/**
 * Map realtime events to the TanStack Query keys they make stale (R07-07).
 *
 * An event never carries data the UI renders; it only invalidates queries, which refetch
 * through the normal API (and its access checks). Keys arriving within
 * `INVALIDATION_BATCH_MS` are merged, so a burst of status changes causes one refetch.
 */

import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { queryKeys } from "@/lib/api/query";
import type { RealtimeEvent } from "@/lib/realtime/types";

export const INVALIDATION_BATCH_MS = 250;

export function keysForEvent(event: RealtimeEvent): QueryKey[] {
  switch (event.type) {
    case "documents.changed":
      return [queryKeys.documents.all];
    case "document.status":
      return [
        queryKeys.documents.all,
        queryKeys.documents.status(event.payload.document_id),
        queryKeys.documents.detail(event.payload.document_id),
      ];
    case "notification.created":
      return [
        queryKeys.notifications.all,
        queryKeys.realtime.topBarNotifications,
      ];
    case "connector.sync":
      return [
        queryKeys.connectorSyncRuns(event.payload.connection_id),
        queryKeys.connectorSyncRun(event.payload.run_id),
        queryKeys.connectorConnection(event.payload.connection_id),
        queryKeys.connectorConnections,
      ];
    case "agent.run":
      return [
        queryKeys.agent.run(event.payload.run_id),
        queryKeys.realtime.agentRuns,
        queryKeys.realtime.agentApprovals,
      ];
    case "incident":
      return [
        queryKeys.statusBanner,
        queryKeys.admin.statusSnapshot,
        queryKeys.realtime.adminIncidents,
      ];
    default:
      return [];
  }
}

/** Every key an event can touch; refetched after the stream was closed for a while. */
export const RESYNC_KEYS: readonly QueryKey[] = [
  queryKeys.documents.all,
  queryKeys.notifications.all,
  queryKeys.realtime.topBarNotifications,
  queryKeys.realtime.connectors,
  queryKeys.realtime.agentRuns,
  queryKeys.realtime.agentApprovals,
  queryKeys.agent.all,
  queryKeys.statusBanner,
  queryKeys.admin.statusSnapshot,
  queryKeys.realtime.adminIncidents,
];

export class RealtimeInvalidator {
  private readonly queryClient: QueryClient;
  private pending = new Map<string, QueryKey>();
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(queryClient: QueryClient) {
    this.queryClient = queryClient;
  }

  handle(event: RealtimeEvent): void {
    this.enqueue(keysForEvent(event));
  }

  resync(): void {
    this.enqueue(RESYNC_KEYS);
  }

  private enqueue(keys: readonly QueryKey[]): void {
    for (const key of keys) {
      this.pending.set(JSON.stringify(key), key);
    }
    if (this.timer === null && this.pending.size > 0) {
      this.timer = setTimeout(() => this.flush(), INVALIDATION_BATCH_MS);
    }
  }

  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const keys = [...this.pending.values()];
    this.pending.clear();
    for (const queryKey of keys) {
      void this.queryClient.invalidateQueries({ queryKey });
    }
  }

  dispose(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.pending.clear();
  }
}
