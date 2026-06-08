"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { DocumentChunkingDiagnosticsPanel } from "@/components/documents/DocumentChunkingDiagnosticsPanel";
import { DocumentExtractionDiagnosticsPanel } from "@/components/documents/DocumentExtractionDiagnosticsPanel";
import type {
  DocumentDetailResponse,
  DocumentLifecycleTimelineStepResponse,
  ReindexDocumentRequest,
  DocumentStatus,
  DocumentStatusResponse,
  AdminLanguageOverrideRequest,
  AdminOcrConfigRequest,
  OcrQualitySnapshot,
} from "@/lib/api/documents";
import {
  configureDocumentOcr,
  deleteDocument,
  downloadDocumentFile,
  getDocument,
  getDocumentChunks,
  overrideDocumentLanguage,
  reindexDocument,
  OCR_LANGUAGES,
  UPLOAD_LANGUAGES,
} from "@/lib/api/documents";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  canDeleteDocument,
  canReindexDocument,
  getDocumentLifecycleActionErrorMessage,
  resolveDocumentCapabilities,
} from "@/lib/documents-ui";
import { extractRequestIdFromError } from "@/lib/forbidden";
import { buildPipelineExplorerHref } from "@/lib/pipeline-links";
import { useDocumentStatusPolling } from "@/lib/use-document-status-polling";
import { useAuthSession } from "@/lib/use-auth-session";

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

type DetailTab = "overview" | "chunks" | "errors";
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

function noChunksMessage(status: DocumentStatus): string {
  if (status === "processing" || status === "uploaded") {
    return "Chunk extraction is still in progress. Chunks will appear after indexing completes.";
  }
  if (status === "failed") {
    return "No chunks are available because document processing failed. Re-index after resolving the failure.";
  }
  if (status === "deleting" || status === "deleted") {
    return "Chunk data is unavailable for documents being deleted or already deleted.";
  }
  return "No chunks are available for this document.";
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
): TimelineStep[] {
  const backendTimeline = Array.isArray(detail.lifecycle_timeline)
    ? detail.lifecycle_timeline.map((step) =>
        fromBackendLifecycleTimelineStep(step),
      )
    : [];
  return backendTimeline.filter((step) => step.state !== "pending");
}

