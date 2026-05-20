"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import type {
  DocumentDetailResponse,
  DocumentStatus,
  DocumentStatusResponse,
} from "@/lib/api/documents";
import {
  deleteDocument,
  getDocument,
  getDocumentChunks,
  reindexDocument,
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
    return "border-emerald-200 bg-emerald-50 text-emerald-900";
  }
  if (state === "active") {
    return "border-blue-200 bg-blue-50 text-blue-900";
  }
  if (state === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-900";
  }
  return "border-[#e4e1f2] bg-[#faf9ff] text-[#5f5a74]";
}

function buildLifecycleTimeline(
  status: DocumentStatus,
  detail: DocumentDetailResponse,
): TimelineStep[] {
  const createdAt = detail.created_at;
  const updatedAt = detail.updated_at;
  const isTerminal =
    status === "indexed" || status === "failed" || status === "deleted";

  return [
    {
      key: "uploaded",
      label: "Uploaded",
      description: "Document metadata accepted and queued for processing.",
      state: "completed",
      timestamp: createdAt,
    },
    {
      key: "processing",
      label: "Processing",
      description: "Extraction, chunking, and embedding generation.",
      state:
        status === "processing"
          ? "active"
          : status === "uploaded"
            ? "pending"
            : "completed",
      timestamp: status === "processing" || isTerminal ? updatedAt : null,
    },
    {
      key: "indexed",
      label: "Indexed",
      description: "Ready for retrieval and chat queries.",
      state:
        status === "indexed"
          ? "completed"
          : status === "failed"
            ? "failed"
            : status === "deleted" || status === "deleting"
              ? "completed"
              : "pending",
      timestamp:
        status === "indexed" || status === "deleted" || status === "deleting"
          ? updatedAt
          : null,
    },
    {
      key: "failed",
      label: "Failed",
      description: "Processing stopped due to a recoverable or terminal error.",
      state: status === "failed" ? "failed" : "pending",
      timestamp: status === "failed" ? updatedAt : null,
    },
    {
      key: "deleting",
      label: "Deleting",
      description: "Deletion queued or currently in progress.",
      state:
        status === "deleting"
          ? "active"
          : status === "deleted"
            ? "completed"
            : "pending",
      timestamp:
        status === "deleting" || status === "deleted" ? updatedAt : null,
    },
    {
      key: "deleted",
      label: "Deleted",
      description: "Document removed from active organization access.",
      state: status === "deleted" ? "completed" : "pending",
      timestamp: status === "deleted" ? updatedAt : null,
    },
  ];
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

export function DocumentDetailPage({ documentId }: DocumentDetailPageProps) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const capabilities = resolveDocumentCapabilities(state.session?.role);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [chunksOffset, setChunksOffset] = useState(0);
  const [includeFullText, setIncludeFullText] = useState(false);

  const detailQuery = useQuery({
    queryKey: queryKeys.documents.detail(documentId),
    queryFn: () => getDocument(documentId),
  });

  const statusQuery = useDocumentStatusPolling(documentId, {
    enabled: detailQuery.isSuccess,
    initialStatus: detailQuery.data?.status ?? null,
    refetchInBackground: true,
  });

  const chunksQuery = useQuery({
    queryKey: queryKeys.documents.chunks(documentId, {
      limit: CHUNK_PAGE_SIZE,
      offset: chunksOffset,
      include_full_text: includeFullText,
    }),
    queryFn: () =>
      getDocumentChunks(documentId, {
        limit: CHUNK_PAGE_SIZE,
        offset: chunksOffset,
        include_full_text: includeFullText,
      }),
    enabled: detailQuery.isSuccess,
  });

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
    mutationFn: () => reindexDocument(documentId),
    onSuccess: async (result) => {
      setActionFeedback(
        `Re-index requested. Queue status: ${result.queue_status}.`,
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
    () =>
      detail && currentStatus
        ? buildLifecycleTimeline(currentStatus, detail)
        : [],
    [currentStatus, detail],
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
          Document Metadata and Lifecycle
        </h1>
        <p className="text-sm text-[#68647b]">
          Review document processing status, metadata, structured errors, and
          lifecycle actions.
        </p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-[#2a2640]">Overview</h2>
          <Link
            href={safeBackHref}
            className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            Back to documents
          </Link>
        </div>

        {detailQuery.isLoading ? (
          <LoadingState
            className="mt-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]"
            title="Loading document detail..."
          />
        ) : null}

        {notFoundOrInaccessible ? (
          <EmptyState
            className="mt-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-6 text-center"
            title="Document not found"
            description="The requested document was not found or is not accessible in your current organization context."
          />
        ) : null}

        {!detailQuery.isLoading &&
        detailQuery.isError &&
        !notFoundOrInaccessible ? (
          <div className="mt-4">
            <ErrorState
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => {
                void detailQuery.refetch();
                void statusQuery.refetch();
              }}
            />
          </div>
        ) : null}

        {detail && currentStatus && !notFoundOrInaccessible ? (
          <div className="mt-4 space-y-4">
            {actionFeedback ? (
              <p
                role="status"
                className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
              >
                {actionFeedback}
                {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
              </p>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricCard label="Filename" value={detail.filename} />
              <MetricCard
                label="File type"
                value={detail.file_type.toUpperCase()}
              />
              <MetricCard
                label="Status"
                value={currentStatus}
                valueClass={statusBadge(currentStatus)}
                plain={false}
              />
              <MetricCard
                label="Checksum"
                value={detail.checksum ?? "-"}
                mono
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricCard label="Pages" value={detail.page_count ?? "-"} />
              <MetricCard label="Chunks" value={detail.chunk_count} />
              <MetricCard
                label="Created"
                value={formatDate(detail.created_at)}
              />
              <MetricCard
                label="Updated"
                value={formatDate(detail.updated_at)}
              />
            </div>

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
                      <span className="font-semibold">Category:</span>{" "}
                      {detail.error_details.category}
                    </li>
                    <li>
                      <span className="font-semibold">Retryable:</span>{" "}
                      {detail.error_details.retryable ? "yes" : "no"}
                    </li>
                    <li>
                      <span className="font-semibold">Message:</span>{" "}
                      {detail.error_details.message}
                    </li>
                  </ul>
                ) : null}
              </div>
            ) : null}

            <section>
              <h3 className="mb-2 text-base font-bold text-[#2a2640]">
                Lifecycle timeline
              </h3>
              <ol className="space-y-2">
                {lifecycle.map((step) => (
                  <li
                    key={step.key}
                    className={`rounded-lg border px-3 py-3 text-sm ${timelineStepClass(step.state)}`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold">{step.label}</p>
                      <p className="text-xs">
                        {step.timestamp ? formatDate(step.timestamp) : "-"}
                      </p>
                    </div>
                    <p className="mt-1 text-xs">{step.description}</p>
                  </li>
                ))}
              </ol>
            </section>

            <section>
              <h3 className="mb-2 text-base font-bold text-[#2a2640]">
                Actions
              </h3>
              <div className="flex flex-wrap gap-2">
                {canAskInChat ? (
                  <Link
                    href={`/chat?document_id=${encodeURIComponent(documentId)}`}
                    className="rounded border border-[#cbc5e6] bg-white px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                  >
                    Ask in Chat
                  </Link>
                ) : (
                  <span className="rounded border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-500">
                    Ask in Chat
                  </span>
                )}
                <Link
                  href={buildPipelineExplorerHref({
                    runType: "document.process",
                    documentId,
                  })}
                  className="rounded border border-[#cbc5e6] bg-white px-3 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
                >
                  View Pipeline
                </Link>
                {capabilities.canDelete ? (
                  <button
                    type="button"
                    disabled={!canDelete || deleteMutation.isPending}
                    onClick={() => {
                      const confirmed = window.confirm(
                        `Delete document \"${detail.filename}\"? This action cannot be undone.`,
                      );
                      if (!confirmed) {
                        return;
                      }
                      setActionFeedback(null);
                      setActionRequestId(null);
                      deleteMutation.mutate();
                    }}
                    className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {deleteMutation.isPending ? "Deleting..." : "Delete"}
                  </button>
                ) : null}
                {capabilities.canReindex ? (
                  <button
                    type="button"
                    disabled={!canReindex || reindexMutation.isPending}
                    onClick={() => {
                      setActionFeedback(null);
                      setActionRequestId(null);
                      reindexMutation.mutate();
                    }}
                    className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {reindexMutation.isPending ? "Queueing..." : "Re-index"}
                  </button>
                ) : null}
              </div>
            </section>

            <section>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
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
                <EmptyState compact title={noChunksMessage(chunkStatus)} />
              ) : null}

              {selectedChunks && selectedChunks.items.length > 0 ? (
                <div className="space-y-2">
                  {selectedChunks.items.map((chunk) => (
                    <article
                      key={chunk.chunk_id}
                      className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-3"
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                        <span>Chunk #{chunk.chunk_index}</span>
                        <span>Page {chunk.page_number ?? "-"}</span>
                        <span>{chunk.token_count} tokens</span>
                        <span>Model {chunk.embedding_model}</span>
                        <span>Index {chunk.index_version}</span>
                        <span>Created {formatDate(chunk.created_at)}</span>
                      </div>
                      <p className="text-sm break-words whitespace-pre-wrap text-[#2a2640]">
                        {includeFullText && chunk.text
                          ? chunk.text
                          : truncateChunkPreview(chunk.text_preview)}
                      </p>
                    </article>
                  ))}
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-xs text-[#6e6a86]">
                      Showing {selectedChunks.items.length} of{" "}
                      {selectedChunks.total} chunks.
                    </p>
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
                  </div>
                </div>
              ) : null}
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
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  plain?: boolean;
  mono?: boolean;
}) {
  if (!plain && valueClass) {
    return (
      <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
        <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
          {label}
        </p>
        <span className={valueClass}>{value}</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p
        className="text-sm font-semibold text-[#2a2640]"
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
