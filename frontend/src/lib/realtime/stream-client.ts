/**
 * Client of `GET /events/stream` (R07-07): one connection per tab, reconnecting.
 *
 * - Reconnects with full-jitter backoff (500 ms base, 30 s cap) after errors and sends
 *   the last seen `Last-Event-ID`, so buffered events are replayed.
 * - `401`: refreshes the access token once, then reconnects; a second `401` backs off.
 * - `404` (disabled) and `503` (no Redis): status `unavailable`, retry after 5 minutes.
 * - `429` (connection cap): backs off.
 * - A tab hidden for 60 s closes the stream; when it is visible again the client
 *   reconnects and calls `onResync` once, so every mapped query is refetched.
 *
 * The server ends each stream after `REALTIME_STREAM_MAX_SECONDS`; the client then
 * reconnects at once (short-lived connections count as failures, so a proxy closing the
 * stream immediately cannot cause a reconnect loop).
 */

import { openEventStream, REALTIME_STREAM_PATH } from "@/lib/api/events";
import {
  refreshAccessToken,
  getSessionRequestContext,
} from "@/lib/api/request";
import { readSseFrames } from "@/lib/realtime/sse-reader";
import {
  parseRealtimeEvent,
  type RealtimeEvent,
  type RealtimeStatus,
} from "@/lib/realtime/types";

export const BACKOFF_BASE_MS = 500;
export const BACKOFF_CAP_MS = 30_000;
export const UNAVAILABLE_RETRY_MS = 5 * 60_000;
export const HIDDEN_CLOSE_MS = 60_000;
const HEALTHY_CONNECTION_MS = 5_000;

export type RealtimeStreamClientOptions = {
  onEvent: (event: RealtimeEvent) => void;
  onStatus: (status: RealtimeStatus) => void;
  onResync?: () => void;
  fetchImpl?: typeof fetch;
  random?: () => number;
  refresh?: () => Promise<unknown>;
  path?: string;
};

/** Full jitter: a uniform delay between 0 and min(cap, base * 2^attempt). */
export function backoffDelay(
  attempt: number,
  random: () => number = Math.random,
): number {
  const ceiling = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** attempt);
  return Math.floor(random() * ceiling);
}

export class RealtimeStreamClient {
  private readonly options: RealtimeStreamClientOptions;
  private controller: AbortController | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private hiddenTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private refreshed = false;
  private running = false;
  private connecting = false;
  private closedWhileHidden = false;
  private lastEventId: string | null = null;
  private status: RealtimeStatus = "connecting";

  constructor(options: RealtimeStreamClientOptions) {
    this.options = options;
  }

  get currentStatus(): RealtimeStatus {
    return this.status;
  }

  start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    this.closedWhileHidden = false;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.clearTimers();
    this.controller?.abort();
    this.controller = null;
  }

  /** Close after 60 s hidden; reconnect (and resync) when visible again. */
  setVisible(visible: boolean): void {
    if (!this.running) {
      return;
    }
    if (!visible) {
      if (this.hiddenTimer === null && !this.closedWhileHidden) {
        this.hiddenTimer = setTimeout(() => {
          this.hiddenTimer = null;
          this.closedWhileHidden = true;
          this.clearRetry();
          this.controller?.abort();
          this.controller = null;
          this.setStatus("connecting");
        }, HIDDEN_CLOSE_MS);
      }
      return;
    }
    if (this.hiddenTimer !== null) {
      clearTimeout(this.hiddenTimer);
      this.hiddenTimer = null;
    }
    if (this.closedWhileHidden) {
      this.closedWhileHidden = false;
      this.attempt = 0;
      this.options.onResync?.();
      this.connect();
    }
  }

  private setStatus(status: RealtimeStatus): void {
    if (this.status !== status) {
      this.status = status;
      this.options.onStatus(status);
    }
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearRetry();
    if (this.hiddenTimer !== null) {
      clearTimeout(this.hiddenTimer);
      this.hiddenTimer = null;
    }
  }

  private schedule(delayMs: number): void {
    this.clearRetry();
    if (!this.running || this.closedWhileHidden) {
      return;
    }
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delayMs);
  }

  private backoff(): void {
    const delay = backoffDelay(this.attempt, this.options.random);
    this.attempt += 1;
    this.schedule(delay);
  }

  private connect(): void {
    if (!this.running || this.connecting || this.closedWhileHidden) {
      return;
    }
    this.connecting = true;
    void this.run().finally(() => {
      this.connecting = false;
    });
  }

  private async run(): Promise<void> {
    if (this.status !== "unavailable") {
      this.setStatus("connecting");
    }
    if (!getSessionRequestContext().token) {
      this.backoff();
      return;
    }
    const controller = new AbortController();
    this.controller = controller;
    let response: Response;
    try {
      response = await openEventStream(
        this.options.path ?? REALTIME_STREAM_PATH,
        {
          lastEventId: this.lastEventId,
          signal: controller.signal,
          fetchImpl: this.options.fetchImpl,
        },
      );
    } catch {
      if (!controller.signal.aborted) {
        this.backoff();
      }
      return;
    }
    if (response.status === 401) {
      await this.handleUnauthorized();
      return;
    }
    if (response.status === 404 || response.status === 503) {
      this.setStatus("unavailable");
      this.schedule(UNAVAILABLE_RETRY_MS);
      return;
    }
    if (!response.ok || !response.body) {
      this.backoff();
      return;
    }
    await this.consume(response.body, controller);
  }

  private async handleUnauthorized(): Promise<void> {
    if (this.refreshed) {
      this.backoff();
      return;
    }
    this.refreshed = true;
    try {
      await (
        this.options.refresh ?? (() => refreshAccessToken({ trigger: "401" }))
      )();
    } catch {
      this.backoff();
      return;
    }
    this.schedule(0);
  }

  private async consume(
    body: ReadableStream<Uint8Array>,
    controller: AbortController,
  ): Promise<void> {
    const openedAt = Date.now();
    this.setStatus("connected");
    this.refreshed = false;
    try {
      for await (const frame of readSseFrames(body)) {
        if (frame.kind !== "event") {
          continue;
        }
        if (frame.id) {
          this.lastEventId = frame.id;
        }
        const event = parseRealtimeEvent(frame.event, frame.data);
        if (event) {
          this.options.onEvent(event);
        }
      }
    } catch {
      // The connection broke; reconnect below.
    }
    if (controller.signal.aborted) {
      return;
    }
    this.controller = null;
    this.setStatus("connecting");
    if (Date.now() - openedAt >= HEALTHY_CONNECTION_MS) {
      this.attempt = 0;
      this.schedule(0);
    } else {
      this.backoff();
    }
  }
}
