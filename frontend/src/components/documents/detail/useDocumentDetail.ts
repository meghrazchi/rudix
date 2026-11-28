"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import type {
  DocumentDetailResponse,
  DocumentQualityState,
  DocumentStatus,
} from "@/lib/api/documents";
import { getDocument, getDocumentChunks } from "@/lib/api/documents";
import type { ChatCitationResponse } from "@/lib/api/chat";
import { queryKeys } from "@/lib/api/query";
import {
  canDeleteDocument,
  canForceReindexDocument,
  canReindexDocument,
  resolveDocumentCapabilities,
} from "@/lib/documents-ui";
import { useDocumentStatusPolling } from "@/lib/use-document-status-polling";
import { useAuthSession } from "@/lib/use-auth-session";

import {
  CHUNK_PAGE_SIZE,
  type NoChunksMessages,
} from "@/components/documents/detail/detail-format";
import {
  buildErrorRows,
  buildLifecycleTimeline,
  deriveDetailStatus,
  deriveRecommendations,
  extractOcrMetadata,
  isSafeNotFoundError,
  type DetailTab,
  type LifecycleLabels,
  type MetadataCopyField,
  type RecMessages,
} from "@/components/documents/detail/detail-lifecycle";
import { useDocumentDetailMutations } from "@/components/documents/detail/useDocumentDetailMutations";

