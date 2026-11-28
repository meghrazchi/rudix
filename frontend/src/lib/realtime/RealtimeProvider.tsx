"use client";

/**
 * Realtime updates for the authenticated app (R07-07).
 *
 * `RealtimeProvider` (mounted once by `AppShell`) opens `GET /events/stream` when
 * `NEXT_PUBLIC_REALTIME_ENABLED=true`, turns events into query invalidations, and
 * publishes the connection status to a module store. `useRealtime()` reads that store, so
 * it works in any component, including hooks `AppShell` itself calls outside the provider.
 * The stream restarts when the signed-in user or organisation changes.
 */

import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAuthSession } from "@/lib/use-auth-session";
import type { RealtimeStatus } from "@/lib/realtime/types";

export function isRealtimeEnabled(): boolean {
  return process.env.NEXT_PUBLIC_REALTIME_ENABLED === "true";
}

type RealtimeSnapshot = { status: RealtimeStatus; hidden: boolean };

const SERVER_SNAPSHOT: RealtimeSnapshot = { status: "disabled", hidden: false };

function documentHidden(): boolean {
  return (
    typeof document !== "undefined" && document.visibilityState === "hidden"
  );
}

let snapshot: RealtimeSnapshot = { status: "disabled", hidden: false };
const listeners = new Set<() => void>();

function emit(next: RealtimeSnapshot): void {
  if (next.status === snapshot.status && next.hidden === snapshot.hidden) {
    return;
  }
  snapshot = next;
  for (const listener of listeners) {
    listener();
  }
}

export function setRealtimeStatus(status: RealtimeStatus): void {
  emit({ ...snapshot, status });
}

function onVisibilityChange(): void {
  emit({ ...snapshot, hidden: documentHidden() });
}

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0 && typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibilityChange);
    if (snapshot.hidden !== documentHidden()) {
      snapshot = { ...snapshot, hidden: documentHidden() };
    }
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    }
  };
}

function getSnapshot(): RealtimeSnapshot {
  return snapshot;
}

export type UseRealtimeResult = {
  enabled: boolean;
  status: RealtimeStatus;
  hidden: boolean;
};

export function useRealtime(): UseRealtimeResult {
  const current = useSyncExternalStore(
    subscribe,
    getSnapshot,
    () => SERVER_SNAPSHOT,
  );
  const enabled = isRealtimeEnabled();
  return {
    enabled,
    status: enabled ? current.status : "disabled",
    hidden: current.hidden,
  };
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { state } = useAuthSession();
  const userId = state.session?.userId ?? null;
  const organizationId = state.session?.organizationId ?? null;

  useEffect(() => {
    if (!isRealtimeEnabled() || !userId) {
      return;
    }
    let disposed = false;
    let teardown: (() => void) | null = null;
    setRealtimeStatus("connecting");
    // Loaded on demand: with the flag off (the default) no stream code is downloaded.
    void Promise.all([
      import("@/lib/realtime/invalidation"),
      import("@/lib/realtime/stream-client"),
    ]).then(([{ RealtimeInvalidator }, { RealtimeStreamClient }]) => {
      if (disposed) {
        return;
      }
      const invalidator = new RealtimeInvalidator(queryClient);
      const client = new RealtimeStreamClient({
        onEvent: (event) => invalidator.handle(event),
        onStatus: setRealtimeStatus,
        onResync: () => invalidator.resync(),
      });
      const syncVisibility = () => client.setVisible(!documentHidden());
      client.start();
      syncVisibility();
      document.addEventListener("visibilitychange", syncVisibility);
      teardown = () => {
        document.removeEventListener("visibilitychange", syncVisibility);
        client.stop();
        invalidator.dispose();
      };
    });
    return () => {
      disposed = true;
      teardown?.();
      setRealtimeStatus("disabled");
    };
  }, [queryClient, userId, organizationId]);

  return <>{children}</>;
}
