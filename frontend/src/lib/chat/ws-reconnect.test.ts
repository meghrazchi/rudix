import { describe, expect, it } from "vitest";

import {
  backoffCeilingMs,
  backoffDelayMs,
  DEFAULT_RECONNECT_POLICY,
  NON_RETRYABLE_CLOSE_CODES,
  resolveReconnectPolicy,
  StreamSequenceTracker,
} from "@/lib/chat/ws-reconnect";

describe("reconnect backoff", () => {
  const policy = resolveReconnectPolicy();

  it("defaults to 500 ms base, 15 s cap and 8 attempts", () => {
    expect(policy).toEqual({ baseMs: 500, capMs: 15_000, maxAttempts: 8 });
    expect(DEFAULT_RECONNECT_POLICY).toEqual(policy);
  });

  it("doubles the ceiling per attempt up to the cap", () => {
    const ceilings = Array.from({ length: 8 }, (_, n) =>
      backoffCeilingMs(n, policy),
    );
    expect(ceilings).toEqual([
      500, 1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000,
    ]);
    expect(backoffCeilingMs(-3, policy)).toBe(500);
    expect(backoffCeilingMs(1_000, policy)).toBe(15_000);
  });

  it("uses full jitter between zero and the ceiling", () => {
    expect(backoffDelayMs(3, policy, () => 0)).toBe(0);
    expect(backoffDelayMs(3, policy, () => 0.5)).toBe(2_000);
    expect(backoffDelayMs(3, policy, () => 0.999999)).toBe(3_999);
    // Out-of-range random sources are clamped into the window.
    expect(backoffDelayMs(3, policy, () => 7)).toBe(4_000);
    expect(backoffDelayMs(3, policy, () => -1)).toBe(0);
  });

  it("stays within bounds for many random samples", () => {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const ceiling = backoffCeilingMs(attempt, policy);
      const samples = Array.from({ length: 200 }, () =>
        backoffDelayMs(attempt, policy),
      );
      expect(Math.min(...samples)).toBeGreaterThanOrEqual(0);
      expect(Math.max(...samples)).toBeLessThanOrEqual(ceiling);
      // Jitter: delays actually vary.
      expect(new Set(samples).size).toBeGreaterThan(1);
    }
  });

  it("accepts a configured policy and ignores invalid fields", () => {
    expect(
      resolveReconnectPolicy({ baseMs: 100, capMs: 1_000, maxAttempts: 3 }),
    ).toEqual({ baseMs: 100, capMs: 1_000, maxAttempts: 3 });
    expect(
      resolveReconnectPolicy({ baseMs: -1, capMs: Number.NaN, maxAttempts: 0 }),
    ).toEqual(DEFAULT_RECONNECT_POLICY);
    expect(resolveReconnectPolicy({ maxAttempts: 2.7 }).maxAttempts).toBe(2);
  });

  it("never retries auth, role or disabled closes", () => {
    for (const code of [4401, 4403, 4503, 1008]) {
      expect(NON_RETRYABLE_CLOSE_CODES.has(code)).toBe(true);
    }
    expect(NON_RETRYABLE_CLOSE_CODES.has(1006)).toBe(false);
    expect(NON_RETRYABLE_CLOSE_CODES.has(4429)).toBe(false);
  });
});

describe("StreamSequenceTracker", () => {
  it("discards an already applied (message_id, stream_sequence)", () => {
    const tracker = new StreamSequenceTracker();
    expect(tracker.accept("m1", 1)).toBe(true);
    expect(tracker.accept("m1", 2)).toBe(true);
    expect(tracker.accept("m1", 2)).toBe(false);
    expect(tracker.accept("m1", 1)).toBe(false);
    expect(tracker.accept("m1", 3)).toBe(true);
    expect(tracker.lastSequence("m1")).toBe(3);
    expect(tracker.messageId).toBe("m1");
  });

  it("tracks messages independently and always applies unsequenced events", () => {
    const tracker = new StreamSequenceTracker();
    expect(tracker.accept(null, 5)).toBe(true);
    expect(tracker.accept("m1", undefined)).toBe(true);
    expect(tracker.accept("m1", null)).toBe(true);
    expect(tracker.accept("m1", 4)).toBe(true);
    expect(tracker.accept("m2", 1)).toBe(true);
    expect(tracker.lastSequence("m2")).toBe(1);
    expect(tracker.lastSequence("unknown")).toBe(0);
    tracker.reset();
    expect(tracker.messageId).toBeNull();
    expect(tracker.accept("m1", 4)).toBe(true);
  });
});
