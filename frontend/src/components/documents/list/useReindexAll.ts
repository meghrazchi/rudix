"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { DocumentStatus } from "@/lib/api/documents";
import { listDocuments, reindexDocument } from "@/lib/api/documents";
import { invalidateAfterMutation } from "@/lib/api/query";
import {
  canReindexDocument,
  getDocumentLifecycleActionErrorMessage,
} from "@/lib/documents-ui";
import { extractRequestIdFromError } from "@/lib/forbidden";

import type { DocumentsPageTranslator } from "@/components/documents/list/documents-list-format";

const REINDEX_ALL_PAGE_SIZE = 200;
const REINDEX_ALL_TARGET_STATUSES: DocumentStatus[] = ["uploaded", "failed"];

type UseReindexAllArgs = {
  tp: DocumentsPageTranslator;
  capabilities: { canReindex: boolean };
  setSelectedDocumentId: Dispatch<SetStateAction<string | null>>;
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
};

/** Queues a reindex for every uploaded or failed document, page by page. */
export function useReindexAll({
  tp,
  capabilities,
  setSelectedDocumentId,
  setActionFeedback,
  setActionRequestId,
}: UseReindexAllArgs) {
  const queryClient = useQueryClient();
  const [isReindexAllPending, setIsReindexAllPending] = useState(false);

  async function fetchDocumentIdsForReindexAllStatus(
    status: DocumentStatus,
  ): Promise<string[]> {
    const ids = new Set<string>();
    let currentOffset = 0;

    while (true) {
      const response = await listDocuments({
        limit: REINDEX_ALL_PAGE_SIZE,
        offset: currentOffset,
        status,
        sort_by: "created_at",
        sort_order: "desc",
      });
      for (const item of response.items) {
        if (canReindexDocument(item.status) && item.status !== "indexed") {
          ids.add(item.document_id);
        }
      }

      currentOffset += response.items.length;
      if (
        response.items.length === 0 ||
        currentOffset >= (response.total ?? 0)
      ) {
        break;
      }
    }

    return Array.from(ids);
  }

  async function handleReindexAllNonIndexedDocuments(): Promise<void> {
    if (!capabilities.canReindex || isReindexAllPending) {
      return;
    }

    setIsReindexAllPending(true);
    setActionFeedback(tp("feedbackReindexCollecting"));
    setActionRequestId(null);

    try {
      const targetIds = new Set<string>();
      for (const status of REINDEX_ALL_TARGET_STATUSES) {
        const ids = await fetchDocumentIdsForReindexAllStatus(status);
        for (const id of ids) {
          targetIds.add(id);
        }
      }

      const orderedTargetIds = Array.from(targetIds);
      if (orderedTargetIds.length === 0) {
        setActionFeedback(tp("feedbackReindexNoEligible"));
        setActionRequestId(null);
        return;
      }

      let queuedCount = 0;
      let failedCount = 0;
      let lastErrorRequestId: string | null = null;
      let firstQueuedDocumentId: string | null = null;

      for (const [index, documentId] of orderedTargetIds.entries()) {
        setActionFeedback(
          tp("feedbackReindexProgress", {
            current: index + 1,
            total: orderedTargetIds.length,
          }),
        );
        try {
          await reindexDocument(documentId);
          queuedCount += 1;
          if (!firstQueuedDocumentId) {
            firstQueuedDocumentId = documentId;
          }
        } catch (error) {
          failedCount += 1;
          const requestId = extractRequestIdFromError(error);
          if (requestId) {
            lastErrorRequestId = requestId;
          }
        }
      }

      if (queuedCount > 0 && failedCount === 0) {
        setActionFeedback(tp("feedbackReindexQueued", { count: queuedCount }));
        setActionRequestId(null);
      } else if (queuedCount > 0) {
        setActionFeedback(
          tp("feedbackReindexQueuedWithFailed", {
            queued: queuedCount,
            failed: failedCount,
          }),
        );
        setActionRequestId(lastErrorRequestId);
      } else {
        setActionFeedback(tp("feedbackReindexNoneQueued"));
        setActionRequestId(lastErrorRequestId);
      }

      if (firstQueuedDocumentId) {
        setSelectedDocumentId(firstQueuedDocumentId);
      }
      await invalidateAfterMutation(queryClient, "document.reindex");
    } catch (error) {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("reindex", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    } finally {
      setIsReindexAllPending(false);
    }
  }

  return { isReindexAllPending, handleReindexAllNonIndexedDocuments };
}
