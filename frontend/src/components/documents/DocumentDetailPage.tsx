"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { DocumentChunkingDiagnosticsPanel } from "@/components/documents/DocumentChunkingDiagnosticsPanel";
import { DocumentExtractionDiagnosticsPanel } from "@/components/documents/DocumentExtractionDiagnosticsPanel";
import { DocumentGraphInsightsPanel } from "@/components/documents/DocumentGraphInsightsPanel";
import { DocumentVersionHistoryPanel } from "@/components/documents/DocumentVersionHistoryPanel";
import { DocumentMetadataPanel } from "@/components/documents/DocumentMetadataPanel";
import { CitationPreviewDrawer } from "@/components/chat/DocumentPreviewModal";
import type {
  DocumentDetailResponse,
  DocumentLifecycleTimelineStepResponse,
  ReindexDocumentRequest,
  DocumentStatus,
  DocumentStatusResponse,
  AdminLanguageOverrideRequest,
  AdminOcrConfigRequest,
  AdminTrustStatusRequest,
  DocumentQualityState,
} from "@/lib/api/documents";
import {
  configureDocumentOcr,
  deleteDocument,
  downloadDocumentFile,
  getDocument,
  getDocumentChunks,
  overrideDocumentLanguage,
  reindexDocumentGraph,
  reindexDocument,
  updateDocumentTrustStatus,
  OCR_LANGUAGES,
  UPLOAD_LANGUAGES,
} from "@/lib/api/documents";
import type { ChatCitationResponse } from "@/lib/api/chat";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  canDeleteDocument,
  canForceReindexDocument,
  canReindexDocument,
  getDocumentLifecycleActionErrorMessage,
  resolveDocumentCapabilities,
} from "@/lib/documents-ui";
import { extractRequestIdFromError } from "@/lib/forbidden";
import { buildPipelineExplorerHref } from "@/lib/pipeline-links";
import { useDocumentStatusPolling } from "@/lib/use-document-status-polling";
import { useAuthSession } from "@/lib/use-auth-session";
import { useTranslations } from "next-intl";

type DocumentDetailPageProps = {
  documentId: string;
};

type TimelineStepState = "completed" | "active" | "pending" | "failed";

type TimelineStep = {
  key: string;
  label: string;
  description: string;
  state: TimelineStepState;
  timestamp: string | null;
  documentId: string | null;
  logs: string[];
  pipelineRunId: string | null;
  pipelineType: string | null;
  durationMs: number | null;
  status: DocumentLifecycleTimelineStepResponse["status"] | null;
  outputs: Record<string, unknown> | null;
};

type DetailTab = "overview" | "chunks" | "errors" | "versions" | "metadata";
type MetadataCopyField = "document-id" | "checksum";

type ErrorRow = {
  key: string;
  type: string;
  severity: "critical" | "warning";
  message: string;
  timestamp: string | null;
  code: string | null;
};

type ReindexMutationInput = {
  payload?: ReindexDocumentRequest;
  label?: string;
  force?: boolean;
};

const CHUNK_PAGE_SIZE = 8;
const CHUNK_PREVIEW_MAX_CHARS = 420;

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function truncateChunkPreview(value: string): string {
  if (value.length <= CHUNK_PREVIEW_MAX_CHARS) {
    return value;
  }
  return `${value.slice(0, CHUNK_PREVIEW_MAX_CHARS).trimEnd()}…`;
}

type NoChunksMessages = {
  processing: string;
  failed: string;
  deleting: string;
  default: string;
};

function noChunksMessage(
  status: DocumentStatus,
  messages: NoChunksMessages,
): string {
  if (status === "processing" || status === "uploaded") {
    return messages.processing;
  }
  if (status === "failed") {
    return messages.failed;
  }
  if (status === "deleting" || status === "deleted") {
    return messages.deleting;
  }
  return messages.default;
}

function documentTypeIcon(fileType: string): string {
  if (fileType === "pdf") {
    return "picture_as_pdf";
  }
  if (fileType === "docx") {
    return "description";
  }
  return "notes";
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function statusBadge(status: DocumentStatus): string {
  if (status === "indexed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "processing") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "uploaded") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "deleted") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function freshnessBadge(status: string | null | undefined): string {
  if (status === "trusted") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "current") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "needs_review") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function qualityBadge(status: string | null | undefined): string {
  if (status === "verified") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "reviewed") {
    return "rounded-full bg-sky-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-sky-800";
  }
  if (status === "unreviewed") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "draft") {
    return "rounded-full bg-violet-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-violet-800";
  }
  if (status === "stale") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "expired") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deprecated") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "archived") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function graphStatusBadge(status: string): string {
  if (status === "completed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "pending" || status === "extracting") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function timelineStepClass(state: TimelineStepState): string {
  if (state === "completed") {
    return "border-[#3525cd] bg-[#3525cd] text-white";
  }
  if (state === "active") {
    return "border-[#4f46e5] bg-[#4f46e5] text-white";
  }
  if (state === "failed") {
    return "border-rose-300 bg-rose-100 text-rose-700";
  }
  return "border-[#d4d1df] bg-white text-[#777587]";
}

function timelineStepGlyph(state: TimelineStepState): string {
  if (state === "failed") {
    return "!";
  }
  if (state === "pending") {
    return "·";
  }
  return "✓";
}

function buildLifecycleTimeline(
  detail: DocumentDetailResponse,
  labels: LifecycleLabels,
): TimelineStep[] {
  const backendTimeline = Array.isArray(detail.lifecycle_timeline)
    ? detail.lifecycle_timeline.map((step) =>
        fromBackendLifecycleTimelineStep(step, labels),
      )
    : [];
  const steps = backendTimeline.filter((step) => step.state !== "pending");

  const hasGraphStep = steps.some((s) => s.key === "extract_entities");
  const graphExtractionStatus = detail.graph_extraction_status;
  if (
    !hasGraphStep &&
    graphExtractionStatus &&
    graphExtractionStatus !== "skipped"
  ) {
    let state: TimelineStepState = "pending";
    if (graphExtractionStatus === "completed") state = "completed";
    else if (graphExtractionStatus === "failed") state = "failed";
    else if (graphExtractionStatus === "extracting") state = "active";
    if (state !== "pending") {
      steps.push({
        key: "extract_entities",
        label: labels.extract_entities,
        description: "",
        state,
        timestamp: null,
        documentId: detail.document_id,
        logs: [],
        pipelineRunId: null,
        pipelineType: null,
        durationMs: null,
        status:
          graphExtractionStatus === "extracting"
            ? "running"
            : graphExtractionStatus,
        outputs: null,
      });
    }
  }

  const hasReadyForChatStep = steps.some((s) => s.key === "ready_for_chat");
  if (detail.status === "indexed" && !hasReadyForChatStep) {
    steps.push({
      key: "ready_for_chat",
      label: labels.ready_for_chat,
      description: "Document is available for retrieval-backed chat queries.",
      state: "completed",
      timestamp: detail.updated_at ?? null,
      documentId: detail.document_id,
      logs: [],
      pipelineRunId: null,
      pipelineType: null,
      durationMs: null,
      status: "completed",
      outputs: null,
    });
  }

  return steps;
}

