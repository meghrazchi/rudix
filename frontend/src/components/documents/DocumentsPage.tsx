"use client";

import { useEffect, useMemo, useState } from "react";

import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DocumentsUploadModal, type UploadFeedbackState } from "@/components/documents/DocumentsUploadModal";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import type {
  DocumentDetailResponse,
  DocumentListResponse,
  DocumentSortBy,
  DocumentStatus,
  DocumentStatusResponse,
  SortOrder,
} from "@/lib/api/documents";
import {
  deleteDocument,
  downloadDocumentFile,
  getDocument,
  getDocumentChunks,
  getDocumentStatus,
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  canDeleteDocument,
  canReindexDocument,
  resolveDocumentCapabilities,
  shouldPollDocumentList,
} from "@/lib/documents-ui";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  ACCEPTED_UPLOAD_TYPES_LABEL,
  maxUploadSizeMbFromEnv,
  validateUploadFile,
} from "@/components/documents/upload-validation";

const DOCUMENT_PAGE_SIZE = 20;
const CHUNK_PAGE_SIZE = 8;
const MAX_UPLOAD_SIZE_MB = maxUploadSizeMbFromEnv();

type StatusFilter = "all" | DocumentStatus;

const statusFilterOptions: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "uploaded", label: "Uploaded" },
  { value: "processing", label: "Processing" },
  { value: "indexed", label: "Indexed" },
  { value: "failed", label: "Failed" },
  { value: "deleting", label: "Deleting" },
  { value: "deleted", label: "Deleted" },
];

const sortByOptions: Array<{ value: DocumentSortBy; label: string }> = [
  { value: "created_at", label: "Created" },
  { value: "updated_at", label: "Updated" },
  { value: "filename", label: "Filename" },
  { value: "status", label: "Status" },
];

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
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
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
}

