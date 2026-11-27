/**
 * Ref-backed store for the streamed answer text (R05-11).
 *
 * `generation.delta` events can arrive hundreds of times per second. Writing
 * each one into React state would re-render the whole chat page per token.
 * Instead the text lives here, outside React: writes update the live text
 * immediately, and subscribers (only `StreamingMessage`, through
 * `useSyncExternalStore`) are notified at most once per animation frame with
 * a new immutable snapshot.
 *
 * Without `requestAnimationFrame` (some test environments, background tabs
 * that never paint) the flush falls back to a 16 ms timer.
 */

export type StreamingTextSnapshot = {
  /** Text published to subscribers at the last flush. */
  readonly text: string;
  /**
   * True once `generation.final` set the authoritative text. Text before that
   * is provisional: it may still be replaced by verification or policy.
   */
  readonly final: boolean;
  /** Increments on every published change; useful for scroll side effects. */
  readonly version: number;
};

export type StreamingTextStore = {
  /** Append a `generation.delta` increment. */
  append: (text: string) => void;
  /** Replace all streamed text (`generation.replace`, or the final answer). */
  replace: (text: string, options?: { final?: boolean }) => void;
  /** Clear text and the final flag; subscribers are notified synchronously. */
  reset: () => void;
  /** The live text, including writes not yet flushed to subscribers. */
  getText: () => string;
  getSnapshot: () => StreamingTextSnapshot;
  getServerSnapshot: () => StreamingTextSnapshot;
  subscribe: (listener: () => void) => () => void;
};

export type FrameScheduler = {
  schedule: (callback: () => void) => unknown;
  cancel: (handle: unknown) => void;
};

export const FALLBACK_FLUSH_MS = 16;

const EMPTY_SNAPSHOT: StreamingTextSnapshot = Object.freeze({
  text: "",
  final: false,
  version: 0,
});

export function defaultFrameScheduler(): FrameScheduler {
  if (
    typeof window !== "undefined" &&
    typeof window.requestAnimationFrame === "function" &&
    typeof window.cancelAnimationFrame === "function"
  ) {
    return {
      schedule: (callback) => window.requestAnimationFrame(() => callback()),
      cancel: (handle) => window.cancelAnimationFrame(handle as number),
    };
  }
  return timerFrameScheduler();
}

export function timerFrameScheduler(
  delayMs: number = FALLBACK_FLUSH_MS,
): FrameScheduler {
  return {
    schedule: (callback) => setTimeout(callback, delayMs),
    cancel: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  };
}

export function createStreamingTextStore(
  scheduler: FrameScheduler = defaultFrameScheduler(),
): StreamingTextStore {
  let text = "";
  let final = false;
  let snapshot: StreamingTextSnapshot = EMPTY_SNAPSHOT;
  let handle: unknown = null;
  const listeners = new Set<() => void>();

  const publish = () => {
    handle = null;
    if (snapshot.text === text && snapshot.final === final) return;
    snapshot = Object.freeze({ text, final, version: snapshot.version + 1 });
    for (const listener of Array.from(listeners)) listener();
  };

  const scheduleFlush = () => {
    if (handle !== null) return;
    handle = scheduler.schedule(publish);
  };

  const cancelFlush = () => {
    if (handle === null) return;
    scheduler.cancel(handle);
    handle = null;
  };

  return {
    append(increment) {
      if (!increment) return;
      text += increment;
      scheduleFlush();
    },
    replace(next, options) {
      text = next;
      if (options?.final) final = true;
      scheduleFlush();
    },
    reset() {
      cancelFlush();
      text = "";
      final = false;
      publish();
    },
    getText: () => text,
    getSnapshot: () => snapshot,
    getServerSnapshot: () => EMPTY_SNAPSHOT,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** A store that never changes, for callers without a streaming transport. */
export const EMPTY_STREAMING_TEXT_STORE: StreamingTextStore = {
  append: () => undefined,
  replace: () => undefined,
  reset: () => undefined,
  getText: () => "",
  getSnapshot: () => EMPTY_SNAPSHOT,
  getServerSnapshot: () => EMPTY_SNAPSHOT,
  subscribe: () => () => undefined,
};