/** State, queries, mutations, and derived view data of the document detail page. */
export function useDocumentDetail(documentId: string) {
  const td = useTranslations("documents.detail");

  const lifecycleLabels: LifecycleLabels = {
    extract: td("lifecycle.extracted"),
    detect_ocr: td("lifecycle.ocrDetection"),
    ocr: td("lifecycle.ocr"),
    chunk: td("lifecycle.chunked"),
    embed: td("lifecycle.embedded"),
    index: td("lifecycle.upserted"),
    extract_entities: td("lifecycle.graphExtraction"),
    ready_for_chat: td("lifecycle.readyForChat"),
    ready_for_chat_description: td("lifecycle.readyForChatDescription"),
  };

  const noChunkMessages: NoChunksMessages = {
    processing: td("noChunksProcessing"),
    failed: td("noChunksFailed"),
    deleting: td("noChunksDeleting"),
    default: td("noChunksDefault"),
  };

  const recMessages: RecMessages = {
    retryIndexing: td("rec.retryIndexing"),
    openPipeline: td("rec.openPipeline"),
    smallerChunks: td("rec.smallerChunks"),
    noErrors: td("rec.noErrors"),
  };

  const searchParams = useSearchParams();
  const highlightedChunkId = searchParams.get("chunk_id");
  const highlightedSnippet = searchParams.get("snippet");
  const { state } = useAuthSession();
  const capabilities = resolveDocumentCapabilities(state.session?.role);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<{
    field: MetadataCopyField;
    fading: boolean;
  } | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>(
    highlightedChunkId ? "chunks" : "overview",
  );
  const [chunksOffset, setChunksOffset] = useState(0);
  const [includeFullText, setIncludeFullText] = useState(false);
  const [chunkSearchQuery, setChunkSearchQuery] = useState("");
  const [langOverrideValue, setLangOverrideValue] = useState<string>("");
  const [langOverrideOpen, setLangOverrideOpen] = useState(false);
  const [ocrLangOverrideValue, setOcrLangOverrideValue] = useState<string>("");
  const [ocrLangOverrideOpen, setOcrLangOverrideOpen] = useState(false);
  const [qualityStateDraft, setQualityStateDraft] =
    useState<DocumentQualityState>("unreviewed");
  const [qualityNotesDraft, setQualityNotesDraft] = useState("");
  const [qualityOwnerDraft, setQualityOwnerDraft] = useState("");
  const [qualityReviewerDraft, setQualityReviewerDraft] = useState("");
  const [qualityDueDateDraft, setQualityDueDateDraft] = useState("");
  const [qualityExpiryDateDraft, setQualityExpiryDateDraft] = useState("");
  const [qualityReviewDateDraft, setQualityReviewDateDraft] = useState("");
  const [qualityTrustLevelDraft, setQualityTrustLevelDraft] = useState("");
  const [previewCitationSet, setPreviewCitationSet] = useState<{
    citations: ChatCitationResponse[];
    initialIndex: number;
  } | null>(null);
  const copyFadeTimeoutRef = useRef<number | null>(null);
  const copyClearTimeoutRef = useRef<number | null>(null);
  const lastLifecycleSyncAttemptRef = useRef<number | null>(null);
  const highlightedChunkRef = useRef<HTMLElement | null>(null);

  const clearCopyFeedbackTimers = (): void => {
    if (copyFadeTimeoutRef.current !== null) {
      window.clearTimeout(copyFadeTimeoutRef.current);
      copyFadeTimeoutRef.current = null;
    }
    if (copyClearTimeoutRef.current !== null) {
      window.clearTimeout(copyClearTimeoutRef.current);
      copyClearTimeoutRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      clearCopyFeedbackTimers();
    };
  }, []);

  const copyMetadataValue = async (
    value: string | null,
    field: MetadataCopyField,
  ): Promise<void> => {
    if (!value || !value.trim()) {
      return;
    }
    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("clipboard_unavailable");
      }
      await navigator.clipboard.writeText(value);
      clearCopyFeedbackTimers();
      setCopyFeedback({ field, fading: false });
      copyFadeTimeoutRef.current = window.setTimeout(() => {
        setCopyFeedback((previous) =>
          previous?.field === field ? { ...previous, fading: true } : previous,
        );
      }, 900);
      copyClearTimeoutRef.current = window.setTimeout(() => {
        setCopyFeedback((previous) =>
          previous?.field === field ? null : previous,
        );
      }, 1450);
    } catch {
      setActionFeedback(td("feedbackCopyFailed"));
      setActionRequestId(null);
    }
  };

  const detailQuery = useQuery({
    queryKey: queryKeys.documents.detail(documentId),
    queryFn: () => getDocument(documentId),
  });

  const statusQuery = useDocumentStatusPolling(documentId, {
    enabled: detailQuery.isSuccess,
    initialStatus: detailQuery.data?.status ?? null,
    refetchInBackground: true,
  });
  const detailData = detailQuery.data;
  const isDetailFetching = detailQuery.isFetching;
  const refetchDetail = detailQuery.refetch;
  const liveStatus = statusQuery.data;
  const statusSnapshotUpdatedAt = statusQuery.dataUpdatedAt;

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!detailData) {
      return;
    }
    setQualityStateDraft(detailData.quality_state ?? "unreviewed");
    setQualityNotesDraft(detailData.quality_notes ?? "");
    setQualityOwnerDraft(detailData.review_owner_id ?? "");
    setQualityReviewerDraft(detailData.trusted_by_id ?? "");
    setQualityDueDateDraft(detailData.review_due_date ?? "");
    setQualityExpiryDateDraft(detailData.expiry_date ?? "");
    setQualityReviewDateDraft(detailData.review_date ?? "");
    setQualityTrustLevelDraft(detailData.trust_level ?? "");
  }, [detailData]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (!detailData || !liveStatus || statusSnapshotUpdatedAt <= 0) {
      return;
    }

    const isOutOfSync =
      detailData.status !== liveStatus.status ||
      (detailData.updated_at ?? null) !== (liveStatus.updated_at ?? null);
    if (!isOutOfSync) {
      lastLifecycleSyncAttemptRef.current = statusSnapshotUpdatedAt;
      return;
    }

    if (
      isDetailFetching ||
      lastLifecycleSyncAttemptRef.current === statusSnapshotUpdatedAt
    ) {
      return;
    }

    lastLifecycleSyncAttemptRef.current = statusSnapshotUpdatedAt;
    void refetchDetail();
  }, [
    detailData,
    isDetailFetching,
    liveStatus,
    refetchDetail,
    statusSnapshotUpdatedAt,
  ]);

  const effectiveChunksLimit = highlightedChunkId ? 100 : CHUNK_PAGE_SIZE;
  const effectiveChunksOffset = highlightedChunkId ? 0 : chunksOffset;
  const effectiveIncludeFullText = highlightedChunkId ? true : includeFullText;

  const chunksQuery = useQuery({
    queryKey: queryKeys.documents.chunks(documentId, {
      limit: effectiveChunksLimit,
      offset: effectiveChunksOffset,
      include_full_text: effectiveIncludeFullText,
    }),
    queryFn: () =>
      getDocumentChunks(documentId, {
        limit: effectiveChunksLimit,
        offset: effectiveChunksOffset,
        include_full_text: effectiveIncludeFullText,
      }),
    enabled: detailQuery.isSuccess,
  });

  useEffect(() => {
    if (!highlightedChunkId || !highlightedChunkRef.current) return;
    highlightedChunkRef.current.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [highlightedChunkId, chunksQuery.data]);

  const {
    deleteMutation,
    reindexMutation,
    graphReindexMutation,
    downloadMutation,
    langOverrideMutation,
    ocrConfigMutation,
    qualityMutation,
    saveQualityMetadata,
  } = useDocumentDetailMutations({
    documentId,
    td,
    detail: detailQuery.data,
    detailQuery,
    statusQuery,
    setActionFeedback,
    setActionRequestId,
    setLangOverrideOpen,
    setOcrLangOverrideOpen,
    qualityDrafts: {
      qualityStateDraft,
      qualityNotesDraft,
      qualityOwnerDraft,
      qualityReviewerDraft,
      qualityDueDateDraft,
      qualityExpiryDateDraft,
      qualityReviewDateDraft,
      qualityTrustLevelDraft,
    },
  });

  const safeBackHrefRaw = searchParams.get("back");
  const safeBackHref =
    safeBackHrefRaw &&
    (safeBackHrefRaw.startsWith("/documents") ||
      safeBackHrefRaw.startsWith("/chat"))
      ? safeBackHrefRaw
      : "/documents";

  const detail = detailQuery.data;
  const currentStatus = detail
    ? deriveDetailStatus(detail, statusQuery.data)
    : null;
  const graphStatus = detail?.graph_extraction_status ?? null;
  const chunkStatus = currentStatus ?? detail?.status ?? null;
  const selectedChunks = chunksQuery.data;
  const highlightedChunk =
    selectedChunks?.items.find(
      (chunk) => chunk.chunk_id === highlightedChunkId,
    ) ?? null;
  const lifecycle = useMemo(
    () =>
      detail && currentStatus
        ? buildLifecycleTimeline(detail, lifecycleLabels)
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentStatus, detail],
  );
  const errorRows = useMemo(
    () =>
      detail ? buildErrorRows(detail, lifecycle, td("documentProcessing")) : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detail, lifecycle],
  );
  const ocrMetadata = useMemo(() => extractOcrMetadata(lifecycle), [lifecycle]);
  const errorSummary = useMemo(
    () => ({
      critical: errorRows.filter((row) => row.severity === "critical").length,
      warnings: errorRows.filter((row) => row.severity === "warning").length,
    }),
    [errorRows],
  );
  const recommendations = useMemo(
    () => (detail ? deriveRecommendations(detail, lifecycle, recMessages) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detail, lifecycle],
  );
  const deferredChunkSearchQuery = useDeferredValue(chunkSearchQuery.trim());
  const filteredChunks = useMemo(() => {
    const items = selectedChunks?.items ?? [];
    if (!deferredChunkSearchQuery) {
      return items;
    }
    const normalizedQuery = deferredChunkSearchQuery.toLowerCase();
    return items.filter((chunk) => {
      const haystack = [
        chunk.text_preview,
        chunk.text,
        chunk.section_path,
        chunk.language,
        chunk.page_number != null ? `page ${chunk.page_number}` : null,
        `chunk ${chunk.chunk_index}`,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [deferredChunkSearchQuery, selectedChunks?.items]);
  const chunkingIssueCount = useMemo(
    () =>
      errorRows.filter((row) =>
        /chunk|ocr|index/i.test(`${row.type} ${row.message}`),
      ).length,
    [errorRows],
  );

  const notFoundOrInaccessible = isSafeNotFoundError(detailQuery.error);
  const canDelete = Boolean(
    currentStatus && capabilities.canDelete && canDeleteDocument(currentStatus),
  );
  const canReindex = Boolean(
    currentStatus &&
    capabilities.canReindex &&
    canReindexDocument(currentStatus),
  );
  const canForceReindex = Boolean(
    currentStatus &&
    capabilities.canReindex &&
    canForceReindexDocument(currentStatus),
  );
  const canAskInChat = currentStatus === "indexed";
  const canShowMoreActions = capabilities.canDelete || capabilities.canReindex;
  const canDownloadOriginal =
    currentStatus !== "deleted" && currentStatus !== "deleting";
  const canGoPrevChunks = chunksOffset > 0;
  const canGoNextChunks = Boolean(
    selectedChunks && chunksOffset + CHUNK_PAGE_SIZE < selectedChunks.total,
  );

  return {
    documentId,
    td,
    noChunkMessages,
    highlightedChunkId,
    highlightedSnippet,
    capabilities,
    actionFeedback,
    setActionFeedback,
    actionRequestId,
    setActionRequestId,
    copyFeedback,
    activeTab,
    setActiveTab,
    chunksOffset,
    setChunksOffset,
    includeFullText,
    setIncludeFullText,
    chunkSearchQuery,
    setChunkSearchQuery,
    langOverrideValue,
    setLangOverrideValue,
    langOverrideOpen,
    setLangOverrideOpen,
    ocrLangOverrideValue,
    setOcrLangOverrideValue,
    ocrLangOverrideOpen,
    setOcrLangOverrideOpen,
    qualityStateDraft,
    setQualityStateDraft,
    qualityNotesDraft,
    setQualityNotesDraft,
    qualityOwnerDraft,
    setQualityOwnerDraft,
    qualityReviewerDraft,
    setQualityReviewerDraft,
    qualityDueDateDraft,
    setQualityDueDateDraft,
    qualityExpiryDateDraft,
    setQualityExpiryDateDraft,
    qualityReviewDateDraft,
    setQualityReviewDateDraft,
    qualityTrustLevelDraft,
    setQualityTrustLevelDraft,
    previewCitationSet,
    setPreviewCitationSet,
    highlightedChunkRef,
    copyMetadataValue,
    detailQuery,
    statusQuery,
    chunksQuery,
    deleteMutation,
    reindexMutation,
    graphReindexMutation,
    downloadMutation,
    langOverrideMutation,
    ocrConfigMutation,
    qualityMutation,
    saveQualityMetadata,
    safeBackHref,
    detail,
    currentStatus,
    graphStatus,
    chunkStatus,
    selectedChunks,
    highlightedChunk,
    lifecycle,
    errorRows,
    ocrMetadata,
    errorSummary,
    recommendations,
    filteredChunks,
    chunkingIssueCount,
    notFoundOrInaccessible,
    canDelete,
    canReindex,
    canForceReindex,
    canAskInChat,
    canShowMoreActions,
    canDownloadOriginal,
    canGoPrevChunks,
    canGoNextChunks,
  };
}

export type DocumentDetailController = ReturnType<typeof useDocumentDetail>;

export type DetailSectionProps = {
  ctl: DocumentDetailController;
  detail: DocumentDetailResponse;
  currentStatus: DocumentStatus;
};
