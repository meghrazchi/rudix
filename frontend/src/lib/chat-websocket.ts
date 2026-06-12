/**
 * Typed WebSocket client for the Rudix chat WebSocket endpoint (F277).
 *
 * Responsibilities:
 *  - Manage a single WebSocket connection lifecycle
 *  - Emit typed events to registered listeners
 *  - Send heartbeat pong responses
 *  - Support graceful close and caller-driven cancellation
 *
 * Auth: the caller passes the current access token; it is appended as a
 * query parameter (?token=…). This is a common pattern for WebSocket auth
 * because the browser native WebSocket API does not allow custom headers.
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
  | "chat.completed"
  | "chat.cancelled"
  | "chat.error"
  | "heartbeat.ping";

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

export type ChatWSClientOptions = {
  /** Full WebSocket URL, e.g. ws://localhost:8000/api/v1/chat/ws */
  url: string;
  /** Bearer access token — appended as ?token=… */
  token: string;
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

  constructor(options: ChatWSClientOptions) {
    this.options = options;
  }

  get state(): ChatWSClientState {
    return this._state;
  }

  connect(): void {
    if (this.closed || this.ws) return;
    this._setState("connecting");

    const url = new URL(this.options.url);
    url.searchParams.set("token", this.options.token);

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
    if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
      // Socket exists but not yet open — queue for when onopen fires.
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