function fromBackendLifecycleTimelineStep(
  step: DocumentLifecycleTimelineStepResponse,
  labels: LifecycleLabels,
): TimelineStep {
  let state: TimelineStepState = "pending";
  if (step.status === "completed" || step.status === "skipped") {
    state = "completed";
  } else if (step.status === "running") {
    state = "active";
  } else if (step.status === "failed") {
    state = "failed";
  }

  return {
    key: step.step,
    label: normalizeLifecycleLabel(step.step, step.label, labels),
    description: step.description,
    state,
    timestamp: step.completed_at ?? step.started_at ?? null,
    documentId: step.document_id,
    logs: Array.isArray(step.logs) ? step.logs : [],
    pipelineRunId: step.pipeline_run_id ?? null,
    pipelineType: step.pipeline_type ?? null,
    durationMs: step.duration_ms ?? null,
    status: step.status,
    outputs: step.outputs ?? null,
  };
}

type LifecycleLabels = {
  extract: string;
  detect_ocr: string;
  ocr: string;
  chunk: string;
  embed: string;
  index: string;
  extract_entities: string;
  ready_for_chat: string;
};

function normalizeLifecycleLabel(
  stepKey: string,
  label: string,
  labels: LifecycleLabels,
): string {
  if (stepKey === "extract") return labels.extract;
  if (stepKey === "detect_ocr") return labels.detect_ocr;
  if (stepKey === "ocr") return labels.ocr;
  if (stepKey === "chunk") return labels.chunk;
  if (stepKey === "embed") return labels.embed;
  if (stepKey === "index") return labels.index;
  if (stepKey === "extract_entities") return labels.extract_entities;
  if (stepKey === "ready_for_chat") return labels.ready_for_chat;
  return label;
}

type OcrMetadata = {
  required: boolean;
  mode: string;
  status: string;
  languages: string[];
  pagesProcessed: number;
  pagesCompleted: number;
  pagesFailed: number;
  nativeTextPages: number;
  durationMs: number | null;
  warnings: string[];
};

function extractOcrMetadata(timeline: TimelineStep[]): OcrMetadata | null {
  const detectStep = timeline.find((s) => s.key === "detect_ocr");
  const ocrStep = timeline.find((s) => s.key === "ocr");

  if (!detectStep) return null;

  const detectOut = detectStep.outputs;
  const ocrOut = ocrStep?.outputs ?? null;

  const required = Boolean(detectOut?.requires_ocr ?? false);
  if (!required) {
    return {
      required: false,
      mode: String(detectOut?.mode ?? "text"),
      status: "not_required",
      languages: [],
      pagesProcessed: 0,
      pagesCompleted: 0,
      pagesFailed: 0,
      nativeTextPages: Number(detectOut?.native_text_pages ?? 0),
      durationMs: null,
      warnings: [],
    };
  }

  return {
    required,
    mode: String(ocrOut?.mode ?? detectOut?.mode ?? "unknown"),
    status: String(ocrOut?.status ?? "unknown"),
    languages: Array.isArray(ocrOut?.languages)
      ? (ocrOut.languages as string[])
      : [],
    pagesProcessed: Number(ocrOut?.pages_processed ?? 0),
    pagesCompleted: Number(ocrOut?.pages_completed ?? 0),
    pagesFailed: Number(ocrOut?.pages_failed ?? 0),
    nativeTextPages: Number(detectOut?.native_text_pages ?? 0),
    durationMs: ocrOut?.duration_ms != null ? Number(ocrOut.duration_ms) : null,
    warnings: Array.isArray(ocrOut?.warnings)
      ? (ocrOut.warnings as string[])
      : [],
  };
}

function deriveDetailStatus(
  detail: DocumentDetailResponse,
  liveStatus: DocumentStatusResponse | undefined,
): DocumentStatus {
  return liveStatus?.status ?? detail.status;
}

function isSafeNotFoundError(error: unknown): boolean {
  if (!isApiClientError(error)) {
    return false;
  }
  return error.status === 403 || error.status === 404;
}

function buildErrorRows(
  detail: DocumentDetailResponse,
  timeline: TimelineStep[],
  docProcessingLabel: string,
): ErrorRow[] {
  const rows: ErrorRow[] = [];

  if (detail.error_message) {
    rows.push({
      key: "document-error",
      type: detail.error_details?.stage ?? docProcessingLabel,
      severity: "critical",
      message: detail.error_details?.message ?? detail.error_message,
      timestamp: detail.updated_at,
      code: detail.error_details?.code ?? null,
    });
  }

  timeline.forEach((step) => {
    step.logs.forEach((line, index) => {
      const normalizedLine = line.trim();
      if (!normalizedLine) {
        return;
      }
      const isCritical =
        step.state === "failed" || /error|failed|fatal/i.test(normalizedLine);
      rows.push({
        key: `${step.key}-${index}`,
        type: step.label,
        severity: isCritical ? "critical" : "warning",
        message: normalizedLine,
        timestamp: step.timestamp,
        code: null,
      });
    });
  });

  return rows;
}

function severityBadgeClass(value: ErrorRow["severity"]): string {
  if (value === "critical") {
    return "bg-rose-100 text-rose-700";
  }
  return "bg-amber-100 text-amber-700";
}

type RecMessages = {
  retryIndexing: string;
  openPipeline: string;
  smallerChunks: string;
  noErrors: string;
};

function deriveRecommendations(
  detail: DocumentDetailResponse,
  timeline: TimelineStep[],
  rec: RecMessages,
): string[] {
  const recommendations: string[] = [];

  if (detail.error_details?.retryable) {
    recommendations.push(rec.retryIndexing);
  }
  if (
    timeline.some(
      (step) =>
        step.state === "failed" ||
        step.logs.some((line) => /error|failed|timeout/i.test(line)),
    )
  ) {
    recommendations.push(rec.openPipeline);
  }
  if (detail.page_count && detail.page_count > 100) {
    recommendations.push(rec.smallerChunks);
  }
  if (recommendations.length === 0) {
    recommendations.push(rec.noErrors);
  }

  return recommendations;
}

