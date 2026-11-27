/**
 * Reconnect policy and resume bookkeeping for the chat WebSocket (R05-13).
 *
 * Backoff is exponential with full jitter: attempt `n` (0-based) waits a
 * uniformly random time in `[0, min(capMs, baseMs * 2^n)]`, which spreads a
 * fleet of clients reconnecting after a server restart.
 */

export type ReconnectPolicy = {
  baseMs: number;
  capMs: number;
  maxAttempts: number;
};

export const DEFAULT_RECONNECT_POLICY: Readonly<ReconnectPolicy> =
  Object.freeze({ baseMs: 500, capMs: 15_000, maxAttempts: 8 });

/** Close codes after which reconnecting cannot help (auth, role, disabled). */
export const NON_RETRYABLE_CLOSE_CODES: ReadonlySet<number> = new Set([
  1008, 4401, 4403, 4503,
]);

function positiveOr(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}

/** Fill missing or invalid fields from the default policy. */
export function resolveReconnectPolicy(
  partial: Partial<ReconnectPolicy> = {},
): ReconnectPolicy {
  return {
    baseMs: positiveOr(partial.baseMs, DEFAULT_RECONNECT_POLICY.baseMs),
    capMs: positiveOr(partial.capMs, DEFAULT_RECONNECT_POLICY.capMs),
    maxAttempts: Math.trunc(
      positiveOr(partial.maxAttempts, DEFAULT_RECONNECT_POLICY.maxAttempts),
    ),
  };
}

/** Upper bound of the delay before attempt `attempt` (0-based). */
export function backoffCeilingMs(
  attempt: number,
  policy: ReconnectPolicy,
): number {
  const exponent = Math.max(0, Math.min(attempt, 30));
  return Math.min(policy.capMs, policy.baseMs * 2 ** exponent);
}

/** Full-jitter delay; `random` returns a value in `[0, 1)`. */
export function backoffDelayMs(
  attempt: number,
  policy: ReconnectPolicy,
  random: () => number = Math.random,
): number {
  const sample = Math.min(Math.max(random(), 0), 1);
  return Math.floor(sample * backoffCeilingMs(attempt, policy));
}

/**
 * Tracks the highest `stream_sequence` applied per assistant message so a
 * resumed stream never applies the same event twice.
 */
export class StreamSequenceTracker {
  private readonly applied = new Map<string, number>();
  private current: string | null = null;

  /**
   * Returns false when the event was already applied. Events without a
   * message id or a numeric `stream_sequence` (older servers) always apply.
   */
  accept(messageId: string | null, streamSequence: unknown): boolean {
    if (!messageId) return true;
    this.current = messageId;
    if (typeof streamSequence !== "number" || !Number.isFinite(streamSequence))
      return true;
    const last = this.applied.get(messageId) ?? 0;
    if (streamSequence <= last) return false;
    this.applied.set(messageId, streamSequence);
    return true;
  }

  /** The message of the run in flight, once `generation.started` named it. */
  get messageId(): string | null {
    return this.current;
  }

  lastSequence(messageId: string): number {
    return this.applied.get(messageId) ?? 0;
  }

  reset(): void {
    this.applied.clear();
    this.current = null;
  }
}
