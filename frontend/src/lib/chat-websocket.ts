/**
 * Typed WebSocket client for the Rudix chat WebSocket endpoint (F277).
 *
 * Responsibilities:
 *  - Manage the WebSocket connection lifecycle
 *  - Emit typed events to registered listeners
 *  - Send heartbeat pong responses
 *  - Support graceful close and caller-driven cancellation
 *  - Reconnect after an unexpected close while a run is in flight, with
 *    exponential backoff and full jitter, and resume the run (R05-13)
 *
 * Auth (R02-10, R05-13): the browser WebSocket API cannot send custom
 * headers, so on every connect, reconnects included, the client awaits
 * `getAuthParam()` (a fresh, single-use ticket from POST /chat/ws-ticket) and
 * appends it as `?ticket=…`. The access token is never put in the URL.
 *
 * Resume (contract 4.2.7): the client remembers the `message_id` of the run in
 * flight and the highest `stream_sequence` it received. On a reconnect it
 * sends `chat.resume` with both; the server replays newer events. The hook
 * discards anything it already applied.
 */

import {
  backoffDelayMs,
  NON_RETRYABLE_CLOSE_CODES,
  resolveReconnectPolicy,
  type ReconnectPolicy,
} from "@/lib/chat/ws-reconnect";

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
  | "generation.replace"
  | "generation.final"
  | "citation.validation.started"
  | "citation.validation.completed"
  | "activity.step.update"
  | "chat.completed"
  | "chat.cancelled"
  | "chat.resumed"
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
  /** Per assistant message, 1, 2, … (contract 4.2.6); absent on older servers. */
  stream_sequence?: number | null;
  timestamp: string;
  payload: Record<string, unknown> | null;
  safe_error_code: string | null;
};

export type ChatWSCommandType =
  | "chat.start"
  | "chat.cancel"
  | "chat.resume"
  | "heartbeat.pong";

export type ChatWSCommand = {
  command: ChatWSCommandType;
  payload?: Record<string, unknown>;
  request_id?: string;
};

export type ChatWSClientState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export type ChatWSAuthParam = { name: "ticket"; value: string };

export type ChatWSReconnectInfo = {
  /** A `chat.resume` command was sent for the run in flight. */
  resumed: boolean;
  /** A queued, unsent `chat.start` was sent, so the run starts on this socket. */
  flushed: boolean;
};

export type ChatWSClientOptions = {
  /** Full WebSocket URL, e.g. ws://localhost:8000/api/v1/chat/ws */
  url: string;
  /**
   * Resolves the handshake query parameter on every connect, normally a fresh
   * single-use ticket. Never cache the result.
   */
  getAuthParam: () => Promise<ChatWSAuthParam>;
  /** Called when getAuthParam fails on a first connect; state is then error. */
  onAuthError?: (error: unknown) => void;
  /** Called for every structured event received from the server */
  onEvent: (event: ChatWSEvent) => void;
  /** Called when the connection state changes */
  onStateChange?: (state: ChatWSClientState) => void;
  /** Called when the socket closes; `willReconnect` is true during a retry. */
  onClose?: (code: number, reason: string, willReconnect: boolean) => void;
  /** Backoff policy (defaults: 500 ms base, 15 s cap, 8 attempts); false disables. */
  reconnect?: Partial<ReconnectPolicy> | false;
  /** Random source in [0, 1) for the jitter; injectable for tests. */
  random?: () => number;
  onReconnecting?: (attempt: number, delayMs: number) => void;
  onReconnected?: (info: ChatWSReconnectInfo) => void;
  /** Reconnecting stopped: attempts exhausted or a non-retryable close code. */
  onReconnectFailed?: (reason: "attempts_exhausted" | "non_retryable") => void;
};

const PONG_COMMAND: ChatWSCommand = { command: "heartbeat.pong" };
const RUN_TERMINAL_EVENTS = new Set<ChatWSEventType>([
  "chat.completed",
  "chat.cancelled",
  "chat.error",
]);

export class ChatWSClient {
  private ws: WebSocket | null = null;
  private _state: ChatWSClientState = "idle";
  private readonly options: ChatWSClientOptions;
  private readonly policy: ReconnectPolicy | null;
  private closed = false;
  /** Commands queued while the socket is still connecting. */
  private readonly pendingQueue: ChatWSCommand[] = [];
  /** In-flight connect (ticket fetch + socket open), guards re-entry. */
  private connectInFlight: Promise<void> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private runInFlight = false;
  private runMessageId: string | null = null;
  private lastStreamSequence = 0;

  constructor(options: ChatWSClientOptions) {
    this.options = options;
    this.policy =
      options.reconnect === false
        ? null
        : resolveReconnectPolicy(options.reconnect ?? {});
  }

  get state(): ChatWSClientState {
    return this._state;
  }

