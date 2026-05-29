"use client";

import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  DocumentsUploadModal,
  type UploadFeedbackState,
  type UploadProgressItem,
  type UploadProgressItemState,
  type UploadProgressState,
} from "@/components/documents/DocumentsUploadModal";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import type {
  DocumentDetailResponse,
  DocumentFileType,
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
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  canDeleteDocument,
  canReindexDocument,
  getDocumentLifecycleActionErrorMessage,
  resolveDocumentCapabilities,
  shouldPollDocumentList,
} from "@/lib/documents-ui";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useDocumentStatusPolling } from "@/lib/use-document-status-polling";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  ACCEPTED_UPLOAD_TYPES_LABEL,
  maxUploadSizeMbFromEnv,
  validateUploadFile,
} from "@/components/documents/upload-validation";

const DOCUMENT_PAGE_SIZE = 20;
const CHUNK_PAGE_SIZE = 8;
const MAX_UPLOAD_SIZE_MB = maxUploadSizeMbFromEnv();
const REINDEX_ALL_PAGE_SIZE = 200;
const REINDEX_ALL_TARGET_STATUSES: DocumentStatus[] = ["uploaded", "failed"];

type StatusFilter = "all" | DocumentStatus;
type FileTypeFilter = "all" | DocumentFileType;
type IndexingStatusSummary = {
  total: number;
  uploaded: number;
  indexed: number;
  processing: number;
  failed: number;
};

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

const fileTypeFilterOptions: Array<{ value: FileTypeFilter; label: string }> = [
  { value: "all", label: "All types" },
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "DOCX" },
  { value: "txt", label: "TXT" },
];

function parseStatusFilter(value: string | null): StatusFilter {
  if (!value) {
    return "all";
  }
  const supported: DocumentStatus[] = [
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "deleting",
    "deleted",
  ];
  return supported.includes(value as DocumentStatus)
    ? (value as DocumentStatus)
    : "all";
}

function parseSortBy(value: string | null): DocumentSortBy {
  if (value === "updated_at" || value === "filename" || value === "status") {
    return value;
  }
  return "created_at";
}

function parseSortOrder(value: string | null): SortOrder {
  return value === "asc" ? "asc" : "desc";
}

function parseOffset(value: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return parsed;
}

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
  if (status === "deleted") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
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

function documentTypeIconClass(fileType: string): string {
  if (fileType === "pdf") {
    return "text-[#3525cd]";
  }
  if (fileType === "docx") {
    return "text-[#505f76]";
  }
  return "text-[#7e3000]";
}

function buildPaginationItems(
  currentPage: number,
  totalPages: number,
): Array<number | null> {
  if (totalPages <= 6) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const items: Array<number | null> = [1];
  const left = Math.max(2, currentPage - 1);
  const right = Math.min(totalPages - 1, currentPage + 1);

  if (left > 2) {
    items.push(null);
  }

  for (let page = left; page <= right; page += 1) {
    items.push(page);
  }

  if (right < totalPages - 1) {
    items.push(null);
  }

  items.push(totalPages);
  return items;
}

