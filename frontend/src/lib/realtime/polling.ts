"use client";

/**
 * Realtime-aware polling intervals (R07-07).
 *
 * `useRealtimeAwareInterval(base)` returns a `refetchInterval` function for TanStack
 * Query. `base` is today's interval (a number, `false`, or a function of the query):
 *
 * - tab hidden: `false` (never poll in a hidden tab; `refetchOnWindowFocus` refreshes);
 * - realtime disabled: `base` (today's behaviour);
 * - stream connected: `false`, because events invalidate the query;
 * - enabled but not connected: at least `NEXT_PUBLIC_REALTIME_FALLBACK_POLL_MS` (15 s).
 *
 * Data that no event describes (health checks, evaluation progress, item counts inside a
 * running sync) passes `{ covered: false }` and keeps `base` while visible.
 */

import { useCallback } from "react";

import { useRealtime } from "@/lib/realtime/RealtimeProvider";
import type { RealtimeStatus } from "@/lib/realtime/types";

const DEFAULT_FALLBACK_POLL_MS = 15_000;

export function realtimeFallbackPollMs(): number {
  const parsed = Number.parseInt(
    process.env.NEXT_PUBLIC_REALTIME_FALLBACK_POLL_MS ?? "",
    10,
  );
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_FALLBACK_POLL_MS;
}

export type IntervalValue = number | false;

export type RealtimeIntervalState = {
  enabled: boolean;
  status: RealtimeStatus;
  hidden: boolean;
  covered: boolean;
};

/** The pure rule behind the hook. */
export function realtimeAwareInterval(
  base: IntervalValue | undefined,
  state: RealtimeIntervalState,
): IntervalValue {
  if (base === undefined || base === false || base <= 0) {
    return false;
  }
  if (state.hidden) {
    return false;
  }
  if (!state.enabled || !state.covered) {
    return base;
  }
  if (state.status === "connected") {
    return false;
  }
  return Math.max(base, realtimeFallbackPollMs());
}

type BaseInterval<TArgs extends unknown[]> =
  | IntervalValue
  | ((...args: TArgs) => IntervalValue | undefined);

export type RealtimeAwareIntervalOptions = { covered?: boolean };

export function useRealtimeAwareInterval<TArgs extends unknown[]>(
  base: BaseInterval<TArgs>,
  options: RealtimeAwareIntervalOptions = {},
): (...args: TArgs) => IntervalValue {
  const { enabled, status, hidden } = useRealtime();
  const covered = options.covered ?? true;
  return useCallback(
    (...args: TArgs) => {
      const value = typeof base === "function" ? base(...args) : base;
      const isHidden =
        hidden ||
        (typeof document !== "undefined" &&
          document.visibilityState === "hidden");
      return realtimeAwareInterval(value, {
        enabled,
        status,
        hidden: isHidden,
        covered,
      });
    },
    [base, enabled, status, hidden, covered],
  );
}
