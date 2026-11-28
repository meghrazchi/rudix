import { act, renderHook } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/api/query";
import {
  INVALIDATION_BATCH_MS,
  keysForEvent,
  RealtimeInvalidator,
  RESYNC_KEYS,
} from "@/lib/realtime/invalidation";
import {
  realtimeAwareInterval,
  realtimeFallbackPollMs,
  useRealtimeAwareInterval,
} from "@/lib/realtime/polling";
import {
  setRealtimeStatus,
  useRealtime,
} from "@/lib/realtime/RealtimeProvider";
import type { RealtimeEvent } from "@/lib/realtime/types";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

afterEach(() => {
  act(() => setRealtimeStatus("disabled"));
  setVisibility("visible");
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

const base = {
  enabled: true,
  status: "connected",
  hidden: false,
  covered: true,
} as const;

describe("realtimeAwareInterval", () => {
  it("applies the realtime rules", () => {
    expect(realtimeAwareInterval(4000, base)).toBe(false);
    expect(realtimeAwareInterval(4000, { ...base, status: "connecting" })).toBe(
      15_000,
    );
    expect(
      realtimeAwareInterval(60_000, { ...base, status: "unavailable" }),
    ).toBe(60_000);
    expect(realtimeAwareInterval(4000, { ...base, enabled: false })).toBe(4000);
    expect(realtimeAwareInterval(4000, { ...base, covered: false })).toBe(4000);
    expect(
      realtimeAwareInterval(4000, { ...base, enabled: false, hidden: true }),
    ).toBe(false);
    expect(realtimeAwareInterval(false, { ...base, enabled: false })).toBe(
      false,
    );
    expect(realtimeAwareInterval(undefined, base)).toBe(false);
    expect(realtimeAwareInterval(0, { ...base, enabled: false })).toBe(false);
  });

  it("reads the fallback interval from the environment", () => {
    vi.stubEnv("NEXT_PUBLIC_REALTIME_FALLBACK_POLL_MS", "20000");
    expect(realtimeFallbackPollMs()).toBe(20_000);
    vi.stubEnv("NEXT_PUBLIC_REALTIME_FALLBACK_POLL_MS", "junk");
    expect(realtimeFallbackPollMs()).toBe(15_000);
  });
});

describe("useRealtimeAwareInterval", () => {
  it("keeps today's interval while realtime is disabled", () => {
    const { result } = renderHook(() => useRealtimeAwareInterval(4000));
    expect(result.current()).toBe(4000);
  });

  it("follows the stream status and the tab visibility", () => {
    vi.stubEnv("NEXT_PUBLIC_REALTIME_ENABLED", "true");
    const { result } = renderHook(() => ({
      interval: useRealtimeAwareInterval((value: number) => value),
      uncovered: useRealtimeAwareInterval(2000, { covered: false }),
      realtime: useRealtime(),
    }));
    expect(result.current.realtime.status).toBe("disabled");
    act(() => setRealtimeStatus("connecting"));
    expect(result.current.interval(4000)).toBe(15_000);
    act(() => setRealtimeStatus("connected"));
    expect(result.current.realtime.status).toBe("connected");
    expect(result.current.interval(4000)).toBe(false);
    expect(result.current.uncovered()).toBe(2000);
    act(() => setVisibility("hidden"));
    expect(result.current.realtime.hidden).toBe(true);
    expect(result.current.uncovered()).toBe(false);
    act(() => setVisibility("visible"));
    expect(result.current.uncovered()).toBe(2000);
  });
});

function event<T extends RealtimeEvent["type"]>(
  type: T,
  payload: Extract<RealtimeEvent, { type: T }>["payload"],
): RealtimeEvent {
  return {
    type,
    organization_id: "o",
    occurred_at: "",
    payload,
  } as RealtimeEvent;
}

describe("invalidation map", () => {
  it("maps every event type to its query keys", () => {
    expect(keysForEvent(event("documents.changed", {}))).toEqual([
      queryKeys.documents.all,
    ]);
    expect(
      keysForEvent(
        event("document.status", { document_id: "d1", status: "indexed" }),
      ),
    ).toContainEqual(queryKeys.documents.status("d1"));
    expect(
      keysForEvent(event("notification.created", { notification_id: "n1" })),
    ).toContainEqual(queryKeys.notifications.all);
    expect(
      keysForEvent(
        event("connector.sync", {
          connection_id: "c1",
          run_id: "r1",
          status: "running",
        }),
      ),
    ).toContainEqual(queryKeys.connectorSyncRuns("c1"));
    expect(
      keysForEvent(event("agent.run", { run_id: "r1", status: "running" })),
    ).toContainEqual(queryKeys.agent.run("r1"));
    expect(
      keysForEvent(
        event("incident", { incident_id: "i1", status: "resolved" }),
      ),
    ).toContainEqual(queryKeys.statusBanner);
    expect(keysForEvent({ type: "other" } as unknown as RealtimeEvent)).toEqual(
      [],
    );
  });

  it("merges a burst of events into one invalidation per key", () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const invalidator = new RealtimeInvalidator(queryClient);
    invalidator.handle(event("documents.changed", {}));
    invalidator.handle(event("documents.changed", {}));
    expect(spy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(INVALIDATION_BATCH_MS);
    expect(spy).toHaveBeenCalledTimes(1);
    invalidator.resync();
    invalidator.flush();
    expect(spy).toHaveBeenCalledTimes(1 + RESYNC_KEYS.length);
    invalidator.handle(event("documents.changed", {}));
    invalidator.dispose();
    vi.advanceTimersByTime(INVALIDATION_BATCH_MS);
    expect(spy).toHaveBeenCalledTimes(1 + RESYNC_KEYS.length);
  });
});
