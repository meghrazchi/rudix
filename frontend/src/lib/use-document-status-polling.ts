"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { DocumentStatus, DocumentStatusResponse } from "@/lib/api/documents";
import { getDocumentStatus } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { shouldPollDocumentStatus } from "@/lib/documents-ui";

const DEFAULT_STATUS_POLL_INTERVAL_MS = 4_000;

type UseDocumentStatusPollingOptions = {
  enabled?: boolean;
  initialStatus?: DocumentStatus | null;
  pollIntervalMs?: number;
  refetchInBackground?: boolean;
};

export function getDocumentStatusRefetchInterval(
  status: DocumentStatus | null | undefined,
  pollIntervalMs: number = DEFAULT_STATUS_POLL_INTERVAL_MS,
): number | false {
  if (!status) {
    return false;
  }
  return shouldPollDocumentStatus(status) ? pollIntervalMs : false;
}

export function useDocumentStatusPolling(
  documentId: string | null | undefined,
  options: UseDocumentStatusPollingOptions = {},
): UseQueryResult<DocumentStatusResponse> {
  const enabled = options.enabled ?? true;
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_STATUS_POLL_INTERVAL_MS;
  const initialStatus = options.initialStatus ?? null;

  return useQuery({
    queryKey: queryKeys.documents.status(documentId ?? ""),
    queryFn: () => getDocumentStatus(documentId ?? ""),
    enabled: Boolean(documentId) && enabled,
    refetchInterval: (query) => {
      const liveStatus = (query.state.data as DocumentStatusResponse | undefined)?.status;
      return getDocumentStatusRefetchInterval(liveStatus ?? initialStatus, pollIntervalMs);
    },
    refetchIntervalInBackground: options.refetchInBackground ?? false,
  });
}

