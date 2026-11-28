"use client";

import type { Dispatch, SetStateAction } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { useTranslations } from "next-intl";

import type {
  AdminLanguageOverrideRequest,
  AdminOcrConfigRequest,
  AdminTrustStatusRequest,
  DocumentDetailResponse,
  DocumentQualityState,
  ReindexDocumentRequest,
} from "@/lib/api/documents";
import {
  configureDocumentOcr,
  deleteDocument,
  downloadDocumentFile,
  overrideDocumentLanguage,
  reindexDocument,
  reindexDocumentGraph,
  updateDocumentTrustStatus,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { getDocumentLifecycleActionErrorMessage } from "@/lib/documents-ui";
import { extractRequestIdFromError } from "@/lib/forbidden";

import { triggerBlobDownload } from "@/components/documents/detail/detail-format";
import type { ReindexMutationInput } from "@/components/documents/detail/detail-lifecycle";

export type DocumentDetailTranslator = ReturnType<
  typeof useTranslations<"documents.detail">
>;

type Refetchable = { refetch: () => Promise<unknown> };

export type QualityDrafts = {
  qualityStateDraft: DocumentQualityState;
  qualityNotesDraft: string;
  qualityOwnerDraft: string;
  qualityReviewerDraft: string;
  qualityDueDateDraft: string;
  qualityExpiryDateDraft: string;
  qualityReviewDateDraft: string;
  qualityTrustLevelDraft: string;
};

type UseDocumentDetailMutationsArgs = {
  documentId: string;
  td: DocumentDetailTranslator;
  detail: DocumentDetailResponse | undefined;
  detailQuery: Refetchable;
  statusQuery: Refetchable;
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
  setLangOverrideOpen: Dispatch<SetStateAction<boolean>>;
  setOcrLangOverrideOpen: Dispatch<SetStateAction<boolean>>;
  qualityDrafts: QualityDrafts;
};

/** Lifecycle, language, OCR, and quality mutations of the document detail page. */
export function useDocumentDetailMutations({
  documentId,
  td,
  detail,
  detailQuery,
  statusQuery,
  setActionFeedback,
  setActionRequestId,
  setLangOverrideOpen,
  setOcrLangOverrideOpen,
  qualityDrafts,
}: UseDocumentDetailMutationsArgs) {
  const queryClient = useQueryClient();
  const {
    qualityStateDraft,
    qualityNotesDraft,
    qualityOwnerDraft,
    qualityReviewerDraft,
    qualityDueDateDraft,
    qualityExpiryDateDraft,
    qualityReviewDateDraft,
    qualityTrustLevelDraft,
  } = qualityDrafts;

  const deleteMutation = useMutation({
    mutationFn: () => deleteDocument(documentId),
    onSuccess: async (result) => {
      setActionFeedback(
        td("feedbackDeleteRequested", { status: result.status }),
      );
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "document.delete");
      await detailQuery.refetch();
      await statusQuery.refetch();
    },
    onError: (error) => {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("delete", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const reindexMutation = useMutation({
    mutationFn: (input?: ReindexMutationInput) => {
      if (!input) {
        return reindexDocument(documentId);
      }
      const payload: ReindexDocumentRequest = {
        ...(input.payload ?? {}),
      };
      if (input.force) {
        payload.force = true;
      }
      return Object.keys(payload).length > 0
        ? reindexDocument(documentId, payload)
        : reindexDocument(documentId);
    },
    onSuccess: async (result, variables) => {
      setActionFeedback(
        variables?.force
          ? td("feedbackForceReindex", { queueStatus: result.queue_status })
          : variables?.label
            ? td("feedbackReindexWithProfile", {
                label: variables.label,
                queueStatus: result.queue_status,
              })
            : td("feedbackReindex", { queueStatus: result.queue_status }),
      );
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "document.reindex");
      await detailQuery.refetch();
      await statusQuery.refetch();
    },
    onError: (error) => {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("reindex", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const graphReindexMutation = useMutation({
    mutationFn: () => reindexDocumentGraph(documentId),
    onSuccess: async (result) => {
      setActionFeedback(
        td("feedbackGraphReindex", { queueStatus: result.queue_status }),
      );
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "document.graph.reindex");
      await detailQuery.refetch();
      await statusQuery.refetch();
    },
    onError: (error) => {
      setActionFeedback(
        getDocumentLifecycleActionErrorMessage("reindex", error),
      );
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const downloadMutation = useMutation({
    mutationFn: async () => {
      const blob = await downloadDocumentFile(documentId);
      return blob;
    },
    onSuccess: (blob) => {
      const fallbackFilename = `document-${documentId}`;
      const filename = detail?.filename?.trim() || fallbackFilename;
      triggerBlobDownload(blob, filename);
      setActionFeedback(null);
      setActionRequestId(null);
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const langOverrideMutation = useMutation({
    mutationFn: (payload: AdminLanguageOverrideRequest) =>
      overrideDocumentLanguage(documentId, payload),
    onSuccess: () => {
      setLangOverrideOpen(false);
      setActionFeedback(td("feedbackLangSaved"));
      setActionRequestId(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      });
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const ocrConfigMutation = useMutation({
    mutationFn: (payload: AdminOcrConfigRequest) =>
      configureDocumentOcr(documentId, payload),
    onSuccess: () => {
      setOcrLangOverrideOpen(false);
      setActionFeedback(td("feedbackOcrSaved"));
      setActionRequestId(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      });
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const qualityMutation = useMutation({
    mutationFn: (payload: AdminTrustStatusRequest) =>
      updateDocumentTrustStatus(documentId, payload),
    onSuccess: async () => {
      setActionFeedback(td("feedbackQualitySaved"));
      setActionRequestId(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      });
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  const saveQualityMetadata = async (): Promise<void> => {
    if (!detail || qualityMutation.isPending) {
      return;
    }

    const payload: AdminTrustStatusRequest = {
      trust_status: detail.trust_status ?? "current",
      quality_state: qualityStateDraft,
      quality_notes: qualityNotesDraft.trim() || null,
      quality_owner_id: qualityOwnerDraft.trim() || null,
      quality_reviewer_id: qualityReviewerDraft.trim() || null,
      review_status: detail.review_status ?? null,
      review_owner_id: qualityOwnerDraft.trim() || null,
      review_due_date: qualityDueDateDraft || null,
      expiry_date: qualityExpiryDateDraft || null,
      trust_level: qualityTrustLevelDraft.trim() || null,
      version_label: detail.version_label ?? null,
      review_date: qualityReviewDateDraft || null,
      effective_date: detail.effective_date ?? null,
      stale_after_days: detail.stale_after_days ?? null,
      superseded_by_document_id: detail.superseded_by_document_id ?? null,
    };
    await qualityMutation.mutateAsync(payload);
  };

  return {
    deleteMutation,
    reindexMutation,
    graphReindexMutation,
    downloadMutation,
    langOverrideMutation,
    ocrConfigMutation,
    qualityMutation,
    saveQualityMetadata,
  };
}