  /** The `chat.resume` command a reconnect would send now, if any. */
  resumeCommand(): ChatWSCommand | null {
    if (!this.runInFlight || !this.runMessageId) return null;
    return {
      command: "chat.resume",
      payload: {
        message_id: this.runMessageId,
        last_stream_sequence: this.lastStreamSequence,
      },
    };
  }

  connect(): Promise<void> {
    if (this.closed || this.ws) return Promise.resolve();
    if (this.connectInFlight) return this.connectInFlight;
    const isReconnect = this._state === "reconnecting";
    this._clearReconnectTimer();
    if (!isReconnect) this._setState("connecting");
    const attempt = this._openSocket(isReconnect).finally(() => {
      this.connectInFlight = null;
    });
    this.connectInFlight = attempt;
    return attempt;
  }

  private async _openSocket(isReconnect: boolean): Promise<void> {
    let auth: ChatWSAuthParam;
    try {
      auth = await this.options.getAuthParam();
    } catch (error) {
      if (this.closed) return;
      if (isReconnect && this._scheduleReconnect()) return;
      this.pendingQueue.length = 0;
      this.runInFlight = false;
      this._setState("error");
      if (isReconnect) this.options.onReconnectFailed?.("attempts_exhausted");
      this.options.onAuthError?.(error);
      return;
    }
    // close() may have run while the ticket was being fetched.
    if (this.closed) return;

    const url = new URL(this.options.url);
    url.searchParams.set(auth.name, auth.value);

    const ws = new WebSocket(url.toString());
    this.ws = ws;
    let errored = false;

    ws.onopen = () => {
      if (this.closed) {
        ws.close();
        return;
      }
      this.reconnectAttempt = 0;
      this._setState("connected");
      // Flush any commands that were queued while connecting.
      const queued = this.pendingQueue.splice(0);
      const startQueued = queued.some((cmd) => cmd.command === "chat.start");
      // On a reconnect, attach to the run first so a command queued during
      // the retry (e.g. chat.cancel) reaches it; an unsent chat.start starts
      // the run on this socket instead.
      const resume = isReconnect && !startQueued ? this.resumeCommand() : null;
      if (resume) this._sendRaw(resume);
      for (const cmd of queued) {
        this._sendRaw(cmd);
      }
      if (!isReconnect) return;
      if (!resume && !startQueued) this.runInFlight = false;
      this.options.onReconnected?.({
        resumed: resume !== null,
        flushed: startQueued,
      });
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
      this._trackRun(parsed);
      this.options.onEvent(parsed);
    };

    ws.onerror = () => {
      // A close event always follows; it decides between retry and error.
      errored = true;
    };

    ws.onclose = (evt: CloseEvent) => {
      if (this.ws === ws) this.ws = null;
      if (this.closed) {
        this.options.onClose?.(evt.code, evt.reason, false);
        return;
      }
      const retryable = !NON_RETRYABLE_CLOSE_CODES.has(evt.code);
      const willReconnect =
        retryable && this.runInFlight && this._scheduleReconnect();
      if (!willReconnect) {
        const wasReconnecting = isReconnect || this.reconnectAttempt > 0;
        this.reconnectAttempt = 0;
        if (this.runInFlight && wasReconnecting) {
          this.options.onReconnectFailed?.(
            retryable ? "attempts_exhausted" : "non_retryable",
          );
        }
        this.runInFlight = false;
        this._setState(errored ? "error" : "disconnected");
      }
      this.options.onClose?.(evt.code, evt.reason, willReconnect);
    };
  }

  /** Schedule the next attempt; false when reconnecting is off or exhausted. */
  private _scheduleReconnect(): boolean {
    const policy = this.policy;
    if (!policy || this.reconnectAttempt >= policy.maxAttempts) return false;
    const delay = backoffDelayMs(
      this.reconnectAttempt,
      policy,
      this.options.random,
    );
    this.reconnectAttempt += 1;
    this._setState("reconnecting");
    this.options.onReconnecting?.(this.reconnectAttempt, delay);
    this._clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
    return true;
  }

  private _clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private _trackRun(event: ChatWSEvent): void {
    if (!this.runInFlight) return;
    if (event.message_id) {
      if (event.message_id !== this.runMessageId) {
        this.runMessageId = event.message_id;
        this.lastStreamSequence = 0;
      }
      const seq = event.stream_sequence;
      if (typeof seq === "number" && seq > this.lastStreamSequence) {
        this.lastStreamSequence = seq;
      }
    }
    if (RUN_TERMINAL_EVENTS.has(event.event)) {
      this.runInFlight = false;
    }
  }

  send(command: ChatWSCommand): void {
    if (command.command === "chat.start") {
      this.runInFlight = true;
      this.runMessageId = null;
      this.lastStreamSequence = 0;
    }
    if (
      this._state === "connecting" ||
      this._state === "reconnecting" ||
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
    this.runInFlight = false;
    this.pendingQueue.length = 0;
    this._clearReconnectTimer();
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
