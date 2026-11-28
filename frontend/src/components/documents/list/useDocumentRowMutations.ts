"use client";

import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  bulkDeleteDocuments,
  deleteDocument,
  downloadDocumentFile,
  reindexDocument,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation } from "@/lib/api/query";
import { getDocumentLifecycleActionErrorMessage } from "@/lib/documents-ui";
import { extractRequestIdFromError } from "@/lib/forbidden";

import {
  triggerBlobDownload,
  type DocumentsPageTranslator,
} from "@/components/documents/list/documents-list-format";

type UseDocumentRowMutationsArgs = {
  tp: DocumentsPageTranslator;
  selectedDocumentId: string | null;
  setSelectedDocumentId: Dispatch<SetStateAction<string | null>>;
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>;
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
};

/** Delete, bulk delete, reindex, and download actions of the documents table. */
export function useDocumentRowMutations({
  tp,
  selectedDocumentId,
  setSelectedDocumentId,
  setSelectedIds,
  setActionFeedback,
  setActionRequestId,
}: UseDocumentRowMutationsArgs) {
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: async (result, documentId) => {
      if (result.status === "retained_by_policy") {
        setActionFeedback(
          tp("deleteRetained", {
            reason: result.hold_reason ?? tp("noReason"),
          }),
        );
      } else {
        setActionFeedback(tp("deleteRequested", { status: result.status }));
      }
      setActionRequestId(null);
      if (selectedDocumentId === documentId && result.status === "deleted") {
        setSelectedDocumentId(null);
      }
      await invalidateAfterMutation(queryClient, "document.delete");
    },
    onError: (error) => {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("delete", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: (documentIds: string[]) => bulkDeleteDocuments(documentIds),
    onSuccess: async (result) => {
      const parts: string[] = [];
      if (result.accepted > 0)
        parts.push(tp("bulkDeleteQueued", { count: result.accepted }));
      if (result.retained > 0)
        parts.push(tp("bulkDeleteRetained", { count: result.retained }));
      if (result.errors > 0)
        parts.push(tp("bulkDeleteErrors", { count: result.errors }));
      setActionFeedback(parts.join(", ") + ".");
      setActionRequestId(null);
      setSelectedIds(new Set());
      await invalidateAfterMutation(queryClient, "document.delete");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const reindexMutation = useMutation({
    mutationFn: (documentId: string) => reindexDocument(documentId),
    onSuccess: async (result, documentId) => {
      setActionFeedback(
        tp("reindexRequested", { documentId, status: result.queue_status }),
      );
      setActionRequestId(null);
      setSelectedDocumentId(documentId);
      await invalidateAfterMutation(queryClient, "document.reindex");
    },
    onError: (error) => {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("reindex", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const downloadMutation = useMutation({
    mutationFn: async (params: { documentId: string; filename: string }) => {
      const blob = await downloadDocumentFile(params.documentId);
      return { blob, filename: params.filename };
    },
    onSuccess: ({ blob, filename }) => {
      triggerBlobDownload(blob, filename);
      setActionFeedback(null);
      setActionRequestId(null);
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  return {
    deleteMutation,
    bulkDeleteMutation,
    reindexMutation,
    downloadMutation,
  };
}