function deriveDetailStatus(
  detail: DocumentDetailResponse,
  liveStatus: DocumentStatusResponse | undefined,
): DocumentStatus {
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

function isAbortError(error: unknown): boolean {
  if (
    error instanceof DOMException &&
    error.name.toLowerCase() === "aborterror"
  ) {
    return true;
  }

  if (error instanceof Error) {
    const normalized = error.message.trim().toLowerCase();
    return normalized.includes("aborted");
  }

  return false;
}

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const capabilities = resolveDocumentCapabilities(state.session?.role);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() =>
    parseStatusFilter(searchParams.get("status")),
  );
  const [sortBy, setSortBy] = useState<DocumentSortBy>(() =>
    parseSortBy(searchParams.get("sort_by")),
  );
  const [sortOrder, setSortOrder] = useState<SortOrder>(() =>
    parseSortOrder(searchParams.get("sort_order")),
  );
  const [offset, setOffset] = useState(() =>
    parseOffset(searchParams.get("offset")),
  );
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(
    () => searchParams.get("document_id"),
  );
  const [chunksOffset, setChunksOffset] = useState(0);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadFeedback, setUploadFeedback] =
    useState<UploadFeedbackState | null>(null);
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressState | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isPageDropActive, setIsPageDropActive] = useState(false);
  const [isReindexAllPending, setIsReindexAllPending] = useState(false);
  const uploadControllersRef = useRef<Map<number, AbortController>>(new Map());
  const canceledUploadIndexesRef = useRef<Set<number>>(new Set());
  const cancelAllUploadsRequestedRef = useRef(false);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [filenameSearch, setFilenameSearch] = useState("");
  const [debouncedFilenameSearch, setDebouncedFilenameSearch] = useState("");
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>("all");

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedFilenameSearch(filenameSearch);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [filenameSearch]);

  const listQueryOptions = useMemo(
    () => ({
      limit: DOCUMENT_PAGE_SIZE,
      offset,
      status: statusFilter === "all" ? undefined : statusFilter,
      file_type: fileTypeFilter === "all" ? undefined : fileTypeFilter,
      sort_by: sortBy,
      sort_order: sortOrder,
      filename_query: debouncedFilenameSearch || undefined,
    }),
    [offset, sortBy, sortOrder, statusFilter, fileTypeFilter, debouncedFilenameSearch],
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
  const indexingStatusQuery = useQuery({
    queryKey: [...queryKeys.documents.all, "indexing-status-summary"] as const,
    queryFn: async (): Promise<IndexingStatusSummary> => {
      const [all, uploaded, indexed, processing, failed] = await Promise.all([
        listDocuments({ limit: 1, offset: 0 }),
        listDocuments({ limit: 1, offset: 0, status: "uploaded" }),
        listDocuments({ limit: 1, offset: 0, status: "indexed" }),
        listDocuments({ limit: 1, offset: 0, status: "processing" }),
        listDocuments({ limit: 1, offset: 0, status: "failed" }),
      ]);

      return {
        total: all.total,
        uploaded: uploaded.total,
        indexed: indexed.total,
        processing: processing.total,
        failed: failed.total,
      };
    },
    refetchInterval: (query) => {
      const data = query.state.data as IndexingStatusSummary | undefined;
      return data && data.processing > 0 ? 4_000 : false;
    },
    refetchIntervalInBackground: true,
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: async (result, documentId) => {
      setActionFeedback(
        `Delete requested for ${documentId}. Current status: ${result.status}.`,
      );
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

  const reindexMutation = useMutation({
    mutationFn: (documentId: string) => reindexDocument(documentId),
    onSuccess: async (result, documentId) => {
      setActionFeedback(
        `Re-index requested for ${documentId}. Queue status: ${result.queue_status}.`,
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

  const detailQuery = useQuery({
    queryKey: queryKeys.documents.detail(selectedDocumentId ?? ""),
    queryFn: () => getDocument(selectedDocumentId ?? ""),
    enabled: Boolean(selectedDocumentId),
  });

  const statusQuery = useDocumentStatusPolling(selectedDocumentId, {
    enabled: Boolean(selectedDocumentId),
    initialStatus: detailQuery.data?.status ?? null,
    refetchInBackground: true,
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
  const detailForbidden =
    isForbiddenError(detailQuery.error) || isForbiddenError(statusQuery.error);

  const pendingDeleteDocumentId = deleteMutation.isPending
    ? deleteMutation.variables
    : null;
  const pendingReindexDocumentId = reindexMutation.isPending
    ? reindexMutation.variables
    : null;
  const pendingDownloadDocumentId = downloadMutation.isPending
    ? downloadMutation.variables.documentId
    : null;

  const canGoPrevDocuments = offset > 0;
  const canGoNextDocuments = Boolean(
    documentsQuery.data &&
    offset + DOCUMENT_PAGE_SIZE < documentsQuery.data.total,
  );

  const canGoPrevChunks = chunksOffset > 0;
  const canGoNextChunks = Boolean(
    selectedChunks && chunksOffset + CHUNK_PAGE_SIZE < selectedChunks.total,
  );

  const currentListHref = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "all") {
      params.set("status", statusFilter);
    }
    params.set("sort_by", sortBy);
    params.set("sort_order", sortOrder);
    if (offset > 0) {
      params.set("offset", String(offset));
    }
    const serialized = params.toString();
    return serialized ? `/documents?${serialized}` : "/documents";
  }, [offset, sortBy, sortOrder, statusFilter]);

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
      if (response.items.length === 0 || currentOffset >= response.total) {
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
    setActionFeedback("Collecting non-indexed documents for re-index...");
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
        setActionFeedback(
          "No non-indexed documents are eligible for re-index.",
        );
        setActionRequestId(null);
        return;
      }

      let queuedCount = 0;
      let failedCount = 0;
      let lastErrorRequestId: string | null = null;
      let firstQueuedDocumentId: string | null = null;

      for (const [index, documentId] of orderedTargetIds.entries()) {
        setActionFeedback(
          `Queueing re-index (${index + 1}/${orderedTargetIds.length})...`,
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
        setActionFeedback(
          `Re-index queued for ${queuedCount} non-indexed document(s).`,
        );
        setActionRequestId(null);
      } else if (queuedCount > 0) {
        setActionFeedback(
          `Re-index queued for ${queuedCount} non-indexed document(s); ${failedCount} failed.`,
        );
        setActionRequestId(lastErrorRequestId);
      } else {
        setActionFeedback(
          "No re-index jobs were queued. Check document lifecycle state and retry.",
        );
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

  function updateUploadProgressItem(
    items: UploadProgressItem[],
    index: number,
    state: UploadProgressItemState,
    message?: string,
    requestId?: string | null,
  ): UploadProgressItem[] {
    return items.map((item, itemIndex) => {
      if (itemIndex !== index) {
        return item;
      }
      return {
        ...item,
        state,
        message: message ?? item.message,
        requestId: requestId ?? item.requestId,
      };
    });
  }

  function hasCancelableUploads(progress: UploadProgressState | null): boolean {
    if (!progress) {
      return false;
    }

    return progress.items.some(
      (item) => item.state === "pending" || item.state === "uploading",
    );
  }

  function cancelUploadAtIndex(index: number): void {
    canceledUploadIndexesRef.current.add(index);
    const controller = uploadControllersRef.current.get(index);
    if (controller) {
      controller.abort("upload-canceled-by-user");
    }

    setUploadProgress((previous) => {
      if (!previous || !previous.items[index]) {
        return previous;
      }

      const nextItems = updateUploadProgressItem(
        previous.items,
        index,
        "canceled",
        "Upload canceled by user.",
      );

      return {
        ...previous,
        items: nextItems,
      };
    });

    setUploadFeedback({
      state: "canceled",
      message: "Upload canceled by user.",
    });
  }

  function cancelAllUploads(): void {
    cancelAllUploadsRequestedRef.current = true;
    for (const controller of uploadControllersRef.current.values()) {
      controller.abort("upload-queue-canceled");
    }
    uploadControllersRef.current.clear();

    setUploadProgress((previous) => {
      if (!previous) {
        return previous;
      }

      const nextItems = previous.items.map((item, index) => {
        if (item.state === "pending" || item.state === "uploading") {
          canceledUploadIndexesRef.current.add(index);
          return {
            ...item,
            state: "canceled" as const,
            message: "Upload canceled by user.",
          };
        }
        return item;
      });

      return {
        ...previous,
        items: nextItems,
      };
    });

    setUploadFeedback({
      state: "canceled",
      message: "Upload queue canceled by user.",
    });
  }

  function handleUploadModalClose(): void {
    if (hasCancelableUploads(uploadProgress) || isUploading) {
      cancelAllUploads();
    }
    setIsUploadModalOpen(false);
  }

  async function handleFileUpload(files: File[]): Promise<void> {
    setActionFeedback(null);
    setActionRequestId(null);

    if (files.length === 0) {
      return;
    }

    uploadControllersRef.current.clear();
    canceledUploadIndexesRef.current.clear();
    cancelAllUploadsRequestedRef.current = false;

    const initialItems: UploadProgressItem[] = files.map((file) => ({
      fileName: file.name,
      state: "pending",
      message: null,
      requestId: null,
    }));

    let completed = 0;
    let successCount = 0;
    let failedCount = 0;
    let canceledCount = 0;
    let latestSuccessDocumentId: string | null = null;
    let lastRequestId: string | null = null;
    let lastFailureMessage: string | null = null;
    let progressItems = initialItems;

    setIsUploading(true);
    setUploadProgress({
      total: files.length,
      completed,
      currentFileName: files[0]?.name ?? null,
      items: progressItems,
    });
    setUploadFeedback({
      state: "uploading",
      message: `Starting upload queue for ${files.length} file(s).`,
    });

    for (const [index, file] of files.entries()) {
      if (
        cancelAllUploadsRequestedRef.current ||
        canceledUploadIndexesRef.current.has(index)
      ) {
        canceledCount += 1;
        completed += 1;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "canceled",
          "Upload canceled by user.",
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        continue;
      }

      const validationError = validateUploadFile(file, MAX_UPLOAD_SIZE_MB);
      if (validationError) {
        failedCount += 1;
        completed += 1;
        lastFailureMessage = validationError;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "failed",
          validationError,
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        setUploadFeedback({
          state: "failed",
          message: validationError,
        });
        continue;
      }

      const uploadController = new AbortController();
      uploadControllersRef.current.set(index, uploadController);
      progressItems = updateUploadProgressItem(
        progressItems,
        index,
        "uploading",
      );
      setUploadProgress({
        total: files.length,
        completed,
        currentFileName: file.name,
        items: progressItems,
      });
      setUploadFeedback({
        state: "uploading",
        message: `Uploading ${index + 1}/${files.length}: ${file.name}`,
      });

      try {
        const result = await uploadDocument(file, uploadController.signal);
        uploadControllersRef.current.delete(index);

        if (canceledUploadIndexesRef.current.has(index)) {
          canceledCount += 1;
          completed += 1;
          progressItems = updateUploadProgressItem(
            progressItems,
            index,
            "canceled",
            "Upload canceled by user.",
          );
          setUploadProgress({
            total: files.length,
            completed,
            currentFileName: files[index + 1]?.name ?? null,
            items: progressItems,
          });
          continue;
        }

        successCount += 1;
        latestSuccessDocumentId = result.document_id;
        completed += 1;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "queued",
          result.message,
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        setUploadFeedback({
          state: "queued",
          message: `Queued ${result.filename} (${completed}/${files.length}).`,
        });
      } catch (error) {
        uploadControllersRef.current.delete(index);
        const canceled =
          canceledUploadIndexesRef.current.has(index) ||
          uploadController.signal.aborted ||
          isAbortError(error);

        if (canceled) {
          canceledCount += 1;
          completed += 1;
          progressItems = updateUploadProgressItem(
            progressItems,
            index,
            "canceled",
            "Upload canceled by user.",
          );
          setUploadProgress({
            total: files.length,
            completed,
            currentFileName: files[index + 1]?.name ?? null,
            items: progressItems,
          });
          continue;
        }

        failedCount += 1;
        completed += 1;
        const errorMessage = getApiErrorMessage(error);
        const requestId = extractRequestIdFromError(error);
        lastRequestId = requestId;
        lastFailureMessage = errorMessage;
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          "failed",
          errorMessage,
          requestId,
        );
        setUploadProgress({
          total: files.length,
          completed,
          currentFileName: files[index + 1]?.name ?? null,
          items: progressItems,
        });
        setUploadFeedback({
          state: "failed",
          message: errorMessage,
          requestId,
        });
      }
    }

    uploadControllersRef.current.clear();
    cancelAllUploadsRequestedRef.current = false;

    if (successCount > 0) {
      setSelectedDocumentId(latestSuccessDocumentId);
      setChunksOffset(0);
      await invalidateAfterMutation(queryClient, "document.upload");
    }

    setIsUploading(false);
    setUploadProgress((previous) =>
      previous
        ? {
            ...previous,
            completed: files.length,
            currentFileName: null,
            items: previous.items,
          }
        : previous,
    );

    if (successCount > 0 && failedCount === 0 && canceledCount === 0) {
      setUploadFeedback({
        state: "success",
        message: `Uploaded ${successCount}/${files.length} file(s). Processing has been queued.`,
      });
      return;
    }

    if (successCount > 0) {
      const remainder: string[] = [];
      if (failedCount > 0) {
        remainder.push(`${failedCount} file(s) failed`);
      }
      if (canceledCount > 0) {
        remainder.push(`${canceledCount} file(s) canceled`);
      }
      setUploadFeedback({
        state: "queued",
        message: `Uploaded ${successCount}/${files.length} file(s); ${remainder.join(" and ")}.`,
        requestId: lastRequestId,
      });
      return;
    }

    if (failedCount === 0 && canceledCount > 0) {
      setUploadFeedback({
        state: "canceled",
        message: `Canceled ${canceledCount}/${files.length} file(s).`,
      });
      return;
    }

    setUploadFeedback({
      state: "failed",
      message:
        files.length === 1 && lastFailureMessage
          ? lastFailureMessage
          : `Upload failed for all ${files.length} file(s).`,
      requestId: lastRequestId,
    });
  }

  function handlePageUploadDragOver(event: DragEvent<HTMLButtonElement>): void {
    event.preventDefault();
    event.stopPropagation();
    if (!capabilities.canUpload || isUploading) {
      return;
    }
    setIsPageDropActive(true);
  }

  function handlePageUploadDragLeave(
    event: DragEvent<HTMLButtonElement>,
  ): void {
    event.preventDefault();
    event.stopPropagation();
    setIsPageDropActive(false);
  }

  async function handlePageUploadDrop(
    event: DragEvent<HTMLButtonElement>,
  ): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    setIsPageDropActive(false);

    if (!capabilities.canUpload || isUploading) {
      return;
    }

    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length === 0) {
      return;
    }

    setIsUploadModalOpen(true);
    await handleFileUpload(files);
  }

  const totalDocumentsCount = documentsQuery.data?.total ?? documents.length;
  const uploadedVisibleCount = documents.filter(
    (document) => document.status === "uploaded",
  ).length;
  const indexedVisibleCount = documents.filter(
    (document) => document.status === "indexed",
  ).length;
  const processingVisibleCount = documents.filter(
    (document) => document.status === "processing",
  ).length;
  const failedVisibleCount = documents.filter(
    (document) => document.status === "failed",
  ).length;
  const allDocumentsStatusCount =
    indexingStatusQuery.data?.total ?? totalDocumentsCount;
  const indexedStatusCount =
    indexingStatusQuery.data?.indexed ?? indexedVisibleCount;
  const processingStatusCount =
    indexingStatusQuery.data?.processing ?? processingVisibleCount;
  const failedStatusCount =
    indexingStatusQuery.data?.failed ?? failedVisibleCount;
  const uploadedStatusCount =
    indexingStatusQuery.data?.uploaded ?? uploadedVisibleCount;
  const reindexAllEligibleCount = uploadedStatusCount + failedStatusCount;
  const indexedUsagePercent =
    allDocumentsStatusCount === 0
      ? 0
      : Math.min(
          100,
          Math.round((indexedStatusCount / allDocumentsStatusCount) * 100),
        );
  const currentPage = Math.floor(offset / DOCUMENT_PAGE_SIZE) + 1;
  const totalPages = Math.max(
    1,
    Math.ceil(Math.max(totalDocumentsCount, 1) / DOCUMENT_PAGE_SIZE),
  );
  const paginationItems = buildPaginationItems(currentPage, totalPages);

  return (
    <section className="space-y-6 bg-white px-4 py-5 lg:px-8 lg:py-8">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {!capabilities.canUpload ? (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-wide text-slate-600 uppercase">
            Read-only role
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setIsUploadModalOpen(true)}
          disabled={isUploading}
          className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white transition-all hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          Open upload modal
        </button>
      </div>

      <section className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-3">
        <button
          type="button"
          disabled={!capabilities.canUpload}
          onClick={() => setIsUploadModalOpen(true)}
          onDragOver={handlePageUploadDragOver}
          onDragLeave={handlePageUploadDragLeave}
          onDrop={(event) => {
            void handlePageUploadDrop(event);
          }}
          className={`group rounded-xl border-2 border-dashed p-6 text-center transition-all disabled:cursor-not-allowed disabled:opacity-60 md:col-span-2 ${
            isPageDropActive
              ? "border-[#3525cd] bg-[#f1efff]"
              : "border-[#3525cd]/20 bg-white hover:border-[#3525cd] hover:bg-[#3525cd]/[0.02]"
          }`}
        >
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-[#3525cd]/10 transition-transform group-hover:scale-110">
            <span className="material-symbols-outlined text-3xl text-[#3525cd]">
              {isPageDropActive ? "upload_file" : "cloud_upload"}
            </span>
          </div>
          <h2 className="text-xl font-semibold text-[#1b1b24]">
            Upload Documents
          </h2>
          <p className="mx-auto mt-1 max-w-xl text-sm text-[#68647b]">
            Drag and drop your files here, or click to browse. We support{" "}
            {ACCEPTED_UPLOAD_TYPES_LABEL} with a max size of{" "}
            {MAX_UPLOAD_SIZE_MB} MB per file.
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              PDF
            </span>
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              DOCX
            </span>
            <span className="rounded-full border border-[#e5e3f1] bg-[#f8f7ff] px-3 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b75] uppercase">
              TXT
            </span>
          </div>
        </button>

        <aside className="relative overflow-hidden rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm">
          <p className="mb-3 text-xs font-bold tracking-[0.08em] text-[#3525cd] uppercase">
            Indexing Status
          </p>
          <div className="space-y-3">
            <div className="flex items-end justify-between">
              <span className="text-sm text-[#68647b]">Total Files</span>
              <span className="text-2xl font-bold text-[#1b1b24]">
                {allDocumentsStatusCount.toLocaleString()}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[#efecf9]">
              <div
                className="h-full bg-[#3525cd] transition-all"
                style={{ width: `${indexedUsagePercent}%` }}
              />
            </div>
            <p className="text-xs text-[#68647b]">
              Indexed: {indexedStatusCount} • Processing:{" "}
              {processingStatusCount} • Failed: {failedStatusCount}
            </p>
            <button
              type="button"
              onClick={() => {
                void handleReindexAllNonIndexedDocuments();
              }}
              disabled={
                !capabilities.canReindex ||
                reindexMutation.isPending ||
                isReindexAllPending ||
                reindexAllEligibleCount <= 0
              }
              className="w-full rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isReindexAllPending ? "Queueing all..." : "Re-index All"}
            </button>
          </div>
        </aside>
      </section>

      {uploadFeedback ? (
        <p
          role="status"
          className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
        >
          Last upload state:{" "}
          <span className="font-semibold uppercase">
            {uploadFeedback.state}
          </span>{" "}
          — {uploadFeedback.message}
          {uploadFeedback.requestId
            ? ` (Trace ID: ${uploadFeedback.requestId})`
            : ""}
        </p>
      ) : null}

      <section className="space-y-4 rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-[#e5e3f1] bg-[#fcfbff] p-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Search
              <div className="relative">
                <span className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-base text-[#9993b8]">
                  search
                </span>
                <input
                  type="search"
                  value={filenameSearch}
                  onChange={(event) => setFilenameSearch(event.target.value)}
                  placeholder="Search filenames…"
                  className="h-9 w-44 rounded-lg border border-[#d2cee6] bg-white pl-8 pr-3 text-sm font-medium text-[#2a2640] placeholder:font-normal placeholder:text-[#b0abc8] outline-none transition-[width] duration-200 focus:w-64 focus:ring-2 focus:ring-[#3525cd]/20"
                />
              </div>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Type
              <select
                value={fileTypeFilter}
                onChange={(event) => {
                  setOffset(0);
                  setFileTypeFilter(event.target.value as FileTypeFilter);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {fileTypeFilterOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Status
              <select
                value={statusFilter}
                onChange={(event) => {
                  setOffset(0);
                  setStatusFilter(event.target.value as StatusFilter);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {statusFilterOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Sort
              <select
                value={sortBy}
                onChange={(event) => {
                  setOffset(0);
                  setSortBy(event.target.value as DocumentSortBy);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                {sortByOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Order
              <select
                value={sortOrder}
                onChange={(event) => {
                  setOffset(0);
                  setSortOrder(event.target.value as SortOrder);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                <option value="desc">Desc</option>
                <option value="asc">Asc</option>
              </select>
            </label>
          </div>
          <p className="text-sm text-[#68647b]">
            Showing{" "}
            <span className="font-semibold text-[#1b1b24]">
              {documents.length}
            </span>{" "}
            of{" "}
            <span className="font-semibold text-[#1b1b24]">
              {totalDocumentsCount}
            </span>{" "}
            documents
          </p>
        </div>

        {actionFeedback ? (
          <p
            role="status"
            className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
          >
            {actionFeedback}
            {actionRequestId ? ` (Trace ID: ${actionRequestId})` : ""}
          </p>
        ) : null}

        {documentsQuery.isLoading ? (
          <LoadingState title="Loading documents..." />
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
          <ErrorState
            error={documentsQuery.error}
            description={getApiErrorMessage(documentsQuery.error)}
            onRetry={() => {
              void documentsQuery.refetch();
            }}
          />
        ) : null}

        {!documentsQuery.isLoading &&
        !documentsQuery.isError &&
        documents.length === 0 ? (
          <EmptyState
            title="No documents found"
            description={
              debouncedFilenameSearch
                ? `No documents match "${debouncedFilenameSearch}".`
                : `Upload your first ${ACCEPTED_UPLOAD_TYPES_LABEL} file to start indexing and retrieval.`
            }
            action={
              debouncedFilenameSearch ? (
                <button
                  type="button"
                  onClick={() => setFilenameSearch("")}
                  className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                >
                  Clear search
                </button>
              ) : capabilities.canUpload ? (
                <button
                  type="button"
                  onClick={() => setIsUploadModalOpen(true)}
                  className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                >
                  Upload document
                </button>
              ) : (
                <p className="text-xs text-[#6a6780]">
                  Your role cannot upload new documents.
                </p>
              )
            }
          />
        ) : null}

        {!documentsQuery.isLoading &&
        !documentsQuery.isError &&
        documents.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-[#e5e3f1]">
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse bg-white text-left">
                <thead className="border-b border-[#e5e3f1] bg-[#f8f7ff]">
                  <tr className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                    <th className="px-4 py-3">Filename</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-center">Pages</th>
                    <th className="px-4 py-3 text-center">Chunks</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3">Updated</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#ece9f6]">
                  {documents.map((document) => {
                    const deleteEnabled =
                      capabilities.canDelete &&
                      canDeleteDocument(document.status);
                    const reindexEnabled =
                      capabilities.canReindex &&
                      canReindexDocument(document.status);
                    const downloadEnabled =
                      document.status !== "deleted" &&
                      document.status !== "deleting";
                    const deleteBusy =
                      pendingDeleteDocumentId === document.document_id;
                    const reindexBusy =
                      pendingReindexDocumentId === document.document_id;
                    const downloadBusy =
                      pendingDownloadDocumentId === document.document_id;

                    return (
                      <tr
                        key={document.document_id}
                        className="group align-top transition-colors hover:bg-[#faf9ff]"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <span
                              className={`material-symbols-outlined ${documentTypeIconClass(document.file_type)}`}
                            >
                              {documentTypeIcon(document.file_type)}
                            </span>
                            <div>
                              <p className="font-semibold text-[#1b1b24]">
                                {document.filename}
                              </p>
                              <p className="text-xs text-[#7a768f]">
                                {document.document_id}
                              </p>
                              {document.error_message ? (
                                <p className="mt-1 text-xs text-rose-700">
                                  {document.error_message}
                                </p>
                              ) : null}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm font-medium text-[#505f76] uppercase">
                          {document.file_type}
                        </td>
                        <td className="px-4 py-3">
                          <span className={statusBadge(document.status)}>
                            {document.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
                          {document.page_count ?? "-"}
                        </td>
                        <td className="px-4 py-3 text-center font-mono text-sm text-[#1b1b24]">
                          {document.chunk_count}
                        </td>
                        <td className="px-4 py-3 text-sm text-[#68647b]">
                          {formatDate(document.created_at)}
                        </td>
                        <td className="px-4 py-3 text-sm text-[#68647b]">
                          {formatDate(document.updated_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-1 opacity-40 transition-opacity group-hover:opacity-100">
                            <button
                              type="button"
                              aria-label="Inspect"
                              onClick={() => {
                                setSelectedDocumentId(document.document_id);
                                setChunksOffset(0);
                                setActionFeedback(null);
                                setActionRequestId(null);
                              }}
                              className="rounded p-1 text-[#3525cd] hover:bg-[#3525cd]/10"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                visibility
                              </span>
                            </button>
                            <Link
                              aria-label="View detail"
                              href={`/documents/${encodeURIComponent(document.document_id)}?back=${encodeURIComponent(currentListHref)}`}
                              className="rounded p-1 text-[#3525cd] hover:bg-[#3525cd]/10"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                open_in_new
                              </span>
                            </Link>
                            <button
                              type="button"
                              aria-label="Download"
                              disabled={!downloadEnabled || downloadBusy}
                              onClick={() => {
                                downloadMutation.mutate({
                                  documentId: document.document_id,
                                  filename: document.filename,
                                });
                              }}
                              className="rounded p-1 text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                download
                              </span>
                            </button>
                            <button
                              type="button"
                              aria-label="Re-index"
                              disabled={!reindexEnabled || reindexBusy}
                              onClick={() => {
                                reindexMutation.mutate(document.document_id);
                              }}
                              className="rounded p-1 text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                refresh
                              </span>
                            </button>
                            <button
                              type="button"
                              aria-label="Delete"
                              disabled={!deleteEnabled || deleteBusy}
                              onClick={() => {
                                const confirmed = window.confirm(
                                  `Delete document \"${document.filename}\"? This action cannot be undone.`,
                                );
                                if (!confirmed) {
                                  return;
                                }
                                deleteMutation.mutate(document.document_id);
                              }}
                              className="rounded p-1 text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                delete
                              </span>
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e5e3f1] bg-[#fcfbff] px-4 py-3">
              <button
                type="button"
                aria-label="Previous"
                disabled={!canGoPrevDocuments}
                onClick={() =>
                  setOffset((current) =>
                    Math.max(0, current - DOCUMENT_PAGE_SIZE),
                  )
                }
                className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-[18px]"
                >
                  chevron_left
                </span>
                Previous
              </button>
              <div className="flex items-center gap-1 text-sm">
                {paginationItems.map((item, index) =>
                  item === null ? (
                    <span
                      key={`ellipsis-${index}`}
                      className="px-2 text-[#6a6780]"
                    >
                      ...
                    </span>
                  ) : (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setOffset((item - 1) * DOCUMENT_PAGE_SIZE)}
                      className={`rounded px-2 py-1 ${
                        currentPage === item
                          ? "bg-[#3525cd] text-white"
                          : "text-[#1b1b24] hover:bg-[#f1eff9]"
                      }`}
                    >
                      {item}
                    </button>
                  ),
                )}
              </div>
              <button
                type="button"
                aria-label="Next"
                disabled={!canGoNextDocuments}
                onClick={() =>
                  setOffset((current) => current + DOCUMENT_PAGE_SIZE)
                }
                className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Next
                <span
                  aria-hidden="true"
                  className="material-symbols-outlined text-[18px]"
                >
                  chevron_right
                </span>
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <article className="relative overflow-hidden rounded-xl bg-gradient-to-br from-[#3525cd] to-[#4f46e5] p-6 text-white shadow-lg md:col-span-3">
          <div className="relative z-10 flex flex-col justify-between gap-4 md:flex-row md:items-center">
            <div className="max-w-2xl">
              <h2 className="text-2xl font-bold">
                Maximize Retrieval Accuracy
              </h2>
              <p className="mt-1 text-sm text-white/90">
                Break large files into optimized chunks and keep overlap at
                10-15% for high-fidelity retrieval quality across support and
                engineering workflows.
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg bg-white px-4 py-2 text-sm font-bold text-[#3525cd] shadow-md transition-transform hover:scale-105"
            >
              Optimize Settings
            </button>
          </div>
          <span className="material-symbols-outlined pointer-events-none absolute -top-8 -right-8 text-[180px] text-white/15">
            architecture
          </span>
        </article>
        <aside className="rounded-xl border border-[#e5e3f1] bg-white p-4 text-center shadow-sm">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#3525cd]/10">
            <span className="material-symbols-outlined text-[#3525cd]">
              history
            </span>
          </div>
          <p className="text-[10px] font-semibold tracking-[0.08em] text-[#6a6780] uppercase">
            Last Activity
          </p>
          <p className="mt-1 text-sm font-semibold text-[#1b1b24]">
            {totalDocumentsCount > 0
              ? "Recent upload available"
              : "No recent uploads"}
          </p>
          <p className="text-xs text-[#68647b]">
            {documents[0]
              ? `Updated ${formatDate(documents[0].updated_at)}`
              : "Upload a document to start"}
          </p>
        </aside>
      </section>

      {selectedDocumentId ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-bold text-[#2a2640]">
              Document detail
            </h2>
            <button
              type="button"
              onClick={() => setSelectedDocumentId(null)}
              className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f]"
            >
              Close
            </button>
          </div>

          {detailQuery.isLoading ? (
            <LoadingState title="Loading document details..." />
          ) : null}

          {(detailQuery.isError || statusQuery.isError) && detailForbidden ? (
            <ForbiddenState
              compact
              title="Document detail access denied"
              description="You do not have permission to inspect this document."
              requestId={extractRequestIdFromError(
                detailQuery.error ?? statusQuery.error,
              )}
            />
          ) : null}

          {detailQuery.isError && !detailForbidden ? (
            <ErrorState
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
            />
          ) : null}

          {selectedDetail ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard label="Filename" value={selectedDetail.filename} />
                <MetricCard
                  label="Type"
                  value={selectedDetail.file_type.toUpperCase()}
                />
                <MetricCard
                  label="Status"
                  value={deriveDetailStatus(selectedDetail, selectedStatus)}
                  valueClass={statusBadge(
                    deriveDetailStatus(selectedDetail, selectedStatus),
                  )}
                  plain={false}
                />
                <MetricCard
                  label="Updated"
                  value={formatDate(selectedDetail.updated_at)}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard
                  label="Pages"
                  value={selectedDetail.page_count ?? "-"}
                />
                <MetricCard label="Chunks" value={selectedDetail.chunk_count} />
                <MetricCard
                  label="Checksum"
                  value={selectedDetail.checksum ?? "-"}
                  mono
                />
              </div>

              {selectedDetail.error_message ? (
                <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  {selectedDetail.error_message}
                </p>
              ) : null}

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h3 className="text-base font-bold text-[#2a2640]">
                    Chunk previews
                  </h3>
                  {chunksQuery.isFetching ? (
                    <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      Refreshing...
                    </span>
                  ) : null}
                </div>

                {chunksQuery.isLoading ? (
                  <LoadingState compact title="Loading chunks..." />
                ) : null}

                {chunksQuery.isError ? (
                  <ErrorState
                    compact
                    error={chunksQuery.error}
                    description={getApiErrorMessage(chunksQuery.error)}
                  />
                ) : null}

                {selectedChunks && selectedChunks.items.length === 0 ? (
                  <EmptyState
                    compact
                    title="No chunks available yet for this document."
                  />
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
                        </div>
                        <p className="text-sm text-[#2a2640]">
                          {chunk.text_preview}
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
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <DocumentsUploadModal
        isOpen={isUploadModalOpen}
        canUpload={capabilities.canUpload}
        isUploading={isUploading}
        acceptedTypesLabel={ACCEPTED_UPLOAD_TYPES_LABEL}
        onRequestClose={handleUploadModalClose}
        onCancelAll={cancelAllUploads}
        onCancelItem={cancelUploadAtIndex}
        onFilesSelected={handleFileUpload}
        feedback={uploadFeedback}
        progress={uploadProgress}
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