function fromBackendLifecycleTimelineStep(
  step: DocumentLifecycleTimelineStepResponse,
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
    label: normalizeLifecycleLabel(step.step, step.label),
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

function normalizeLifecycleLabel(stepKey: string, label: string): string {
  if (stepKey === "extract") return "Extracted";
  if (stepKey === "detect_ocr") return "OCR detection";
  if (stepKey === "ocr") return "OCR";
  if (stepKey === "chunk") return "Chunked";
  if (stepKey === "embed") return "Embedded";
  if (stepKey === "index") return "Upserted to Qdrant";
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
): ErrorRow[] {
  const rows: ErrorRow[] = [];

  if (detail.error_message) {
    rows.push({
      key: "document-error",
      type: detail.error_details?.stage ?? "Document processing",
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

function deriveRecommendations(
  detail: DocumentDetailResponse,
  timeline: TimelineStep[],
): string[] {
  const recommendations: string[] = [];

  if (detail.error_details?.retryable) {
    recommendations.push(
      "Retry indexing after validating provider availability and queue health.",
    );
  }
  if (
    timeline.some(
      (step) =>
        step.state === "failed" ||
        step.logs.some((line) => /error|failed|timeout/i.test(line)),
    )
  ) {
    recommendations.push(
      "Open Pipeline Explorer to inspect the related run logs for the failing lifecycle step.",
    );
  }
  if (detail.page_count && detail.page_count > 100) {
    recommendations.push(
      "Use re-indexing with smaller chunk size for very large documents to improve retrieval quality.",
    );
  }
  if (recommendations.length === 0) {
    recommendations.push(
      "No active blocking errors were detected. The current index is healthy for retrieval.",
    );
  }

  return recommendations;
}

export function DocumentDetailPage({ documentId }: DocumentDetailPageProps) {
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
    label: "Document ID" | "Checksum",
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
      setActionFeedback(`Unable to copy ${label.toLowerCase()}.`);
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
      setActionFeedback(`Delete requested. Current status: ${result.status}.`);
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
    mutationFn: (input?: ReindexMutationInput) =>
      input?.payload
        ? reindexDocument(documentId, input.payload)
        : reindexDocument(documentId),
    onSuccess: async (result, variables) => {
      setActionFeedback(
        variables?.label
          ? `Re-index requested using ${variables.label}. Queue status: ${result.queue_status}.`
          : `Re-index requested. Queue status: ${result.queue_status}.`,
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
      setActionFeedback("Language override saved.");
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
      setActionFeedback("OCR language configuration saved.");
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
  const chunkStatus = currentStatus ?? detail?.status ?? null;
  const selectedChunks = chunksQuery.data;
  const lifecycle = useMemo(
    () => (detail && currentStatus ? buildLifecycleTimeline(detail) : []),
    [currentStatus, detail],
  );
  const errorRows = useMemo(
    () => (detail ? buildErrorRows(detail, lifecycle) : []),
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
    () => (detail ? deriveRecommendations(detail, lifecycle) : []),
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
          Rudix Document Detail
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Document Details
        </h1>
        <p className="text-sm text-[#68647b]">
          Review metadata, lifecycle events, chunk payloads, and processing
          errors from backend state.
        </p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        {detailQuery.isLoading ? (
          <LoadingState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]"
            title="Loading document detail..."
          />
        ) : null}

        {notFoundOrInaccessible ? (
          <EmptyState
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-6 text-center"
            title="Document not found"
            description="The requested document was not found or is not accessible in your current organization context."
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
                  </div>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
                    <span className="break-all">
                      Document ID: {detail.document_id}
                    </span>
                    <button
                      type="button"
                      aria-label="Copy document id"
                      onClick={() => {
                        void copyMetadataValue(
                          detail.document_id,
                          "Document ID",
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
                        Copied
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-[#5c5874]">
                    <span className="break-all">
                      Checksum: {detail.checksum ?? "-"}
                    </span>
                    <button
                      type="button"
                      aria-label="Copy checksum"
                      disabled={!detail.checksum}
                      onClick={() => {
                        void copyMetadataValue(
                          detail.checksum ?? null,
                          "Checksum",
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
                        Copied
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
                    Back to documents
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
                      Ask in Chat
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">
                      <span
                        aria-hidden="true"
                        className="material-symbols-outlined text-[16px]"
                      >
                        forum
                      </span>
                      Ask in Chat
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
                    View Pipeline
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
                        More actions
                      </summary>
                      <div className="absolute right-0 z-20 mt-1 flex min-w-[10.5rem] flex-col gap-1 rounded-lg border border-[#d8d3ea] bg-white p-1 shadow-lg">
                        {capabilities.canReindex ? (
                          <button
                            type="button"
                            disabled={!canReindex || reindexMutation.isPending}
                            onClick={(event) => {
                              (
                                event.currentTarget.closest(
                                  "details",
                                ) as HTMLDetailsElement | null
                              )?.removeAttribute("open");
                              setActionFeedback(null);
                              setActionRequestId(null);
                              reindexMutation.mutate({
                                label: "the system default profile",
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
                              ? "Queueing..."
                              : "Re-index"}
                          </button>
                        ) : null}
                        {capabilities.canDelete ? (
                          <button
                            type="button"
                            disabled={!canDelete || deleteMutation.isPending}
                            onClick={(event) => {
                              const confirmed = window.confirm(
                                `Delete document \"${detail.filename}\"? This action cannot be undone.`,
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
                              ? "Deleting..."
                              : "Delete"}
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
                    Citation evidence
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
                {activeTab !== "chunks" ? (
                  <button
                    type="button"
                    onClick={() => setActiveTab("chunks")}
                    className="mt-2 text-xs font-semibold text-[#3525cd] hover:underline"
                  >
                    View in chunks tab &rarr;
                  </button>
                ) : null}
              </div>
            ) : null}

            <div className="grid items-start gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-8">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <MetricCard
                    label="Page count"
                    value={detail.page_count ?? "-"}
                  />
                  <MetricCard label="Chunk count" value={detail.chunk_count} />
                  <MetricCard
                    label="File type"
                    value={detail.file_type.toUpperCase()}
                  />
                  <MetricCard
                    label="Updated"
                    value={formatDate(detail.updated_at)}
                  />
                </div>

                <section className="rounded-xl border border-[#e4e1f2] bg-white shadow-sm">
                  <div className="flex flex-wrap items-center border-b border-[#e9e6f5] px-4">
                    {(["overview", "chunks", "errors"] as const).map(
                      (tabKey) => (
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
                          {tabKey}
                          {tabKey === "errors" ? (
                            <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                              {errorRows.length}
                            </span>
                          ) : null}
                        </button>
                      ),
                    )}
                  </div>

                  <div className="space-y-4 p-4">
                    {activeTab === "overview" ? (
                      <div className="space-y-4">
                        {detail.error_message ? (
                          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-800">
                            <p className="font-semibold">Processing error</p>
                            <p className="mt-1">{detail.error_message}</p>
                            {detail.error_details ? (
                              <ul className="mt-2 space-y-1 text-xs">
                                <li>
                                  <span className="font-semibold">Stage:</span>{" "}
                                  {detail.error_details.stage}
                                </li>
                                <li>
                                  <span className="font-semibold">Code:</span>{" "}
                                  {detail.error_details.code}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    Category:
                                  </span>{" "}
                                  {detail.error_details.category}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    Retryable:
                                  </span>{" "}
                                  {detail.error_details.retryable
                                    ? "yes"
                                    : "no"}
                                </li>
                                <li>
                                  <span className="font-semibold">
                                    Message:
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
                              File summary
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">Filename</span>
                                <span className="font-semibold">
                                  {detail.filename}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  File type
                                </span>
                                <span className="font-semibold">
                                  {detail.file_type.toUpperCase()}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">Created</span>
                                <span className="font-semibold">
                                  {formatDate(detail.created_at)}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">Updated</span>
                                <span className="font-semibold">
                                  {formatDate(detail.updated_at)}
                                </span>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              Indexing intelligence
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">Status</span>
                                <span className={statusBadge(currentStatus)}>
                                  {currentStatus}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  Embedding model
                                </span>
                                <span className="font-semibold">
                                  {selectedChunks?.items[0]?.embedding_model ??
                                    "-"}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  Index version
                                </span>
                                <span className="font-semibold">
                                  {selectedChunks?.items[0]?.index_version ??
                                    "-"}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  Pipeline surface
                                </span>
                                <span className="font-semibold">
                                  Backend worker
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        {ocrMetadata && detail.file_type === "pdf" ? (
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              OCR extraction
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  OCR required
                                </span>
                                <span className="font-semibold">
                                  {ocrMetadata.required ? "Yes" : "No"}
                                </span>
                              </div>
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-[#69637f]">
                                  Detection mode
                                </span>
                                <span className="font-semibold capitalize">
                                  {ocrMetadata.mode}
                                </span>
                              </div>
                              {ocrMetadata.required ? (
                                <>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      OCR status
                                    </span>
                                    <span
                                      className={`font-semibold capitalize ${ocrMetadata.status === "failed" ? "text-rose-600" : ocrMetadata.status === "partial" ? "text-amber-600" : "text-emerald-700"}`}
                                    >
                                      {ocrMetadata.status}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      Languages
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.languages.length > 0
                                        ? ocrMetadata.languages.join(", ")
                                        : "-"}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      Native pages
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.nativeTextPages}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-[#69637f]">
                                      OCR pages
                                    </span>
                                    <span className="font-semibold">
                                      {ocrMetadata.pagesCompleted} /{" "}
                                      {ocrMetadata.pagesProcessed}
                                    </span>
                                  </div>
                                  {ocrMetadata.durationMs !== null ? (
                                    <div className="flex items-center justify-between gap-3">
                                      <span className="text-[#69637f]">
                                        OCR duration
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
                                        Warnings
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
                                  This document contains sufficient native text
                                  — OCR was skipped.
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
                              OCR quality
                            </h4>
                            <div className="space-y-2 text-sm text-[#2a2640]">
                              {detail.ocr_languages_override ? (
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-[#69637f]">
                                    Language override
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
                                      Avg confidence
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
                                      Languages used
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
                                        {
                                          detail.ocr_quality_snapshot
                                            .pages_failed
                                        }{" "}
                                        page
                                        {detail.ocr_quality_snapshot
                                          .pages_failed !== 1
                                          ? "s"
                                          : ""}{" "}
                                        failed OCR
                                      </p>
                                    </div>
                                  ) : null}
                                  {(detail.ocr_quality_snapshot
                                    .avg_confidence ?? 1) < 0.3 &&
                                  detail.ocr_quality_snapshot.pages_completed >
                                    0 ? (
                                    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                                      <p className="text-xs font-semibold text-amber-700">
                                        Low OCR confidence — consider
                                        re-indexing with the correct language
                                        pack.
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
                                          — clear override —
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
                                          ? "Saving…"
                                          : "Save"}
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setOcrLangOverrideOpen(false)
                                        }
                                        className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                                      >
                                        Cancel
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
                                      Set OCR language
                                    </button>
                                  )}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        ) : null}

                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <h4 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                            Language
                          </h4>
                          <div className="space-y-2 text-sm text-[#2a2640]">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-[#69637f]">
                                Detected language
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
                                  Confidence
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
                                <span className="text-[#69637f]">Source</span>
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
                                        — clear override —
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
                                        ? "Saving…"
                                        : "Save"}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setLangOverrideOpen(false)}
                                      className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-medium text-[#69637f] hover:bg-[#f0ecf9]"
                                    >
                                      Cancel
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
                                    Override language
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
                              Extraction diagnostics
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

                        <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                          <h4 className="mb-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                            AI summary
                          </h4>
                          <p className="text-sm leading-relaxed text-[#2a2640]">
                            Document is currently{" "}
                            <strong>{currentStatus}</strong> with{" "}
                            {detail.chunk_count} indexed chunks
                            {detail.page_count !== null
                              ? ` across ${detail.page_count} pages`
                              : ""}{" "}
                            and checksum persisted for ingestion integrity
                            checks.
                          </p>
                        </div>
                      </div>
                    ) : null}

                    {activeTab === "chunks" ? (
                      <section className="space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <h3 className="text-base font-bold text-[#2a2640]">
                            Chunk preview
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
                                Include full chunk text
                              </label>
                            ) : null}
                            {chunksQuery.isFetching ? (
                              <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                                Refreshing...
                              </span>
                            ) : null}
                          </div>
                        </div>

                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                          <label className="space-y-1">
                            <span className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                              Search sample chunks
                            </span>
                            <input
                              value={chunkSearchQuery}
                              onChange={(event) =>
                                setChunkSearchQuery(event.target.value)
                              }
                              placeholder="Filter by preview text, section path, page, or language"
                              className="w-full rounded-xl border border-[#c9c4de] bg-white px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                            />
                          </label>
                          <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm text-[#4d4963]">
                            <p className="text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                              Search scope
                            </p>
                            <p className="mt-1">
                              {selectedChunks?.items.length ?? 0} loaded chunk
                              sample
                              {(selectedChunks?.items.length ?? 0) === 1
                                ? ""
                                : "s"}
                              .
                            </p>
                          </div>
                        </div>

                        {chunksQuery.isLoading ? (
                          <LoadingState compact title="Loading chunks..." />
                        ) : null}

                        {chunksQuery.isError ? (
                          <ErrorState
                            compact
                            error={chunksQuery.error}
                            description={getApiErrorMessage(chunksQuery.error)}
                            onRetry={() => {
                              void chunksQuery.refetch();
                            }}
                            retryLabel="Retry chunk load"
                          />
                        ) : null}

                        {selectedChunks &&
                        selectedChunks.items.length === 0 &&
                        chunkStatus ? (
                          <EmptyState
                            compact
                            title={noChunksMessage(chunkStatus)}
                          />
                        ) : null}

                        {selectedChunks &&
                        selectedChunks.items.length > 0 &&
                        filteredChunks.length === 0 ? (
                          <EmptyState
                            compact
                            title="No chunk samples matched this filter."
                            description="Try a shorter phrase, a page number, or clear the search."
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
                                        cited
                                      </span>
                                    ) : null}
                                    <span>Chunk #{chunk.chunk_index}</span>
                                    <span>Page {chunk.page_number ?? "-"}</span>
                                    <span>{chunk.token_count} tokens</span>
                                    <span>Model {chunk.embedding_model}</span>
                                    <span>Index {chunk.index_version}</span>
                                    <span>
                                      Created {formatDate(chunk.created_at)}
                                    </span>
                                  </div>
                                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-[#5f5a74]">
                                    <span>
                                      Section{" "}
                                      {chunk.section_path ?? "not recorded"}
                                    </span>
                                    <span>·</span>
                                    <span>
                                      Language {chunk.language ?? "-"}
                                    </span>
                                    <span>·</span>
                                    <span>Level {chunk.chunk_level ?? 0}</span>
                                    {chunk.source_start_offset != null &&
                                    chunk.source_end_offset != null ? (
                                      <>
                                        <span>·</span>
                                        <span>
                                          Offsets {chunk.source_start_offset}-
                                          {chunk.source_end_offset}
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
                                Showing {filteredChunks.length} of{" "}
                                {selectedChunks.total} chunks.
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
                                    Previous
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
                                    Next
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
                              Critical errors
                            </p>
                          </div>
                          <div className="rounded-lg border border-[#e9e6f5] bg-[#faf9ff] p-4">
                            <p className="text-2xl font-bold text-[#2a2640]">
                              {errorSummary.warnings}
                            </p>
                            <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                              Warnings
                            </p>
                          </div>
                        </div>

                        <div className="overflow-hidden rounded-lg border border-[#e9e6f5]">
                          <div className="border-b border-[#e9e6f5] bg-[#faf9ff] px-3 py-2 text-sm font-semibold text-[#2a2640]">
                            Error log
                          </div>
                          {errorRows.length === 0 ? (
                            <p className="px-3 py-4 text-sm text-[#69637f]">
                              No backend error entries were reported for this
                              document.
                            </p>
                          ) : (
                            <div className="overflow-x-auto">
                              <table className="min-w-full text-left text-sm">
                                <thead className="bg-[#f7f5ff] text-xs tracking-wide text-[#69637f] uppercase">
                                  <tr>
                                    <th className="px-3 py-2 font-semibold">
                                      Type
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      Severity
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      Message
                                    </th>
                                    <th className="px-3 py-2 font-semibold">
                                      Timestamp
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
                            Re-indexing recommendations
                          </p>
                          <ul className="list-disc space-y-1 pl-4 text-sm text-[#4d4868]">
                            {recommendations.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      </section>
                    ) : null}
                  </div>
                </section>
              </div>
              <section className="rounded-xl border border-[#e4e1f2] bg-white p-4 shadow-sm lg:col-span-4">
                <h3 className="mb-3 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  Lifecycle timeline
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
                Document preview
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
                      View Original {detail.file_type.toUpperCase()}
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
                      ? "Preparing download..."
                      : "Download original file"}
                  </button>
                </div>
              </div>
            </section>
          </div>
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