function deriveDetailStatus(detail: DocumentDetailResponse, liveStatus: DocumentStatusResponse | undefined): DocumentStatus {
  return liveStatus?.status ?? detail.status;
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

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const capabilities = resolveDocumentCapabilities(state.session?.role);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<DocumentSortBy>("created_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [offset, setOffset] = useState(0);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [chunksOffset, setChunksOffset] = useState(0);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadFeedback, setUploadFeedback] = useState<UploadFeedbackState | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);

  const listQueryOptions = useMemo(
    () => ({
      limit: DOCUMENT_PAGE_SIZE,
      offset,
      status: statusFilter === "all" ? undefined : statusFilter,
      sort_by: sortBy,
      sort_order: sortOrder,
    }),
    [offset, sortBy, sortOrder, statusFilter],
  );

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list(listQueryOptions),
    queryFn: () => listDocuments(listQueryOptions),
    refetchInterval: (query) => {
      const data = query.state.data as DocumentListResponse | undefined;
      return shouldPollDocumentList(data?.items) ? 4_000 : false;
    },
    refetchIntervalInBackground: true,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onMutate: (file) => {
      setUploadFeedback({
        state: "uploading",
        message: `Uploading ${file.name}...`,
      });
    },
    onSuccess: async (result) => {
      setUploadFeedback({
        state: "queued",
        message: `Uploaded ${result.filename}. Processing has been queued.`,
      });
      setActionFeedback(null);
      setActionRequestId(null);
      setSelectedDocumentId(result.document_id);
      setChunksOffset(0);
      await invalidateAfterMutation(queryClient, "document.upload");
      setUploadFeedback((previous) => {
        if (!previous || previous.state !== "queued") {
          return previous;
        }
        return {
          state: "success",
          message: `${result.filename} queued successfully. Document lists were refreshed.`,
        };
      });
      setIsUploadModalOpen(false);
    },
    onError: (error) => {
      setUploadFeedback({
        state: "failed",
        message: getApiErrorMessage(error),
        requestId: extractRequestIdFromError(error),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: async (result, documentId) => {
      setActionFeedback(`Delete requested for ${documentId}. Current status: ${result.status}.`);
      setActionRequestId(null);
      if (selectedDocumentId === documentId && result.status === "deleted") {
        setSelectedDocumentId(null);
      }
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
      setActionFeedback(`Re-index requested for ${documentId}. Queue status: ${result.queue_status}.`);
      setActionRequestId(null);
      setSelectedDocumentId(documentId);
      await invalidateAfterMutation(queryClient, "document.reindex");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
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

  const detailQuery = useQuery({
    queryKey: queryKeys.documents.detail(selectedDocumentId ?? ""),
    queryFn: () => getDocument(selectedDocumentId ?? ""),
    enabled: Boolean(selectedDocumentId),
  });

  const statusQuery = useQuery({
    queryKey: queryKeys.documents.status(selectedDocumentId ?? ""),
    queryFn: () => getDocumentStatus(selectedDocumentId ?? ""),
    enabled: Boolean(selectedDocumentId),
    refetchInterval: (query) => {
      const data = query.state.data as DocumentStatusResponse | undefined;
      if (!data) {
        return false;
      }
      if (data.status === "uploaded" || data.status === "processing" || data.status === "deleting") {
        return 4_000;
      }
      return false;
    },
  });

  const chunksQuery = useQuery({
    queryKey: queryKeys.documents.chunks(selectedDocumentId ?? "", {
      limit: CHUNK_PAGE_SIZE,
      offset: chunksOffset,
      include_full_text: false,
    }),
    queryFn: () =>
      getDocumentChunks(selectedDocumentId ?? "", {
        limit: CHUNK_PAGE_SIZE,
        offset: chunksOffset,
        include_full_text: false,
      }),
    enabled: Boolean(selectedDocumentId),
  });

  const documents = documentsQuery.data?.items ?? [];
  const selectedDetail = detailQuery.data;
  const selectedStatus = statusQuery.data;
  const selectedChunks = chunksQuery.data;

  const listForbidden = isForbiddenError(documentsQuery.error);
  const detailForbidden = isForbiddenError(detailQuery.error) || isForbiddenError(statusQuery.error);

  const pendingDeleteDocumentId = deleteMutation.isPending ? deleteMutation.variables : null;
  const pendingReindexDocumentId = reindexMutation.isPending ? reindexMutation.variables : null;
  const pendingDownloadDocumentId = downloadMutation.isPending ? downloadMutation.variables.documentId : null;

  const canGoPrevDocuments = offset > 0;
  const canGoNextDocuments = Boolean(documentsQuery.data && offset + DOCUMENT_PAGE_SIZE < documentsQuery.data.total);

  const canGoPrevChunks = chunksOffset > 0;
  const canGoNextChunks = Boolean(selectedChunks && chunksOffset + CHUNK_PAGE_SIZE < selectedChunks.total);

  useEffect(() => {
    const documentIdFromQuery = searchParams.get("document_id");
    if (!documentIdFromQuery) {
      return;
    }
    if (documentIdFromQuery !== selectedDocumentId) {
      setSelectedDocumentId(documentIdFromQuery);
      setChunksOffset(0);
    }
  }, [searchParams, selectedDocumentId]);

  async function handleFileUpload(file: File): Promise<void> {
    setActionFeedback(null);
    setActionRequestId(null);
    const validationError = validateUploadFile(file, MAX_UPLOAD_SIZE_MB);
    if (validationError) {
      setUploadFeedback({
        state: "failed",
        message: validationError,
      });
      return;
    }

    try {
      await uploadMutation.mutateAsync(file);
    } catch {
      // upload feedback state is handled in the mutation onError callback
    }
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Documents</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Upload, Index, and Manage Documents</h1>
        <p className="text-sm text-[#68647b]">
          Track ingestion status, inspect chunk previews, and run delete or re-index actions with permission-aware controls.
        </p>
      </header>

      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-[#2a2640]">Upload</h2>
          <div className="flex items-center gap-2">
            {!capabilities.canUpload ? (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                Read-only role
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => setIsUploadModalOpen(true)}
              disabled={uploadMutation.isPending}
              className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              Open upload modal
            </button>
          </div>
        </div>

        <p className="text-sm text-[#68647b]">
          Upload one file at a time using the dropzone modal. Supported formats: {ACCEPTED_UPLOAD_TYPES_LABEL}. Max
          size: {MAX_UPLOAD_SIZE_MB} MB.
        </p>

        {uploadFeedback ? (
          <p role="status" className="mt-3 text-sm text-[#3f3778]">
            Last upload state: <span className="font-semibold uppercase">{uploadFeedback.state}</span> —{" "}
            {uploadFeedback.message}
          </p>
        ) : null}
      </div>

      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-bold text-[#2a2640]">Documents</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Status
              <select
                value={statusFilter}
                onChange={(event) => {
                  setOffset(0);
                  setStatusFilter(event.target.value as StatusFilter);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
              >
                {statusFilterOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Sort
              <select
                value={sortBy}
                onChange={(event) => {
                  setOffset(0);
                  setSortBy(event.target.value as DocumentSortBy);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
              >
                {sortByOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Order
              <select
                value={sortOrder}
                onChange={(event) => {
                  setOffset(0);
                  setSortOrder(event.target.value as SortOrder);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
              >
                <option value="desc">Desc</option>
                <option value="asc">Asc</option>
              </select>
            </label>
          </div>
        </div>

        {actionFeedback ? (
          <p
            role="status"
            className="mb-4 rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
          >
            {actionFeedback}
            {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
          </p>
        ) : null}

        {documentsQuery.isLoading ? (
          <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]">
            Loading documents...
          </p>
        ) : null}

        {documentsQuery.isError && listForbidden ? (
          <ForbiddenState
            compact
            title="Documents access denied"
            description="You do not have permission to list documents in this organization."
            requestId={extractRequestIdFromError(documentsQuery.error)}
          />
        ) : null}

        {documentsQuery.isError && !listForbidden ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-800">
            <p>{getApiErrorMessage(documentsQuery.error)}</p>
            <button
              type="button"
              onClick={() => {
                void documentsQuery.refetch();
              }}
              className="mt-3 rounded border border-rose-300 bg-white px-3 py-1 text-xs font-semibold text-rose-800"
            >
              Retry
            </button>
          </div>
        ) : null}

        {!documentsQuery.isLoading && !documentsQuery.isError && documents.length === 0 ? (
          <div className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-8 text-center">
            <p className="text-base font-semibold text-[#2a2640]">No documents found</p>
            <p className="mt-1 text-sm text-[#68647b]">
              Upload your first {ACCEPTED_UPLOAD_TYPES_LABEL} file to start indexing and retrieval.
            </p>
          </div>
        ) : null}

        {!documentsQuery.isLoading && !documentsQuery.isError && documents.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-[#e4e1f2]">
            <table className="min-w-full divide-y divide-[#e7e4f4] bg-white text-sm">
              <thead className="bg-[#faf9ff]">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                  <th className="px-3 py-3">Filename</th>
                  <th className="px-3 py-3">Type</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Pages</th>
                  <th className="px-3 py-3">Chunks</th>
                  <th className="px-3 py-3">Created</th>
                  <th className="px-3 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f0edf8]">
                {documents.map((document) => {
                  const deleteEnabled = capabilities.canDelete && canDeleteDocument(document.status);
                  const reindexEnabled = capabilities.canReindex && canReindexDocument(document.status);
                  const downloadEnabled = document.status !== "deleted" && document.status !== "deleting";
                  const deleteBusy = pendingDeleteDocumentId === document.document_id;
                  const reindexBusy = pendingReindexDocumentId === document.document_id;
                  const downloadBusy = pendingDownloadDocumentId === document.document_id;

                  return (
                    <tr key={document.document_id} className="align-top text-[#2a2640]">
                      <td className="px-3 py-3">
                        <div className="font-semibold">{document.filename}</div>
                        <div className="text-xs text-[#7a768f]">{document.document_id}</div>
                        {document.error_message ? (
                          <p className="mt-1 text-xs text-rose-700">{document.error_message}</p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 uppercase">{document.file_type}</td>
                      <td className="px-3 py-3">
                        <span className={statusBadge(document.status)}>{document.status}</span>
                      </td>
                      <td className="px-3 py-3">{document.page_count ?? "-"}</td>
                      <td className="px-3 py-3">{document.chunk_count}</td>
                      <td className="px-3 py-3">{formatDate(document.created_at)}</td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedDocumentId(document.document_id);
                              setChunksOffset(0);
                              setActionFeedback(null);
                              setActionRequestId(null);
                            }}
                            className="rounded border border-[#cbc5e6] bg-white px-2 py-1 text-xs font-semibold text-[#3e376f]"
                          >
                            Inspect
                          </button>
                          <button
                            type="button"
                            disabled={!downloadEnabled || downloadBusy}
                            onClick={() => {
                              void downloadMutation.mutateAsync({
                                documentId: document.document_id,
                                filename: document.filename,
                              });
                            }}
                            className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {downloadBusy ? "Downloading..." : "Download"}
                          </button>
                          <button
                            type="button"
                            disabled={!deleteEnabled || deleteBusy}
                            onClick={() => {
                              void deleteMutation.mutateAsync(document.document_id);
                            }}
                            className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {deleteBusy ? "Deleting..." : "Delete"}
                          </button>
                          <button
                            type="button"
                            disabled={!reindexEnabled || reindexBusy}
                            onClick={() => {
                              void reindexMutation.mutateAsync(document.document_id);
                            }}
                            className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {reindexBusy ? "Queueing..." : "Re-index"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {!documentsQuery.isLoading && !documentsQuery.isError && documents.length > 0 ? (
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs text-[#6e6a86]">
              Showing {documents.length} of {documentsQuery.data?.total ?? documents.length} documents.
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={!canGoPrevDocuments}
                onClick={() => setOffset((current) => Math.max(0, current - DOCUMENT_PAGE_SIZE))}
                className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!canGoNextDocuments}
                onClick={() => setOffset((current) => current + DOCUMENT_PAGE_SIZE)}
                className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {selectedDocumentId ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-bold text-[#2a2640]">Document detail</h2>
            <button
              type="button"
              onClick={() => setSelectedDocumentId(null)}
              className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f]"
            >
              Close
            </button>
          </div>

          {detailQuery.isLoading ? (
            <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-4 text-sm text-[#5f5b72]">
              Loading document details...
            </p>
          ) : null}

          {(detailQuery.isError || statusQuery.isError) && detailForbidden ? (
            <ForbiddenState
              compact
              title="Document detail access denied"
              description="You do not have permission to inspect this document."
              requestId={extractRequestIdFromError(detailQuery.error ?? statusQuery.error)}
            />
          ) : null}

          {detailQuery.isError && !detailForbidden ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-800">
              {getApiErrorMessage(detailQuery.error)}
            </div>
          ) : null}

          {selectedDetail ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard label="Filename" value={selectedDetail.filename} />
                <MetricCard label="Type" value={selectedDetail.file_type.toUpperCase()} />
                <MetricCard
                  label="Status"
                  value={deriveDetailStatus(selectedDetail, selectedStatus)}
                  valueClass={statusBadge(deriveDetailStatus(selectedDetail, selectedStatus))}
                  plain={false}
                />
                <MetricCard label="Updated" value={formatDate(selectedDetail.updated_at)} />
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard label="Pages" value={selectedDetail.page_count ?? "-"} />
                <MetricCard label="Chunks" value={selectedDetail.chunk_count} />
                <MetricCard label="Checksum" value={selectedDetail.checksum ?? "-"} mono />
              </div>

              {selectedDetail.error_message ? (
                <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  {selectedDetail.error_message}
                </p>
              ) : null}

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h3 className="text-base font-bold text-[#2a2640]">Chunk previews</h3>
                  {chunksQuery.isFetching ? (
                    <span className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Refreshing...</span>
                  ) : null}
                </div>

                {chunksQuery.isLoading ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm text-[#5f5b72]">
                    Loading chunks...
                  </p>
                ) : null}

                {chunksQuery.isError ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                    {getApiErrorMessage(chunksQuery.error)}
                  </div>
                ) : null}

                {selectedChunks && selectedChunks.items.length === 0 ? (
                  <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm text-[#5f5b72]">
                    No chunks available yet for this document.
                  </p>
                ) : null}

                {selectedChunks && selectedChunks.items.length > 0 ? (
                  <div className="space-y-2">
                    {selectedChunks.items.map((chunk) => (
                      <article
                        key={chunk.chunk_id}
                        className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-3"
                      >
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                          <span>Chunk #{chunk.chunk_index}</span>
                          <span>Page {chunk.page_number ?? "-"}</span>
                          <span>{chunk.token_count} tokens</span>
                        </div>
                        <p className="text-sm text-[#2a2640]">{chunk.text_preview}</p>
                      </article>
                    ))}
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-xs text-[#6e6a86]">
                        Showing {selectedChunks.items.length} of {selectedChunks.total} chunks.
                      </p>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={!canGoPrevChunks}
                          onClick={() => setChunksOffset((current) => Math.max(0, current - CHUNK_PAGE_SIZE))}
                          className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Previous
                        </button>
                        <button
                          type="button"
                          disabled={!canGoNextChunks}
                          onClick={() => setChunksOffset((current) => current + CHUNK_PAGE_SIZE)}
                          className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <DocumentsUploadModal
        isOpen={isUploadModalOpen}
        canUpload={capabilities.canUpload}
        isUploading={uploadMutation.isPending}
        acceptedTypesLabel={ACCEPTED_UPLOAD_TYPES_LABEL}
        onClose={() => setIsUploadModalOpen(false)}
        onFileSelected={handleFileUpload}
        feedback={uploadFeedback}
      />
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
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">{label}</p>
        <span className={valueClass}>{value}</span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">{label}</p>
      <p
        className="text-sm font-semibold text-[#2a2640]"
        style={
          mono
            ? { fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace" }
            : undefined
        }
      >
        {value}
      </p>
    </div>
  );
}
