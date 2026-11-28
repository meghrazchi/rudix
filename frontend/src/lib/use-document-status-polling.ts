"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type {
  DocumentStatus,
  DocumentStatusResponse,
} from "@/lib/api/documents";
import { getDocumentStatus } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { shouldPollDocumentStatus } from "@/lib/documents-ui";
import { useRealtimeAwareInterval } from "@/lib/realtime/polling";

const DEFAULT_STATUS_POLL_INTERVAL_MS = 4_000;

type UseDocumentStatusPollingOptions = {
  enabled?: boolean;
  initialStatus?: DocumentStatus | null;
  pollIntervalMs?: number;
};

export function getDocumentStatusRefetchInterval(
  status: DocumentStatus | null | undefined,
  graphStatus: string | null | undefined = null,
  pollIntervalMs: number = DEFAULT_STATUS_POLL_INTERVAL_MS,
): number | false {
  if (!status) {
    return false;
  }
  return shouldPollDocumentStatus(status, graphStatus) ? pollIntervalMs : false;
}

export function useDocumentStatusPolling(
  documentId: string | null | undefined,
  options: UseDocumentStatusPollingOptions = {},
): UseQueryResult<DocumentStatusResponse> {
  const enabled = options.enabled ?? true;
  const pollIntervalMs =
    options.pollIntervalMs ?? DEFAULT_STATUS_POLL_INTERVAL_MS;
  const initialStatus = options.initialStatus ?? null;

  // R07-07: no polling while the realtime stream is connected or the tab is hidden.
  const refetchInterval = useRealtimeAwareInterval(
    (query: { state: { data: unknown } }) => {
      const data = query.state.data as DocumentStatusResponse | undefined;
      return getDocumentStatusRefetchInterval(
        data?.status ?? initialStatus,
        data?.graph_extraction_status ?? null,
        pollIntervalMs,
      );
    },
  );

  return useQuery({
    queryKey: queryKeys.documents.status(documentId ?? ""),
    queryFn: () => getDocumentStatus(documentId ?? ""),
    enabled: Boolean(documentId) && enabled,
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}
