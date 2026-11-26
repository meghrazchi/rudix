/**
 * Typed WebSocket client for the Rudix chat WebSocket endpoint (F277).
 *
 * Responsibilities:
 *  - Manage a single WebSocket connection lifecycle
 *  - Emit typed events to registered listeners
 *  - Send heartbeat pong responses
 *  - Support graceful close and caller-driven cancellation
 *
 * Auth (R02-10): the browser WebSocket API cannot send custom headers, so
 * on every connect the client awaits `getAuthParam()` (normally a fresh,
 * single-use ticket from POST /chat/ws-ticket) and appends it as `?ticket=…`.
 * The access token is never put in the URL, except for the temporary legacy
 * fallback against backends without the ticket endpoint (see chat-ws-auth.ts).
 */

export type ChatWSEventType =
  | "connection.ready"
  | "chat.request.received"
  | "chat.scope.validated"
  | "retrieval.started"
  | "retrieval.completed"
  | "rerank.started"
  | "rerank.completed"
  | "generation.started"
  | "generation.delta"
  | "citation.validation.started"
  | "citation.validation.completed"
  | "activity.step.update"
  | "chat.completed"
  | "chat.cancelled"
  | "chat.error"
  | "heartbeat.ping";

export type ActivityStepState =
  | "pending"
  | "running"
  | "success"
  | "warning"
  | "failed"
  | "skipped";

export type ActivityTimelineStep = {
  stepKey: string;
  sequence: number;
  label: string;
  state: ActivityStepState;
  detail: string | null;
  durationMs: number | null;
};

export type ChatWSEvent = {
  event: ChatWSEventType;
  request_id: string | null;
  conversation_id: string | null;
  message_id: string | null;
  sequence: number;
  timestamp: string;
  payload: Record<string, unknown> | null;
  safe_error_code: string | null;
};

export type ChatWSCommandType = "chat.start" | "chat.cancel" | "heartbeat.pong";

export type ChatWSCommand = {
  command: ChatWSCommandType;
  payload?: Record<string, unknown>;
  request_id?: string;
};

export type ChatWSClientState =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export type ChatWSAuthParam = { name: "ticket" | "token"; value: string };

export type ChatWSClientOptions = {
  /** Full WebSocket URL, e.g. ws://localhost:8000/api/v1/chat/ws */
  url: string;
  /**
   * Resolves the handshake query parameter on every connect, normally a fresh
   * single-use ticket. Never cache the result.
   */
  getAuthParam: () => Promise<ChatWSAuthParam>;
  /** Called when getAuthParam fails; the client is then in the error state. */
  onAuthError?: (error: unknown) => void;
  /** Called for every structured event received from the server */
  onEvent: (event: ChatWSEvent) => void;
  /** Called when the connection state changes */
  onStateChange?: (state: ChatWSClientState) => void;
  /** Called when the socket closes (code, reason) */
  onClose?: (code: number, reason: string) => void;
};

const PONG_COMMAND: ChatWSCommand = { command: "heartbeat.pong" };

export class ChatWSClient {
  private ws: WebSocket | null = null;
  private _state: ChatWSClientState = "idle";
  private readonly options: ChatWSClientOptions;
  private closed = false;
  /** Commands queued while the socket is still connecting. */
  private readonly pendingQueue: ChatWSCommand[] = [];
  /** In-flight connect (ticket fetch + socket open), guards re-entry. */
  private connectInFlight: Promise<void> | null = null;

  constructor(options: ChatWSClientOptions) {
    this.options = options;
  }

  get state(): ChatWSClientState {
    return this._state;
  }

  connect(): Promise<void> {
    if (this.closed || this.ws) return Promise.resolve();
    if (this.connectInFlight) return this.connectInFlight;
    this._setState("connecting");
    const attempt = this._openSocket().finally(() => {
      this.connectInFlight = null;
    });
    this.connectInFlight = attempt;
    return attempt;
  }

  private async _openSocket(): Promise<void> {
    let auth: ChatWSAuthParam;
    try {
      auth = await this.options.getAuthParam();
    } catch (error) {
      if (this.closed) return;
      this.pendingQueue.length = 0;
      this._setState("error");
      this.options.onAuthError?.(error);
      return;
    }
    // close() may have run while the ticket was being fetched.
    if (this.closed) return;

    const url = new URL(this.options.url);
    url.searchParams.set(auth.name, auth.value);

    const ws = new WebSocket(url.toString());
    this.ws = ws;

    ws.onopen = () => {
      if (this.closed) {
        ws.close();
        return;
      }
      this._setState("connected");
      // Flush any commands that were queued while connecting.
      for (const cmd of this.pendingQueue.splice(0)) {
        this._sendRaw(cmd);
      }
    };

    ws.onmessage = (evt: MessageEvent<string>) => {
      let parsed: ChatWSEvent;
      try {
        parsed = JSON.parse(evt.data) as ChatWSEvent;
      } catch {
        return;
      }
      if (parsed.event === "heartbeat.ping") {
        this._sendRaw(PONG_COMMAND);
      }
      this.options.onEvent(parsed);
    };

    ws.onerror = () => {
      this._setState("error");
    };

    ws.onclose = (evt: CloseEvent) => {
      this.ws = null;
      if (!this.closed) {
        this._setState("disconnected");
      }
      this.options.onClose?.(evt.code, evt.reason);
    };
  }

  send(command: ChatWSCommand): void {
    if (
      this._state === "connecting" ||
      (this.ws && this.ws.readyState === WebSocket.CONNECTING)
    ) {
      // Still fetching the ticket or opening the socket — queue for onopen.
      this.pendingQueue.push(command);
    } else {
      this._sendRaw(command);
    }
  }

  close(): void {
    this.closed = true;
    this.pendingQueue.length = 0;
    if (this.ws) {
      this.ws.close(1000, "client_closed");
      this.ws = null;
    }
    this._setState("idle");
  }

  private _sendRaw(command: ChatWSCommand): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(command));
    }
  }

  private _setState(next: ChatWSClientState): void {
    if (this._state === next) return;
    this._state = next;
    this.options.onStateChange?.(next);
  }
}

/** Build the WebSocket URL from the configured API base URL. */
export function buildChatWsUrl(apiBaseUrl: string): string {
  const base = apiBaseUrl.replace(/^http/, "ws").replace(/\/$/, "");
  return `${base}/chat/ws`;
}
