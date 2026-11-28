"use client";

import { useQuery } from "@tanstack/react-query";

import { listDocuments } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { useRealtimeAwareInterval } from "@/lib/realtime/polling";

import type { IndexingStatusSummary } from "@/components/documents/list/documents-list-format";

/** Organisation-wide document counts per status, from `total` of one-row pages. */
export function useIndexingStatusSummary() {
  const refetchInterval = useRealtimeAwareInterval(
    (query: { state: { data: unknown } }) => {
      const data = query.state.data as IndexingStatusSummary | undefined;
      return data && data.processing > 0 ? 4_000 : false;
    },
  );
  return useQuery({
    queryKey: queryKeys.documentViews.indexingStatusSummary,
    queryFn: async (): Promise<IndexingStatusSummary> => {
      const [all, uploaded, indexed, processing, failed] = await Promise.all([
        listDocuments({ limit: 1, offset: 0 }),
        listDocuments({ limit: 1, offset: 0, status: "uploaded" }),
        listDocuments({ limit: 1, offset: 0, status: "indexed" }),
        listDocuments({ limit: 1, offset: 0, status: "processing" }),
        listDocuments({ limit: 1, offset: 0, status: "failed" }),
      ]);

      return {
        total: all.total ?? 0,
        uploaded: uploaded.total ?? 0,
        indexed: indexed.total ?? 0,
        processing: processing.total ?? 0,
        failed: failed.total ?? 0,
      };
    },
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}