export function DocumentDetailPage({ documentId }: DocumentDetailPageProps) {
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

  const queryClient = useQueryClient();
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
        `Graph re-index queued. Queue status: ${result.queue_status}.`,
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
      setActionFeedback("Quality metadata saved.");
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

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {td("eyebrow")}
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {td("title")}
        </h1>
        <p className="text-sm text-[#68647b]">{td("description")}</p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        {detailQuery.isLoading ? (
          <LoadingState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]"
            title={td("loading")}
          />
        ) : null}

        {notFoundOrInaccessible ? (
          <EmptyState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-6 text-center"
            title={td("notFoundTitle")}
            description={td("notFoundDesc")}
          />
        ) : null}

        {!detailQuery.isLoading &&
        detailQuery.isError &&
        !notFoundOrInaccessible ? (
          <ErrorState
            error={detailQuery.error}
            description={getApiErrorMessage(detailQuery.error)}
            onRetry={() => {
              void detailQuery.refetch();
              void statusQuery.refetch();
            }}
          />
        ) : null}

        {detail && currentStatus && !notFoundOrInaccessible ? (
          <div className="space-y-5">
            {actionFeedback ? (
              <p
                role="status"
                className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
              >
                {actionFeedback}
                {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
              </p>
            ) : null}

            <section className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-bold text-[#2a2640]">
                      {detail.filename}
                    </h2>
                    <span className={statusBadge(currentStatus)}>
                      {currentStatus}
                    </span>
                    {graphStatus ? (
                      <span className={graphStatusBadge(graphStatus)}>
                        graph {graphStatus}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
                    <span className="break-all">
                      {td("documentIdLabel")} {detail.document_id}
                    </span>
                    <button
                      type="button"
                      aria-label="Copy document id"
                      onClick={() => {
                        void copyMetadataValue(
                          detail.document_id,
                          "document-id",
                        );
                      }}
                      className="inline-flex h-3 w-3 cursor-pointer items-center justify-center text-[#5b5484] hover:text-[#2f2a52]"
                    >
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[9px] leading-none"
                      >
                        content_copy
                      </span>
                    </button>
                    {copyFeedback?.field === "document-id" ? (
                      <span
                        className={`text-[10px] text-[#6b6594] transition-opacity duration-300 ${
                          copyFeedback.fading ? "opacity-0" : "opacity-100"
                        }`}
                      >
                        {td("copied")}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
                    <span className="break-all">
                      {td("checksumLabel")} {detail.checksum ?? "-"}
                    </span>
                    <button
                      type="button"
                      aria-label="Copy checksum"
                      disabled={!detail.checksum}
                      onClick={() => {
                        void copyMetadataValue(
                          detail.checksum ?? null,
                          "checksum",
                        );
                      }}
                      className="inline-flex h-3 w-3 cursor-pointer items-center justify-center text-[#5b5484] hover:text-[#2f2a52] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[9px] leading-none"
                      >
                        content_copy
                      </span>
                    </button>
                    {copyFeedback?.field === "checksum" ? (
                      <span
                        className={`text-[10px] text-[#6b6594] transition-opacity duration-300 ${
                          copyFeedback.fading ? "opacity-0" : "opacity-100"
                        }`}
                      >
                        {td("copied")}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Link
                    href={safeBackHref}
                    className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[16px]"
                    >
                      arrow_back
                    </span>
                    {td("back")}
                  </Link>
                  {canAskInChat ? (
                    <Link
                      href={`/chat?document_id=${encodeURIComponent(documentId)}`}
                      className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                    >
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[16px]"
                      >
                        forum
                      </span>
                      {td("askInChat")}
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[16px]"
                      >
                        forum
                      </span>
                      {td("askInChat")}
                    </span>
                  )}
                  <Link
                    href={buildPipelineExplorerHref({
                      runType: "document.process",
                      documentId,
                    })}
                    className="inline-flex items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                  >
                    <span
                      aria-hidden="true"
                      className="material-symbols-outlined text-[16px]"
                    >
                      account_tree
                    </span>
                    {td("viewPipeline")}
                  </Link>
                  {canShowMoreActions ? (
                    <details className="relative">
                      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] [&::-webkit-details-marker]:hidden">
                        <span
                          aria-hidden="true"
                          className="material-symbols-outlined text-[16px]"
                        >
                          more_horiz
                        </span>
                        {td("moreActions")}
                      </summary>
                      <div className="absolute right-0 z-20 mt-1 flex min-w-[10.5rem] flex-col gap-1 rounded-lg border border-[#d8d3ea] bg-white p-1 shadow-lg">
                        {capabilities.canReindex ? (
                          <>
                            {canForceReindex ? (
                              <button
                                type="button"
                                disabled={reindexMutation.isPending}
                                onClick={(event) => {
                                  (
                                    event.currentTarget.closest(
                                      "details",
                                    ) as HTMLDetailsElement | null
                                  )?.removeAttribute("open");
                                  setActionFeedback(null);
                                  setActionRequestId(null);
                                  reindexMutation.mutate({ force: true });
                                }}
                                className="inline-flex w-full items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-left text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                <span
                                  aria-hidden="true"
                                  className="material-symbols-outlined text-[15px]"
                                >
                                  restart_alt
                                </span>
                                {reindexMutation.isPending
                                  ? td("reindexQueueing")
                                  : td("forceReindex")}
                              </button>
                            ) : null}
                            <button
                              type="button"
                              disabled={
                                !canReindex || reindexMutation.isPending
                              }
                              onClick={(event) => {
                                (
                                  event.currentTarget.closest(
                                    "details",
                                  ) as HTMLDetailsElement | null
                                )?.removeAttribute("open");
                                setActionFeedback(null);
                                setActionRequestId(null);
                                reindexMutation.mutate({
                                  label: td("reindexDefaultProfile"),
                                });
                              }}
                              className="inline-flex w-full items-center gap-2 rounded-md border border-[#cbc5e6] bg-white px-2.5 py-2 text-left text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span
                                aria-hidden="true"
                                className="material-symbols-outlined text-[15px]"
                              >
                                refresh
                              </span>
                              {reindexMutation.isPending
                                ? td("reindexQueueing")
                                : td("reindex")}
                            </button>
                            <button
                              type="button"
                              disabled={
                                !canReindex || graphReindexMutation.isPending
                              }
                              onClick={(event) => {
                                (
                                  event.currentTarget.closest(
                                    "details",
                                  ) as HTMLDetailsElement | null
                                )?.removeAttribute("open");
                                setActionFeedback(null);
                                setActionRequestId(null);
                                graphReindexMutation.mutate();
                              }}
                              className="inline-flex w-full items-center gap-2 rounded-md border border-[#cbc5e6] bg-white px-2.5 py-2 text-left text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span
                                aria-hidden="true"
                                className="material-symbols-outlined text-[15px]"
                              >
                                schema
                              </span>
                              {graphReindexMutation.isPending
                                ? td("reindexQueueing")
                                : "Graph re-index"}
                            </button>
                          </>
                        ) : null}
                        {capabilities.canDelete ? (
                          <button
                            type="button"
                            disabled={!canDelete || deleteMutation.isPending}
                            onClick={(event) => {
                              const confirmed = window.confirm(
                                td("deleteConfirm", {
                                  filename: detail.filename,
                                }),
                              );
                              if (!confirmed) {
                                return;
                              }
                              (
                                event.currentTarget.closest(
                                  "details",
                                ) as HTMLDetailsElement | null
                              )?.removeAttribute("open");
                              setActionFeedback(null);
                              setActionRequestId(null);
                              deleteMutation.mutate();
                            }}
                            className="inline-flex w-full items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-left text-xs font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <span
                              aria-hidden="true"
                              className="material-symbols-outlined text-[15px]"
                            >
                              delete
                            </span>
                            {deleteMutation.isPending
                              ? td("deleting")
                              : td("delete")}
                          </button>
                        ) : null}
                      </div>
                    </details>
                  ) : null}
                </div>
              </div>
            </section>

            {/* Citation evidence callout — shown when arriving from a chat citation deep-link */}
            {highlightedChunkId ? (
              <div className="rounded-xl border border-[#3525cd]/30 bg-[#f5f2ff] p-4">
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className="material-symbols-outlined text-[18px] text-[#3525cd]"
                    aria-hidden="true"
                  >
                    format_quote
                  </span>
                  <p className="text-xs font-bold tracking-wide text-[#3525cd] uppercase">
                    {td("citationEvidence")}
                  </p>
                </div>
                {highlightedSnippet ? (
                  <p className="rounded-r border-l-4 border-[#3525cd] bg-white py-2 pr-2 pl-3 text-sm text-[#1b1b24] italic">
                    {highlightedSnippet}
                  </p>
                ) : null}
                <p
                  className="mt-2 font-mono text-[10px] text-[#6a6780]"
                  title={`Chunk ID: ${highlightedChunkId}`}
                >
                  Chunk: {highlightedChunkId.slice(0, 16)}&hellip;
                </p>
                <button
                  type="button"
                  onClick={() => {
                    if (!detail || !highlightedChunkId) return;
                    setPreviewCitationSet({
                      citations: [
                        {
                          document_id: detail.document_id,
                          chunk_id: highlightedChunkId,
                          filename: detail.filename,
                          page_number: highlightedChunk?.page_number ?? null,
                          text_snippet: highlightedSnippet ?? null,
                          score: null,
                          similarity_score: null,
                          rerank_score: null,
                        },
                      ],
                      initialIndex: 0,
                    });
                  }}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-[#d2cee6] bg-white px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                >
                  <span
                    className="material-symbols-outlined text-[15px]"
                    aria-hidden="true"
                  >
                    visibility
                  </span>
                  Preview citation
                </button>
                {activeTab !== "chunks" ? (
                  <button
                    type="button"
                    onClick={() => setActiveTab("chunks")}
                    className="mt-2 text-xs font-semibold text-[#3525cd] hover:underline"
                  >
                    {td("viewInChunks")}
                  </button>
                ) : null}
              </div>
            ) : null}

            <div className="grid items-start gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-8">
                {detail.review_status &&
                ["stale", "expired", "needs_review", "archived"].includes(
                  detail.review_status,
                ) ? (
                  <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    This document is marked{" "}
                    {detail.review_status.replaceAll("_", " ")}. Freshness
                    metadata is used to warn readers and can exclude the
                    document from retrieval.
                  </p>
                ) : null}
                {detail.quality_state &&
                ["draft", "unreviewed", "stale", "expired", "deprecated", "archived"].includes(
                  detail.quality_state,
                ) ? (
                  <p className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800">
                    This document is marked{" "}
                    {detail.quality_state.replaceAll("_", " ")}. Quality state
                    influences retrieval ranking, warning banners, and bulk
                    review workflows.
                  </p>
                ) : null}
                {capabilities.canEditQuality ? (
                  <div className="rounded-lg border border-violet-200 bg-white p-4 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                          Quality workflow
                        </h4>
                        <p className="mt-1 text-sm text-[#605d73]">
                          Update the state that drives retrieval preference and
                          source warnings.
                        </p>
                      </div>
                      <button
                        type="button"
                        disabled={qualityMutation.isPending}
                        onClick={() => {
                          void saveQualityMetadata();
                        }}
                        className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {qualityMutation.isPending ? "Saving..." : "Save quality"}
                      </button>
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Quality state
                        <select
                          value={qualityStateDraft}
                          onChange={(event) =>
                            setQualityStateDraft(
                              event.target.value as DocumentQualityState,
                            )
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        >
                          {[
                            "draft",
                            "verified",
                            "reviewed",
                            "unreviewed",
                            "stale",
                            "expired",
                            "deprecated",
                            "archived",
                          ].map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Quality owner id
                        <input
                          type="text"
                          value={qualityOwnerDraft}
                          onChange={(event) =>
                            setQualityOwnerDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Reviewer id
                        <input
                          type="text"
                          value={qualityReviewerDraft}
                          onChange={(event) =>
                            setQualityReviewerDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Review due
                        <input
                          type="date"
                          value={qualityDueDateDraft}
                          onChange={(event) =>
                            setQualityDueDateDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Review date
                        <input
                          type="date"
                          value={qualityReviewDateDraft}
                          onChange={(event) =>
                            setQualityReviewDateDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Expiry date
                        <input
                          type="date"
                          value={qualityExpiryDateDraft}
                          onChange={(event) =>
                            setQualityExpiryDateDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                        Trust level
                        <input
                          type="text"
                          value={qualityTrustLevelDraft}
                          onChange={(event) =>
                            setQualityTrustLevelDraft(event.target.value)
                          }
                          className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                        />
                      </label>
                    </div>
                    <label className="mt-3 grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                      Quality notes
                      <textarea
                        value={qualityNotesDraft}
                        onChange={(event) =>
                          setQualityNotesDraft(event.target.value)
                        }
                        rows={4}
                        className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
                      />
                    </label>
                  </div>
                ) : null}

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <MetricCard
                    label={td("pageCount")}
                    value={detail.page_count ?? "-"}
                  />
                  <MetricCard
                    label={td("chunkCount")}
                    value={detail.chunk_count}
                  />
                  <MetricCard
                    label={td("fileType")}
                    value={detail.file_type.toUpperCase()}
                  />
                  <MetricCard
                    label={td("updatedMetric")}
                    value={formatDate(detail.updated_at)}
                  />
                  <MetricCard
                    label="Quality"
                    value={detail.quality_state ?? "unreviewed"}
                    valueClass={qualityBadge(detail.quality_state)}
                    plain={false}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <MetricCard
                    label="Quality owner"
                    value={detail.review_owner_id ?? "-"}
                    mono
                  />
                  <MetricCard
                    label="Reviewer"
                    value={detail.trusted_by_id ?? "-"}
                    mono
                  />
                  <MetricCard
                    label="Review due"
                    value={formatDate(detail.review_due_date)}
                  />
                  <MetricCard
                    label="Expiry date"
                    value={formatDate(detail.expiry_date)}
                  />
                  <MetricCard
                    label="Trust level"
                    value={detail.trust_level ?? "-"}
                  />
                </div>
                {detail.quality_notes ? (
                  <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-900">
                    <p className="font-semibold">Quality notes</p>
                    <p className="mt-1 whitespace-pre-wrap">{detail.quality_notes}</p>
                  </div>
                ) : null}

                <section className="rounded-xl border border-[#e4e1f2] bg-white shadow-sm">
                  <div className="flex flex-wrap items-center border-b border-[#e9e6f5] px-4">
                    {(
                      [
                        "overview",
                        "chunks",
                        "errors",
                        "versions",
                        "metadata",
                      ] as const
                    ).map((tabKey) => (
                      <button
                        key={tabKey}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tabKey}
                        onClick={() => setActiveTab(tabKey)}
                        className={`px-4 py-3 text-sm font-semibold capitalize transition-colors ${
                          activeTab === tabKey
                            ? "border-b-2 border-[#3525cd] text-[#3525cd]"
                            : "text-[#69637f] hover:text-[#2a2640]"
                        }`}
                      >
                        {tabKey === "overview"
                          ? td("tabOverview")
                          : tabKey === "chunks"
                            ? td("tabChunks")
                            : tabKey === "versions"
                              ? "Versions"
                              : tabKey === "metadata"
                                ? "Metadata"
                                : td("tabErrors")}
                        {tabKey === "errors" ? (
                          <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                            {errorRows.length}
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>

                  <div className="space-y-4 p-4">
                    {activeTab === "overview" ? (
                      <div className="space-y-4">
                        {detail.error_message ? (
                          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-800">
                            <p className="font-semibold">
                              {td("processingError")}
                            </p>
                            <p className="mt-1">{detail.error_message}</p>
                            {detail.error_details ? (
                              <ul className="mt-2 space-y-1 text-xs">
                                <li>
                                  <span className="font-semibold">
                                    {td("errorStage")}
                                  </span>{" "}
                                  {detail.error_details.stage}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    {td("errorCode")}
                                  </span>{" "}
                                  {detail.error_details.code}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    {td("errorCategory")}
                                  </span>{" "}
                                  {detail.error_details.category}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    {td("errorRetryable")}
                                  </span>{" "}
                                  {detail.error_details.retryable
                                    ? td("errorYes")
                                    : td("errorNo")}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    {td("errorMessage")}
                                  </span>{" "}
                                  {detail.error_details.message}
                                </li>
                              </ul>
                            ) : null}
                          </div>
                        ) : null}

                        <div className="grid gap-3 md:grid-cols-2">
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("fileSummary")}
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("filenameLabel")}
                                </span>
                                <span className="font-semibold">
                                  {detail.filename}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("fileTypeLabel")}
                                </span>
                                <span className="font-semibold">
                                  {detail.file_type.toUpperCase()}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("createdLabel")}
                                </span>
                                <span className="font-semibold">
                                  {formatDate(detail.created_at)}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("updatedLabel")}
                                </span>
                                <span className="font-semibold">
                                  {formatDate(detail.updated_at)}
                                </span>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("indexingIntelligence")}
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("statusLabel")}
                                </span>
                                <span className={statusBadge(currentStatus)}>
                                  {currentStatus}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("embeddingModel")}
                                </span>
                                <span className="font-semibold">
                                  {selectedChunks?.items[0]?.embedding_model ??
                                    "-"}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("indexVersion")}
                                </span>
                                <span className="font-semibold">
                                  {selectedChunks?.items[0]?.index_version ??
                                    "-"}
                                </span>
                              </div>
                              {detail.embedding_provider_type && (
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-[#69637f]">
                                    {td("embeddingProvider")}
                                  </span>
                                  <span className="font-semibold">
                                    {detail.embedding_provider_type}
                                  </span>
                                </div>
                              )}
                              {detail.embedding_vector_dimension != null && (
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-[#69637f]">
                                    {td("vectorDimension")}
                                  </span>
                                  <span className="font-semibold">
                                    {detail.embedding_vector_dimension}
                                  </span>
                                </div>
                              )}
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("pipelineSurface")}
                                </span>
                                <span className="font-semibold">
                                  {td("backendWorker")}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        {ocrMetadata && detail.file_type === "pdf" ? (
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <div className="mb-3 flex items-center gap-2">
                              <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                                {td("ocrExtraction")}
                              </h4>
                              <ContextualHelpLink topic="multilingual" />
                            </div>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("ocrRequired")}
                                </span>
                                <span className="font-semibold">
                                  {ocrMetadata.required
                                    ? td("errorYes").charAt(0).toUpperCase() +
                                      td("errorYes").slice(1)
                                    : td("errorNo").charAt(0).toUpperCase() +
                                      td("errorNo").slice(1)}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("detectionMode")}
                                </span>
                                <span className="font-semibold capitalize">
                                  {ocrMetadata.mode}
                                </span>
                              </div>
                              {ocrMetadata.required ? (
                                <>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("ocrStatus")}
                                    </span>
                                    <span
                                      className={`font-semibold capitalize ${ocrMetadata.status === "failed" ? "text-rose-600" : ocrMetadata.status === "partial" ? "text-amber-600" : "text-emerald-700"}`}
                                    >
                                      {ocrMetadata.status}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("languages")}
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.languages.length > 0
                                        ? ocrMetadata.languages.join(", ")
                                        : "-"}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("nativePages")}
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.nativeTextPages}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("ocrPages")}
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.pagesCompleted} /{" "}
                                      {ocrMetadata.pagesProcessed}
                                    </span>
                                  </div>
                                  {ocrMetadata.durationMs !== null ? (
                                    <div className="flex items-center justify-between gap-3">
                                      <span className="text-[#69637f]">
                                        {td("ocrDuration")}
                                      </span>
                                      <span className="font-semibold">
                                        {(
                                          ocrMetadata.durationMs / 1000
                                        ).toFixed(1)}
                                        s
                                      </span>
                                    </div>
                                  ) : null}
                                  {ocrMetadata.warnings.length > 0 ? (
                                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                                      <p className="mb-1 text-xs font-semibold tracking-wide text-amber-700 uppercase">
                                        {td("ocrWarnings")}
                                      </p>
                                      <ul className="space-y-1 text-xs text-amber-800">
                                        {ocrMetadata.warnings.map((w, i) => (
                                          <li key={i}>{w}</li>
                                        ))}
                                      </ul>
                                    </div>
                                  ) : null}
                                </>
                              ) : (
                                <p className="text-xs text-[#69637f]">
                                  {td("nativeTextNote")}
                                </p>
                              )}
                            </div>
                          </div>
                        ) : null}

                        {/* OCR quality diagnostics (F232) */}
                        {detail.file_type === "pdf" &&
                        (detail.ocr_quality_snapshot ||
                          detail.ocr_languages_override ||
                          capabilities.canOverrideLanguage) ? (
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("ocrQuality")}
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              {detail.ocr_languages_override ? (
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-[#69637f]">
                                    {td("languageOverride")}
                                  </span>
                                  <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-xs font-semibold text-[#3525cd]">
                                    {detail.ocr_languages_override}
                                  </span>
                                </div>
                              ) : null}
                              {detail.ocr_quality_snapshot ? (
                                <>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("avgConfidence")}
                                    </span>
                                    <span
                                      className={`font-semibold ${
                                        (detail.ocr_quality_snapshot
                                          .avg_confidence ?? 0) >= 0.7
                                          ? "text-emerald-700"
                                          : (detail.ocr_quality_snapshot
                                                .avg_confidence ?? 0) >= 0.3
                                            ? "text-amber-600"
                                            : "text-rose-600"
                                      }`}
                                    >
                                      {detail.ocr_quality_snapshot
                                        .avg_confidence !== null &&
                                      detail.ocr_quality_snapshot
                                        .avg_confidence !== undefined
                                        ? `${(detail.ocr_quality_snapshot.avg_confidence * 100).toFixed(0)}%`
                                        : "-"}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      {td("languagesUsed")}
                                    </span>
                                    <span className="font-semibold">
                                      {detail.ocr_quality_snapshot.languages
                                        .length > 0
                                        ? detail.ocr_quality_snapshot.languages.join(
                                            "+",
                                          )
                                        : "-"}
                                    </span>
                                  </div>
                                  {detail.ocr_quality_snapshot.pages_failed >
                                  0 ? (
                                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                                      <p className="text-xs font-semibold text-amber-700">
                                        {detail.ocr_quality_snapshot
                                          .pages_failed === 1
                                          ? td("pagesFailed", {
                                              count:
                                                detail.ocr_quality_snapshot
                                                  .pages_failed,
                                            })
                                          : td("pagesFailedPlural", {
                                              count:
                                                detail.ocr_quality_snapshot
                                                  .pages_failed,
                                            })}
                                      </p>
                                    </div>
                                  ) : null}
                                  {(detail.ocr_quality_snapshot
                                    .avg_confidence ?? 1) < 0.3 &&
                                  detail.ocr_quality_snapshot.pages_completed >
                                    0 ? (
                                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                                      <p className="text-xs font-semibold text-amber-700">
                                        {td("lowConfidence")}
                                      </p>
                                    </div>
                                  ) : null}
                                </>
                              ) : null}
                              {capabilities.canOverrideLanguage ? (
                                <div className="mt-2 border-t border-[#e9e6f5] pt-2">
                                  {ocrLangOverrideOpen ? (
                                    <div className="flex items-center gap-2">
                                      <select
                                        value={ocrLangOverrideValue}
                                        onChange={(e) =>
                                          setOcrLangOverrideValue(
                                            e.target.value,
                                          )
                                        }
                                        aria-label="Select OCR language"
                                        className="flex-1 cursor-pointer rounded border border-[#c7c4d8] bg-white px-2 py-1 text-xs font-medium text-[#2a2640] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                                      >
                                        <option value="">
                                          {td("clearOverride")}
                                        </option>
                                        {OCR_LANGUAGES.map((l) => (
                                          <option key={l.code} value={l.code}>
                                            {l.label}
                                          </option>
                                        ))}
                                      </select>
                                      <button
                                        type="button"
                                        disabled={ocrConfigMutation.isPending}
                                        onClick={() => {
                                          ocrConfigMutation.mutate({
                                            ocr_languages: ocrLangOverrideValue
                                              ? [ocrLangOverrideValue]
                                              : null,
                                          });
                                        }}
                                        className="rounded bg-[#3525cd] px-2 py-1 text-xs font-semibold text-white hover:bg-[#2a1eb0] disabled:opacity-50"
                                      >
                                        {ocrConfigMutation.isPending
                                          ? td("saving")
                                          : td("save")}
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setOcrLangOverrideOpen(false)
                                        }
                                        className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                                      >
                                        {td("cancel")}
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setOcrLangOverrideValue("");
                                        setOcrLangOverrideOpen(true);
                                      }}
                                      className="text-xs font-semibold text-[#3525cd] hover:underline"
                                    >
                                      {td("setOcrLanguage")}
                                    </button>
                                  )}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        ) : null}

                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <div className="mb-3 flex items-center gap-2">
                            <h4 className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("languageSection")}
                            </h4>
                            <ContextualHelpLink topic="multilingual" />
                          </div>
                          <div className="space-y-2 text-sm text-[#2a2640]">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-[#69637f]">
                                {td("detectedLanguage")}
                              </span>
                              <span className="font-semibold">
                                {detail.language
                                  ? (UPLOAD_LANGUAGES.find(
                                      (l) => l.code === detail.language,
                                    )?.label ?? detail.language.toUpperCase())
                                  : "-"}
                              </span>
                            </div>
                            {detail.language_confidence !== null &&
                            detail.language_confidence !== undefined ? (
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("confidence")}
                                </span>
                                <span className="font-semibold">
                                  {(detail.language_confidence * 100).toFixed(
                                    0,
                                  )}
                                  %
                                </span>
                              </div>
                            ) : null}
                            {detail.language_source ? (
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  {td("source")}
                                </span>
                                <span className="rounded-full bg-[#ece8ff] px-2 py-0.5 text-xs font-semibold text-[#3525cd]">
                                  {detail.language_source.replace(/_/g, " ")}
                                </span>
                              </div>
                            ) : null}
                            {capabilities.canOverrideLanguage ? (
                              <div className="mt-2 border-t border-[#e9e6f5] pt-2">
                                {langOverrideOpen ? (
                                  <div className="flex items-center gap-2">
                                    <select
                                      value={langOverrideValue}
                                      onChange={(e) =>
                                        setLangOverrideValue(e.target.value)
                                      }
                                      aria-label="Select override language"
                                      className="flex-1 cursor-pointer rounded border border-[#c7c4d8] bg-white px-2 py-1 text-xs font-medium text-[#2a2640] outline-none focus:ring-1 focus:ring-[#3525cd]/20"
                                    >
                                      <option value="">
                                        {td("clearOverride")}
                                      </option>
                                      {UPLOAD_LANGUAGES.map((l) => (
                                        <option key={l.code} value={l.code}>
                                          {l.label}
                                        </option>
                                      ))}
                                    </select>
                                    <button
                                      type="button"
                                      disabled={langOverrideMutation.isPending}
                                      onClick={() => {
                                        langOverrideMutation.mutate({
                                          language: langOverrideValue || null,
                                        });
                                      }}
                                      className="rounded bg-[#3525cd] px-2 py-1 text-xs font-semibold text-white hover:bg-[#2a1eb0] disabled:opacity-50"
                                    >
                                      {langOverrideMutation.isPending
                                        ? td("saving")
                                        : td("save")}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setLangOverrideOpen(false)}
                                      className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                                    >
                                      {td("cancel")}
                                    </button>
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setLangOverrideValue(
                                        detail.language ?? "",
                                      );
                                      setLangOverrideOpen(true);
                                    }}
                                    className="text-xs font-semibold text-[#3525cd] hover:underline"
                                  >
                                    {td("overrideLanguage")}
                                  </button>
                                )}
                              </div>
                            ) : null}
                          </div>
                        </div>

                        {/* Extraction diagnostics (F237) */}
                        {detail.file_type === "pdf" &&
                        detail.extraction_snapshot ? (
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("extractionDiagnostics")}
                            </h4>
                            <DocumentExtractionDiagnosticsPanel
                              snapshot={detail.extraction_snapshot}
                            />
                          </div>
                        ) : null}

                        <DocumentChunkingDiagnosticsPanel
                          documentId={documentId}
                          detail={detail}
                          canReindex={canReindex}
                          isReindexPending={reindexMutation.isPending}
                          chunkingIssueCount={chunkingIssueCount}
                          onQueueReindex={(payload, label) => {
                            setActionFeedback(null);
                            setActionRequestId(null);
                            reindexMutation.mutate({ payload, label });
                          }}
                        />

                        <DocumentGraphInsightsPanel
                          documentId={documentId}
                          graphExtractionStatus={graphStatus}
                          canReindex={canReindex && capabilities.canReindex}
                          isReindexPending={graphReindexMutation.isPending}
                          onReindexGraph={() => {
                            setActionFeedback(null);
                            setActionRequestId(null);
                            graphReindexMutation.mutate();
                          }}
                        />

                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <h4 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                            {td("aiSummary")}
                          </h4>
                          <p className="text-sm leading-relaxed text-[#2a2640]">
                            {td("aiSummaryBody", {
                              status: currentStatus,
                              chunks: detail.chunk_count,
                              pages:
                                detail.page_count != null
                                  ? td("acrossPages", {
                                      pages: detail.page_count,
                                    })
                                  : "",
                            })}
                          </p>
                        </div>
                      </div>
                    ) : null}

                    {activeTab === "chunks" ? (
                      <section className="space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <h3 className="text-base font-bold text-[#2a2640]">
                            {td("chunkPreviewTitle")}
                          </h3>
                          <div className="flex items-center gap-3">
                            {capabilities.canViewChunkFullText ? (
                              <label className="flex items-center gap-2 text-xs font-semibold tracking-wide text-[#5f5b72] uppercase">
                                <input
                                  type="checkbox"
                                  checked={includeFullText}
                                  onChange={(event) => {
                                    setChunksOffset(0);
                                    setIncludeFullText(event.target.checked);
                                  }}
                                  className="h-4 w-4 rounded border-[#c9c4de]"
                                />
                                {td("includeFullText")}
                              </label>
                            ) : null}
                            {chunksQuery.isFetching ? (
                              <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                                {td("refreshing")}
                              </span>
                            ) : null}
                          </div>
                        </div>

                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                          <label className="space-y-1">
                            <span className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                              {td("searchSampleChunks")}
                            </span>
                            <input
                              value={chunkSearchQuery}
                              onChange={(event) =>
                                setChunkSearchQuery(event.target.value)
                              }
                              placeholder={td("searchPlaceholder")}
                              className="w-full rounded-xl border border-[#c9c4de] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                            />
                          </label>
                          <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm text-[#4d4963]">
                            <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                              {td("searchScope")}
                            </p>
                            <p className="mt-1">
                              {(selectedChunks?.items.length ?? 0) === 1
                                ? td("loadedChunkSample", {
                                    count: selectedChunks?.items.length ?? 0,
                                  })
                                : td("loadedChunkSamples", {
                                    count: selectedChunks?.items.length ?? 0,
                                  })}
                            </p>
                          </div>
                        </div>

                        {chunksQuery.isLoading ? (
                          <LoadingState compact title={td("loadingChunks")} />
                        ) : null}

                        {chunksQuery.isError ? (
                          <ErrorState
                            compact
                            error={chunksQuery.error}
                            description={getApiErrorMessage(chunksQuery.error)}
                            onRetry={() => {
                              void chunksQuery.refetch();
                            }}
                            retryLabel={td("retryChunkLoad")}
                          />
                        ) : null}

                        {selectedChunks &&
                        selectedChunks.items.length === 0 &&
                        chunkStatus ? (
                          <EmptyState
                            compact
                            title={noChunksMessage(
                              chunkStatus,
                              noChunkMessages,
                            )}
                          />
                        ) : null}

                        {selectedChunks &&
                        selectedChunks.items.length > 0 &&
                        filteredChunks.length === 0 ? (
                          <EmptyState
                            compact
                            title={td("noChunkMatch")}
                            description={td("noChunkMatchDesc")}
                          />
                        ) : null}

                        {selectedChunks && filteredChunks.length > 0 ? (
                          <div className="space-y-2">
                            {filteredChunks.map((chunk) => {
                              const isCited =
                                chunk.chunk_id === highlightedChunkId;
                              return (
                                <article
                                  key={chunk.chunk_id}
                                  ref={
                                    isCited
                                      ? (el) => {
                                          highlightedChunkRef.current = el;
                                        }
                                      : undefined
                                  }
                                  className={`rounded-lg border px-3 py-3 ${
                                    isCited
                                      ? "border-[#3525cd]/30 bg-[#f0ecff] shadow-sm ring-1 ring-[#3525cd]/20"
                                      : "border-[#e4e1f2] bg-[#faf9ff]"
                                  }`}
                                >
                                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                                    {isCited ? (
                                      <span className="rounded bg-[#3525cd] px-1.5 py-0.5 text-[10px] font-bold text-white uppercase">
                                        {td("citedLabel")}
                                      </span>
                                    ) : null}
                                    <span>
                                      {td("chunkIndex", {
                                        index: chunk.chunk_index,
                                      })}
                                    </span>
                                    <span>
                                      {td("chunkPage", {
                                        n: chunk.page_number ?? "-",
                                      })}
                                    </span>
                                    <span>
                                      {td("chunkTokens", {
                                        n: chunk.token_count,
                                      })}
                                    </span>
                                    <span>
                                      {td("chunkModel", {
                                        name: chunk.embedding_model,
                                      })}
                                    </span>
                                    <span>
                                      {td("chunkIndexVersion", {
                                        version: chunk.index_version,
                                      })}
                                    </span>
                                    <span>
                                      {td("chunkCreated", {
                                        date: formatDate(chunk.created_at),
                                      })}
                                    </span>
                                  </div>
                                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-[#5f5a74]">
                                    <span>
                                      {chunk.section_path
                                        ? td("chunkSection", {
                                            path: chunk.section_path,
                                          })
                                        : td("chunkSectionNone")}
                                    </span>
                                    <span>·</span>
                                    <span>
                                      {td("chunkLanguage", {
                                        lang: chunk.language ?? "-",
                                      })}
                                    </span>
                                    <span>·</span>
                                    <span>
                                      {td("chunkLevel", {
                                        n: chunk.chunk_level ?? 0,
                                      })}
                                    </span>
                                    {chunk.source_start_offset != null &&
                                    chunk.source_end_offset != null ? (
                                      <>
                                        <span>·</span>
                                        <span>
                                          {td("chunkOffsets", {
                                            start: chunk.source_start_offset,
                                            end: chunk.source_end_offset,
                                          })}
                                        </span>
                                      </>
                                    ) : null}
                                  </div>
                                  <p className="text-sm break-words whitespace-pre-wrap text-[#2a2640]">
                                    {includeFullText && chunk.text
                                      ? chunk.text
                                      : truncateChunkPreview(
                                          chunk.text_preview,
                                        )}
                                  </p>
                                </article>
                              );
                            })}
                            <div className="mt-2 flex items-center justify-between gap-2">
                              <p className="text-xs text-[#6e6a86]">
                                {td("showingChunks", {
                                  shown: filteredChunks.length,
                                  total: selectedChunks.total,
                                })}
                              </p>
                              {!highlightedChunkId ? (
                                <div className="flex items-center gap-2">
                                  <button
                                    type="button"
                                    disabled={!canGoPrevChunks}
                                    onClick={() =>
                                      setChunksOffset((current) =>
                                        Math.max(0, current - CHUNK_PAGE_SIZE),
                                      )
                                    }
                                    className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                                  >
                                    {td("previous")}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={!canGoNextChunks}
                                    onClick={() =>
                                      setChunksOffset(
                                        (current) => current + CHUNK_PAGE_SIZE,
                                      )
                                    }
                                    className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                                  >
                                    {td("next")}
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          </div>
                        ) : null}
                      </section>
                    ) : null}

                    {activeTab === "errors" ? (
                      <section className="space-y-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <p className="text-2xl font-bold text-[#2a2640]">
                              {errorSummary.critical}
                            </p>
                            <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("criticalErrors")}
                            </p>
                          </div>
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <p className="text-2xl font-bold text-[#2a2640]">
                              {errorSummary.warnings}
                            </p>
                            <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              {td("warningsLabel")}
                            </p>
                          </div>
                        </div>

                        <div className="overflow-hidden rounded-lg border border-[#e9e6f5]">
                          <div className="border-b border-[#e9e6f5] bg-[#faf9ff] px-3 py-2 text-sm font-semibold text-[#2a2640]">
                            {td("errorLog")}
                          </div>
                          {errorRows.length === 0 ? (
                            <p className="px-3 py-4 text-sm text-[#69637f]">
                              {td("noErrors")}
                            </p>
                          ) : (
                            <div className="overflow-x-auto">
                              <table className="min-w-full text-left text-sm">
                                <thead className="bg-[#f7f5ff] text-xs tracking-wide text-[#69637f] uppercase">
                                  <tr>
                                    <th className="px-3 py-2 font-semibold">
                                      {td("errorColType")}
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      {td("errorColSeverity")}
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      {td("errorColMessage")}
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      {td("errorColTimestamp")}
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {errorRows.map((row) => (
                                    <tr
                                      key={row.key}
                                      className="border-t border-[#ece9f8]"
                                    >
                                      <td className="px-3 py-3 text-[#2a2640]">
                                        {row.type}
                                      </td>
                                      <td className="px-3 py-3">
                                        <span
                                          className={`rounded px-2 py-1 text-[10px] font-bold uppercase ${severityBadgeClass(row.severity)}`}
                                        >
                                          {row.severity}
                                        </span>
                                      </td>
                                      <td className="px-3 py-3 text-[#2a2640]">
                                        {row.message}
                                        {row.code ? (
                                          <span className="ml-1 font-mono text-xs text-[#69637f]">
                                            ({row.code})
                                          </span>
                                        ) : null}
                                      </td>
                                      <td className="px-3 py-3 font-mono text-xs text-[#69637f]">
                                        {formatDate(row.timestamp)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>

                        <div className="rounded-lg border border-[#d9d4f1] bg-[#f5f3ff] px-4 py-3">
                          <p className="mb-2 text-sm font-semibold text-[#2a2640]">
                            {td("recommendations")}
                          </p>
                          <ul className="list-disc space-y-1 pl-4 text-sm text-[#4d4868]">
                            {recommendations.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      </section>
                    ) : null}

                    {activeTab === "versions" ? (
                      <section className="space-y-3">
                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <h3 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                            Version history
                          </h3>
                          <p className="mb-4 text-xs text-[#69637f]">
                            A new version is recorded on every upload and
                            re-index. The{" "}
                            <span className="font-semibold text-emerald-700">
                              active
                            </span>{" "}
                            version is what the vector index currently serves.
                          </p>
                          <DocumentVersionHistoryPanel
                            documentId={documentId}
                          />
                        </div>
                      </section>
                    ) : null}

                    {activeTab === "metadata" ? (
                      <section className="space-y-3">
                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <DocumentMetadataPanel
                            documentId={documentId}
                            canEdit={capabilities.canDelete}
                          />
                        </div>
                      </section>
                    ) : null}
                  </div>
                </section>
              </div>
              <section className="rounded-xl border border-[#e4e1f2] bg-white p-4 shadow-sm lg:col-span-4">
                <h3 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  {td("lifecycleTitle")}
                </h3>
                <ol className="relative space-y-3">
                  <div className="absolute top-1 bottom-1 left-[11px] w-[2px] bg-[#e1e0eb]" />
                  {lifecycle.map((step) => (
                    <li
                      key={step.key}
                      className="relative z-10 flex items-start gap-3"
                    >
                      <span
                        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[12px] font-bold ${timelineStepClass(step.state)}`}
                      >
                        {timelineStepGlyph(step.state)}
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-semibold text-[#2a2640]">
                            {step.label}
                          </p>
                          <p className="text-[11px] text-[#68647b]">
                            {step.timestamp ? formatDate(step.timestamp) : "-"}
                          </p>
                        </div>
                        <p className="mt-0.5 text-xs text-[#5f5a74]">
                          {step.description}
                        </p>
                        {step.logs.slice(0, 1).map((line, index) => (
                          <p
                            key={`${step.key}-timeline-${index}`}
                            className="mt-1 text-xs break-words text-[#4c4970]"
                          >
                            {line}
                          </p>
                        ))}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            </div>

            <section className="rounded-xl border border-[#e4e1f2] bg-white p-4 shadow-sm">
              <h3 className="mb-3 text-base font-bold text-[#2a2640]">
                {td("previewTitle")}
              </h3>
              <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-4">
                <div className="flex flex-col items-center gap-4 text-center">
                  <div className="flex h-32 w-24 items-center justify-center rounded-lg border border-[#ddd7f6] bg-[#faf9ff] shadow-sm">
                    <span className="material-symbols-outlined text-[44px] text-[#3525cd]">
                      {documentTypeIcon(detail.file_type)}
                    </span>
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-[#2a2640]">
                      {td("viewOriginal", {
                        type: detail.file_type.toUpperCase(),
                      })}
                    </p>
                    <p className="font-mono text-xs break-all text-[#6e6a86]">
                      Source endpoint: /api/v1/documents/{detail.document_id}
                      /download
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={
                      !canDownloadOriginal || downloadMutation.isPending
                    }
                    onClick={() => {
                      setActionFeedback(null);
                      setActionRequestId(null);
                      downloadMutation.mutate();
                    }}
                    className="inline-flex items-center gap-2 rounded border border-[#cbc5e6] bg-white px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span className="material-symbols-outlined text-[18px]">
                      download
                    </span>
                    {downloadMutation.isPending
                      ? td("downloading")
                      : td("download")}
                  </button>
                </div>
              </div>
            </section>
          </div>
        ) : null}
        {previewCitationSet ? (
          <CitationPreviewDrawer
            citations={previewCitationSet.citations}
            initialIndex={previewCitationSet.initialIndex}
            onClose={() => setPreviewCitationSet(null)}
          />
        ) : null}
      </section>
    </section>
  );
}

function MetricCard({
  label,
  value,
  valueClass,
  plain = true,
  mono = false,
  wrap = false,
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  plain?: boolean;
  mono?: boolean;
  wrap?: boolean;
}) {
  if (!plain && valueClass) {
    return (
      <div className="flex h-[92px] flex-col rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
        <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {label}
        </p>
        <span className={valueClass}>{value}</span>
      </div>
    );
  }

  return (
    <div className="flex h-[92px] flex-col rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p
        className={`text-sm font-semibold text-[#2a2640] ${wrap ? "leading-relaxed break-all" : ""}`}
        title={typeof value === "string" ? value : undefined}
        style={
          mono
            ? {
                fontFamily:
                  "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace",
              }
            : undefined
        }
      >
        {value}
      </p>
    </div>
  );
}
