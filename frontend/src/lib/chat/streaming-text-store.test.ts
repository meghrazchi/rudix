import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createStreamingTextStore,
  defaultFrameScheduler,
  EMPTY_STREAMING_TEXT_STORE,
  FALLBACK_FLUSH_MS,
  timerFrameScheduler,
  type FrameScheduler,
} from "@/lib/chat/streaming-text-store";

function manualScheduler() {
  const queue: Array<() => void> = [];
  const scheduler: FrameScheduler = {
    schedule: (callback) => {
      queue.push(callback);
      return queue.length;
    },
    cancel: (handle) => {
      queue[(handle as number) - 1] = () => undefined;
    },
  };
  return {
    scheduler,
    pending: () => queue.length,
    frame: () => {
      const callbacks = queue.splice(0);
      for (const callback of callbacks) callback();
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("createStreamingTextStore", () => {
  it("notifies subscribers at most once per frame however many deltas arrive", () => {
    const frames = manualScheduler();
    const store = createStreamingTextStore(frames.scheduler);
    const listener = vi.fn();
    store.subscribe(listener);

    for (let i = 0; i < 100; i += 1) store.append(`t${i} `);
    expect(frames.pending()).toBe(1);
    expect(listener).not.toHaveBeenCalled();
    // The live text is current before the flush; the snapshot is not.
    expect(store.getText()).toContain("t99");
    expect(store.getSnapshot().text).toBe("");

    frames.frame();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().text).toBe(store.getText());
    expect(store.getSnapshot().version).toBe(1);

    store.append("more");
    frames.frame();
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("keeps the snapshot identity stable between flushes", () => {
    const frames = manualScheduler();
    const store = createStreamingTextStore(frames.scheduler);
    store.append("a");
    frames.frame();
    const first = store.getSnapshot();
    expect(store.getSnapshot()).toBe(first);
    store.append("");
    frames.frame();
    expect(store.getSnapshot()).toBe(first);
  });

  it("replaces all text and marks the authoritative final text", () => {
    const frames = manualScheduler();
    const store = createStreamingTextStore(frames.scheduler);
    store.append("Draft with an unsupported claim");
    frames.frame();
    expect(store.getSnapshot()).toMatchObject({ final: false });

    store.replace("Verified text");
    frames.frame();
    expect(store.getSnapshot()).toMatchObject({
      text: "Verified text",
      final: false,
    });

    store.replace("Final answer", { final: true });
    frames.frame();
    expect(store.getSnapshot()).toMatchObject({
      text: "Final answer",
      final: true,
    });
  });

  it("publishes a final flag change even when the text is unchanged", () => {
    const frames = manualScheduler();
    const store = createStreamingTextStore(frames.scheduler);
    store.append("same");
    frames.frame();
    store.replace("same", { final: true });
    frames.frame();
    expect(store.getSnapshot().final).toBe(true);
  });

  it("resets synchronously and cancels a pending flush", () => {
    const frames = manualScheduler();
    const store = createStreamingTextStore(frames.scheduler);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.append("x");
    frames.frame();
    store.append("y");
    store.reset();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot()).toMatchObject({ text: "", final: false });
    frames.frame();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    store.append("z");
    frames.frame();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.getServerSnapshot().text).toBe("");
  });

  it("uses requestAnimationFrame when available", () => {
    const raf = vi.fn((callback: FrameRequestCallback) => {
      callback(0);
      return 7;
    });
    const caf = vi.fn();
    vi.stubGlobal("requestAnimationFrame", raf);
    vi.stubGlobal("cancelAnimationFrame", caf);
    const scheduler = defaultFrameScheduler();
    const callback = vi.fn();
    expect(scheduler.schedule(callback)).toBe(7);
    expect(callback).toHaveBeenCalledTimes(1);
    scheduler.cancel(7);
    expect(caf).toHaveBeenCalledWith(7);
  });

  it("falls back to a 16 ms timer without requestAnimationFrame", () => {
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", undefined);
    const store = createStreamingTextStore(defaultFrameScheduler());
    const listener = vi.fn();
    store.subscribe(listener);
    store.append("hello");
    vi.advanceTimersByTime(FALLBACK_FLUSH_MS - 1);
    expect(listener).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(listener).toHaveBeenCalledTimes(1);

    const timer = timerFrameScheduler(5);
    const cancelled = vi.fn();
    timer.cancel(timer.schedule(cancelled));
    vi.advanceTimersByTime(10);
    expect(cancelled).not.toHaveBeenCalled();
  });

  it("offers an inert empty store", () => {
    const listener = vi.fn();
    const unsubscribe = EMPTY_STREAMING_TEXT_STORE.subscribe(listener);
    EMPTY_STREAMING_TEXT_STORE.append("x");
    EMPTY_STREAMING_TEXT_STORE.replace("y");
    EMPTY_STREAMING_TEXT_STORE.reset();
    unsubscribe();
    expect(listener).not.toHaveBeenCalled();
    expect(EMPTY_STREAMING_TEXT_STORE.getText()).toBe("");
    expect(EMPTY_STREAMING_TEXT_STORE.getSnapshot().text).toBe("");
    expect(EMPTY_STREAMING_TEXT_STORE.getServerSnapshot().final).toBe(false);
  });
});
