"use client";

import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  DocumentsUploadModal,
  type UploadBatchRecord,
  type UploadFeedbackState,
  type UploadProgressItem,
  type UploadProgressItemState,
  type UploadProgressState,
} from "@/components/documents/DocumentsUploadModal";
import { DeleteConfirmModal } from "@/components/documents/DeleteConfirmModal";
import type { UploadDocumentMetadata } from "@/lib/api/documents";
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
  bulkDeleteDocuments,
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
import { useTranslations } from "next-intl";

import { useAuthSession } from "@/lib/use-auth-session";
import {
  ACCEPTED_UPLOAD_TYPES_LABEL,
  maxUploadSizeMbFromEnv,
  validateUploadFile,
} from "@/components/documents/upload-validation";
import { AssignCollectionsDialog } from "@/components/collections/CollectionsPage";
import {
  getDocumentCollections,
  listCollections,
  setDocumentCollections,
} from "@/lib/api/collections";

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


function parseStatusFilter(value: string | null): StatusFilter {
  if (!value) {
    return "all";
  }
  const supported: DocumentStatus[] = [
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "quarantined",
    "blocked",
    "delete_requested",
    "deleting",
    "deleted",
    "retained_by_policy",
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
  if (status === "quarantined") {
    return "rounded-full bg-orange-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-orange-800";
  }
  if (status === "blocked") {
    return "rounded-full bg-red-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-red-800";
  }
  if (status === "delete_requested") {
    return "rounded-full bg-rose-50 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-600";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  if (status === "deleted") {
    return "rounded-full bg-slate-300 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-800";
  }
  if (status === "retained_by_policy") {
    return "rounded-full bg-yellow-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-yellow-800";
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

function truncateFilename(name: string, maxLen = 28): string {
  if (name.length <= maxLen) return name;
  const extDot = name.lastIndexOf(".");
  const ext = extDot > 0 ? name.slice(extDot) : "";
  const base = extDot > 0 ? name.slice(0, extDot) : name;
  const budget = maxLen - ext.length - 1;
  const startLen = Math.ceil(budget * 0.6);
  const endLen = Math.floor(budget * 0.4);
  return base.slice(0, startLen) + "…" + base.slice(-endLen) + ext;
}

function documentSourceLabel(
  sourceProvider: string | null | undefined,
  sourceProviderLabel: string | null | undefined,
): string | null {
  if (sourceProviderLabel) return sourceProviderLabel;
  if (!sourceProvider) return null;
  const map: Record<string, string> = {
    confluence: "Confluence",
    google_drive: "Google Drive",
    "microsoft-sharepoint-onedrive": "SharePoint / OneDrive",
    notion: "Notion",
    jira: "Jira",
    upload: "Local Upload",
  };
  return map[sourceProvider] ?? sourceProvider.replace(/_/g, " ");
}

function documentSourceIcon(sourceProvider: string | null | undefined): string {
  if (!sourceProvider || sourceProvider === "upload") return "upload_file";
  const map: Record<string, string> = {
    confluence: "integration_instructions",
    google_drive: "add_to_drive",
    "microsoft-sharepoint-onedrive": "cloud",
    notion: "article",
    jira: "bug_report",
  };
  return map[sourceProvider] ?? "cloud_sync";
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
  const tp = useTranslations("documents.page");

  const statusFilterOptions: Array<{ value: StatusFilter; label: string }> = [
    { value: "all", label: tp("statusAll") },
    { value: "uploaded", label: tp("statusUploaded") },
    { value: "processing", label: tp("statusProcessing") },
    { value: "indexed", label: tp("statusIndexed") },
    { value: "failed", label: tp("statusFailed") },
    { value: "quarantined", label: tp("statusQuarantined") },
    { value: "blocked", label: tp("statusBlocked") },
    { value: "delete_requested", label: tp("statusDeleteRequested") },
    { value: "deleting", label: tp("statusDeleting") },
    { value: "deleted", label: tp("statusDeleted") },
    { value: "retained_by_policy", label: tp("statusRetainedByPolicy") },
  ];

  const sortByOptions: Array<{ value: DocumentSortBy; label: string }> = [
    { value: "created_at", label: tp("sortCreated") },
    { value: "updated_at", label: tp("sortUpdated") },
    { value: "filename", label: tp("sortFilename") },
    { value: "status", label: tp("sortStatus") },
  ];

  const fileTypeFilterOptions: Array<{ value: FileTypeFilter; label: string }> = [
    { value: "all", label: tp("typeAll") },
    { value: "pdf", label: tp("typePdf") },
    { value: "docx", label: tp("typeDocx") },
    { value: "txt", label: tp("typeTxt") },
  ];

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
  const [uploadHistory, setUploadHistory] = useState<UploadBatchRecord[]>([]);
  const uploadControllersRef = useRef<Map<number, AbortController>>(new Map());
  const canceledUploadIndexesRef = useRef<Set<number>>(new Set());
  const cancelAllUploadsRequestedRef = useRef(false);
  const currentBatchFilesRef = useRef<File[]>([]);
  const currentBatchMetadataRef = useRef<UploadDocumentMetadata>({});
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [filenameSearch, setFilenameSearch] = useState("");
  const [debouncedFilenameSearch, setDebouncedFilenameSearch] = useState("");
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>("all");
  const [assignDocumentId, setAssignDocumentId] = useState<string | null>(null);
  const [assignDocumentName, setAssignDocumentName] = useState<string>("");
  const [assignSaveError, setAssignSaveError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteModalState, setDeleteModalState] = useState<{
    open: boolean;
    documentId: string | null;
    filenames: string[];
  }>({ open: false, documentId: null, filenames: [] });

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
    [
      offset,
      sortBy,
      sortOrder,
      statusFilter,
      fileTypeFilter,
      debouncedFilenameSearch,
    ],
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
      if (result.status === "retained_by_policy") {
        setActionFeedback(
          `Document is retained by policy${result.hold_reason ? `: ${result.hold_reason}` : "."} Deletion blocked.`,
        );
      } else {
        setActionFeedback(`Deletion requested. Status: ${result.status}.`);
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
        parts.push(`${result.accepted} queued for deletion`);
      if (result.retained > 0)
        parts.push(`${result.retained} retained by policy`);
      if (result.errors > 0) parts.push(`${result.errors} errors`);
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

  const allCollectionsQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "for-upload"],
    queryFn: () => listCollections({ limit: 200 }),
    enabled: isUploadModalOpen,
  });

  const assignCollectionsListQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "for-assign"],
    queryFn: () => listCollections({ limit: 200 }),
    enabled: Boolean(assignDocumentId),
  });

  const docCollectionsQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "doc", assignDocumentId ?? ""],
    queryFn: () => getDocumentCollections(assignDocumentId ?? ""),
    enabled: Boolean(assignDocumentId),
  });

  const assignCollectionsMutation = useMutation({
    mutationFn: (collectionIds: string[]) =>
      setDocumentCollections(assignDocumentId ?? "", collectionIds),
    onSuccess: async () => {
      setAssignDocumentId(null);
      setAssignDocumentName("");
      setAssignSaveError(null);
      setActionFeedback(tp("feedbackCollectionSaved"));
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.document.add");
    },
    onError: (error) => {
      setAssignSaveError(getApiErrorMessage(error));
    },
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
  const isBulkDeleting = bulkDeleteMutation.isPending;

  const selectableDocumentIds = documents
    .filter((d) => canDeleteDocument(d.status))
    .map((d) => d.document_id);
  const allSelectableSelected =
    selectableDocumentIds.length > 0 &&
    selectableDocumentIds.every((id) => selectedIds.has(id));
  const someSelected = selectedIds.size > 0;

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
          tp("feedbackReindexProgress", { current: index + 1, total: orderedTargetIds.length }),
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
          tp("feedbackReindexQueuedWithFailed", { queued: queuedCount, failed: failedCount }),
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

      const cancelMsg = tp("feedbackUploadCanceled");
      const nextItems = updateUploadProgressItem(
        previous.items,
        index,
        "canceled",
        cancelMsg,
      );

      return {
        ...previous,
        items: nextItems,
      };
    });

    setUploadFeedback({
      state: "canceled",
      message: tp("feedbackUploadCanceled"),
    });
  }

  function cancelAllUploads(): void {
    cancelAllUploadsRequestedRef.current = true;
    for (const controller of uploadControllersRef.current.values()) {
      controller.abort("upload-queue-canceled");
    }
    uploadControllersRef.current.clear();

    const cancelMsg = tp("feedbackUploadCanceled");
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
            message: cancelMsg,
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
      message: tp("feedbackUploadQueueCanceled"),
    });
  }

  function handleUploadModalClose(): void {
    if (hasCancelableUploads(uploadProgress) || isUploading) {
      cancelAllUploads();
    }
    setIsUploadModalOpen(false);
  }

  async function handleFileUpload(
    files: File[],
    metadata: UploadDocumentMetadata = {},
  ): Promise<void> {
    setActionFeedback(null);
    setActionRequestId(null);

    if (files.length === 0) {
      return;
    }

    currentBatchFilesRef.current = files;
    currentBatchMetadataRef.current = metadata;
    uploadControllersRef.current.clear();
    canceledUploadIndexesRef.current.clear();
    cancelAllUploadsRequestedRef.current = false;

    const initialItems: UploadProgressItem[] = files.map((file) => ({
      fileName: file.name,
      state: "pending",
      message: null,
      requestId: null,
      canRetry: false,
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
          tp("feedbackUploadCanceled"),
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
        const result = await uploadDocument(
          file,
          metadata,
          uploadController.signal,
        );
        uploadControllersRef.current.delete(index);

        if (canceledUploadIndexesRef.current.has(index)) {
          canceledCount += 1;
          completed += 1;
          progressItems = updateUploadProgressItem(
            progressItems,
            index,
            "canceled",
            tp("feedbackUploadCanceled"),
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
        const uploadedState = result.duplicate_detected
          ? "queued_duplicate"
          : "queued";
        progressItems = updateUploadProgressItem(
          progressItems,
          index,
          uploadedState,
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
            tp("feedbackUploadCanceled"),
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
        progressItems = progressItems.map((item, itemIndex) => {
          if (itemIndex !== index) return item;
          return {
            ...item,
            state: "failed" as const,
            message: errorMessage,
            requestId: requestId ?? item.requestId,
            canRetry: true,
          };
        });
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

    setUploadHistory((prev) => {
      const record: UploadBatchRecord = {
        id: `batch-${Date.now()}`,
        startedAt: new Date().toISOString(),
        total: files.length,
        succeeded: successCount,
        failed: failedCount,
        canceled: canceledCount,
        files: files.map((f) => f.name),
      };
      return [record, ...prev].slice(0, 10);
    });

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

  function handleRetryItem(index: number): void {
    const file = currentBatchFilesRef.current[index];
    if (!file || isUploading) {
      return;
    }

    setUploadProgress((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        completed: Math.max(0, prev.completed - 1),
        total: prev.total,
        items: prev.items.map((item, i) => {
          if (i !== index) return item;
          return {
            ...item,
            state: "pending" as const,
            message: null,
            requestId: null,
            canRetry: false,
          };
        }),
      };
    });

    void (async () => {
      await handleFileUpload([file], currentBatchMetadataRef.current);
    })();
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
    await handleFileUpload(files, {});
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
      {!capabilities.canUpload ? (
        <div className="flex justify-end">
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold tracking-wide text-slate-600 uppercase">
            {tp("readOnlyRole")}
          </span>
        </div>
      ) : null}

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
          className={`group rounded-xl border-2 border-dashed p-6 text-center transition-all disabled:cursor-not-allowed disabled:opacity-60 md:col-span-2 cursor-pointer ${
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
            {tp("uploadTitle")}
          </h2>
          <p className="mx-auto mt-1 max-w-xl text-sm text-[#68647b]">
            {tp("uploadDescription", { types: ACCEPTED_UPLOAD_TYPES_LABEL, maxMb: MAX_UPLOAD_SIZE_MB })}
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
            {tp("indexingStatus")}
          </p>
          <div className="space-y-3">
            <div className="flex items-end justify-between">
              <span className="text-sm text-[#68647b]">{tp("totalFiles")}</span>
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
              {tp("indexedCount", { count: indexedStatusCount })} •{" "}
              {tp("processingCount", { count: processingStatusCount })} •{" "}
              {tp("failedCount", { count: failedStatusCount })}
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
              {isReindexAllPending ? tp("reindexAllQueuing") : tp("reindexAll")}
            </button>
          </div>
        </aside>
      </section>

      {uploadFeedback ? (
        <p
          role="status"
          className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-2 text-sm text-[#3f3778]"
        >
          {tp("lastUploadState")}{" "}
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
              {tp("searchLabel")}
              <div className="relative">
                <span className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-base text-[#9993b8]">
                  search
                </span>
                <input
                  type="search"
                  value={filenameSearch}
                  onChange={(event) => setFilenameSearch(event.target.value)}
                  placeholder={tp("searchPlaceholder")}
                  className="h-9 w-44 rounded-lg border border-[#d2cee6] bg-white pr-3 pl-8 text-sm font-medium text-[#2a2640] transition-[width] duration-200 outline-none placeholder:font-normal placeholder:text-[#b0abc8] focus:w-64 focus:ring-2 focus:ring-[#3525cd]/20"
                />
              </div>
            </label>
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              {tp("typeLabel")}
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
              {tp("statusLabel")}
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
              {tp("sortLabel")}
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
              {tp("orderLabel")}
              <select
                value={sortOrder}
                onChange={(event) => {
                  setOffset(0);
                  setSortOrder(event.target.value as SortOrder);
                }}
                className="h-9 rounded-lg border border-[#d2cee6] bg-white px-2 text-sm font-medium text-[#2a2640] outline-none focus:ring-2 focus:ring-[#3525cd]/20"
              >
                <option value="desc">{tp("orderDesc")}</option>
                <option value="asc">{tp("orderAsc")}</option>
              </select>
            </label>
          </div>
          <p className="text-sm text-[#68647b]">
            {tp("showing", { shown: documents.length, total: totalDocumentsCount })}
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
          <LoadingState title={tp("loading")} />
        ) : null}

        {documentsQuery.isError && listForbidden ? (
          <ForbiddenState
            compact
            title={tp("accessDenied")}
            description={tp("accessDeniedDesc")}
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
            title={tp("noDocumentsFound")}
            description={
              debouncedFilenameSearch
                ? tp("noDocumentsMatch", { query: debouncedFilenameSearch })
                : tp("uploadFirst", { types: ACCEPTED_UPLOAD_TYPES_LABEL })
            }
            action={
              debouncedFilenameSearch ? (
                <button
                  type="button"
                  onClick={() => setFilenameSearch("")}
                  className="rounded-lg border border-[#d2cee6] bg-white px-3 py-2 text-sm font-semibold text-[#2a2640] hover:bg-[#f3f1ff]"
                >
                  {tp("clearSearch")}
                </button>
              ) : capabilities.canUpload ? (
                <button
                  type="button"
                  onClick={() => setIsUploadModalOpen(true)}
                  className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
                >
                  {tp("uploadDocument")}
                </button>
              ) : (
                <p className="text-xs text-[#6a6780]">
                  {tp("roleCannotUpload")}
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
                    {capabilities.canDelete ? (
                      <th className="px-4 py-3">
                        <input
                          type="checkbox"
                          aria-label="Select all"
                          checked={allSelectableSelected}
                          disabled={selectableDocumentIds.length === 0}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedIds(new Set(selectableDocumentIds));
                            } else {
                              setSelectedIds(new Set());
                            }
                          }}
                          className="h-4 w-4 rounded border-[#c9c6dc] text-[#3525cd] accent-[#3525cd]"
                        />
                      </th>
                    ) : null}
                    <th className="px-4 py-3">{tp("tableFilename")}</th>
                    <th className="px-4 py-3">{tp("tableSource")}</th>
                    <th className="px-4 py-3">{tp("tableType")}</th>
                    <th className="px-4 py-3">{tp("tableStatus")}</th>
                    <th className="px-4 py-3 text-center">{tp("tablePages")}</th>
                    <th className="px-4 py-3 text-center">{tp("tableChunks")}</th>
                    <th className="px-4 py-3">{tp("tableCreated")}</th>
                    <th className="px-4 py-3">{tp("tableUpdated")}</th>
                    <th className="px-4 py-3 text-right">{tp("tableActions")}</th>
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
                        {capabilities.canDelete ? (
                          <td className="px-4 py-3">
                            <input
                              type="checkbox"
                              aria-label={`Select ${document.filename}`}
                              checked={selectedIds.has(document.document_id)}
                              disabled={!canDeleteDocument(document.status)}
                              onChange={(e) => {
                                setSelectedIds((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) {
                                    next.add(document.document_id);
                                  } else {
                                    next.delete(document.document_id);
                                  }
                                  return next;
                                });
                              }}
                              className="h-4 w-4 rounded border-[#c9c6dc] text-[#3525cd] accent-[#3525cd] disabled:opacity-40"
                            />
                          </td>
                        ) : null}
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <span
                              className={`material-symbols-outlined ${documentTypeIconClass(document.file_type)}`}
                            >
                              {documentTypeIcon(document.file_type)}
                            </span>
                            <div>
                              <p
                                className="font-semibold text-[#1b1b24]"
                                title={document.filename}
                              >
                                {truncateFilename(document.filename)}
                              </p>
                              <p className="text-xs text-[#7a768f]">
                                {document.document_id}
                              </p>
                              {document.collections &&
                              document.collections.length > 0 ? (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {document.collections.map((c) => (
                                    <span
                                      key={c.collection_id}
                                      className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-800"
                                    >
                                      {c.name}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                              {document.tags && document.tags.length > 0 ? (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {document.tags.map((tag) => (
                                    <span
                                      key={tag}
                                      className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600"
                                    >
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                              {document.error_message ? (
                                <p className="mt-1 text-xs text-rose-700">
                                  {document.error_message}
                                </p>
                              ) : null}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {(() => {
                            const providerKey = document.source_provider ?? document.source;
                            const label = documentSourceLabel(providerKey, document.source_provider_label);
                            return (
                              <div className="flex items-center gap-1.5">
                                <span className="material-symbols-outlined text-[16px] text-[#6a6780]">
                                  {documentSourceIcon(providerKey)}
                                </span>
                                <span className="whitespace-nowrap text-xs text-[#464555]">
                                  {label ?? "Local Upload"}
                                </span>
                              </div>
                            );
                          })()}
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
                                setDeleteModalState({
                                  open: true,
                                  documentId: document.document_id,
                                  filenames: [document.filename],
                                });
                              }}
                              className="rounded p-1 text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                delete
                              </span>
                            </button>
                            <button
                              type="button"
                              aria-label="Assign collections"
                              title="Assign to collections"
                              onClick={() => {
                                setAssignDocumentId(document.document_id);
                                setAssignDocumentName(document.filename);
                                setAssignSaveError(null);
                              }}
                              className="rounded p-1 text-violet-700 hover:bg-violet-100"
                            >
                              <span className="material-symbols-outlined text-[18px]">
                                folder_open
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

            {someSelected && capabilities.canDelete ? (
              <div className="flex items-center justify-between gap-3 border-t border-rose-100 bg-rose-50 px-4 py-2">
                <p className="text-sm font-semibold text-rose-800">
                  {selectedIds.size === 1
                    ? tp("bulkSelectedSingle", { count: selectedIds.size })
                    : tp("bulkSelectedPlural", { count: selectedIds.size })}
                </p>
                <button
                  type="button"
                  disabled={isBulkDeleting}
                  onClick={() => {
                    const filenames = documents
                      .filter((d) => selectedIds.has(d.document_id))
                      .map((d) => d.filename);
                    setDeleteModalState({
                      open: true,
                      documentId: null,
                      filenames,
                    });
                  }}
                  className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="material-symbols-outlined text-[16px]">
                    delete
                  </span>
                  {tp("deleteSelected", { count: selectedIds.size })}
                </button>
              </div>
            ) : null}

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
                {tp("previous")}
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
                {tp("next")}
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
                {tp("maximize")}
              </h2>
              <p className="mt-1 text-sm text-white/90">
                {tp("maximizeDesc")}
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg bg-white px-4 py-2 text-sm font-bold text-[#3525cd] shadow-md transition-transform hover:scale-105"
            >
              {tp("optimizeSettings")}
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
            {tp("lastActivity")}
          </p>
          <p className="mt-1 text-sm font-semibold text-[#1b1b24]">
            {totalDocumentsCount > 0
              ? tp("recentUpload")
              : tp("noRecentUploads")}
          </p>
          <p className="text-xs text-[#68647b]">
            {documents[0]
              ? tp("updatedDate", { date: formatDate(documents[0].updated_at) })
              : tp("uploadStart")}
          </p>
        </aside>
      </section>

      {selectedDocumentId ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-bold text-[#2a2640]">
              {tp("detailTitle")}
            </h2>
            <button
              type="button"
              onClick={() => setSelectedDocumentId(null)}
              className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f]"
            >
              {tp("close")}
            </button>
          </div>

          {detailQuery.isLoading ? (
            <LoadingState title={tp("loadingDetails")} />
          ) : null}

          {(detailQuery.isError || statusQuery.isError) && detailForbidden ? (
            <ForbiddenState
              compact
              title={tp("detailAccessDenied")}
              description={tp("detailAccessDeniedDesc")}
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
                <MetricCard label={tp("tableFilename")} value={selectedDetail.filename} />
                <MetricCard
                  label={tp("tableType")}
                  value={selectedDetail.file_type.toUpperCase()}
                />
                <MetricCard
                  label={tp("tableStatus")}
                  value={deriveDetailStatus(selectedDetail, selectedStatus)}
                  valueClass={statusBadge(
                    deriveDetailStatus(selectedDetail, selectedStatus),
                  )}
                  plain={false}
                />
                <MetricCard
                  label={tp("tableUpdated")}
                  value={formatDate(selectedDetail.updated_at)}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard
                  label={tp("tablePages")}
                  value={selectedDetail.page_count ?? "-"}
                />
                <MetricCard label={tp("tableChunks")} value={selectedDetail.chunk_count} />
                <MetricCard
                  label={tp("metricChecksum")}
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
                    {tp("chunkPreviews")}
                  </h3>
                  {chunksQuery.isFetching ? (
                    <span className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      {tp("refreshing")}
                    </span>
                  ) : null}
                </div>

                {chunksQuery.isLoading ? (
                  <LoadingState compact title={tp("loadingChunks")} />
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
                    title={tp("noChunksYet")}
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
                          <span>{tp("chunkIndex", { index: chunk.chunk_index })}</span>
                          <span>{tp("chunkPage", { n: chunk.page_number ?? "-" })}</span>
                          <span>{tp("chunkTokens", { n: chunk.token_count })}</span>
                        </div>
                        <p className="text-sm text-[#2a2640]">
                          {chunk.text_preview}
                        </p>
                      </article>
                    ))}
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-xs text-[#6e6a86]">
                        {tp("showingChunks", { shown: selectedChunks.items.length, total: selectedChunks.total })}
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
                          {tp("previous")}
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
                          {tp("next")}
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
        collections={allCollectionsQuery.data?.items ?? []}
        onRequestClose={handleUploadModalClose}
        onCancelAll={cancelAllUploads}
        onCancelItem={cancelUploadAtIndex}
        onRetryItem={handleRetryItem}
        onFilesSelected={handleFileUpload}
        feedback={uploadFeedback}
        progress={uploadProgress}
        uploadHistory={uploadHistory}
      />

      {assignDocumentId ? (
        <AssignCollectionsDialog
          documentName={assignDocumentName}
          collectionList={assignCollectionsListQuery.data?.items ?? []}
          loadingCollections={
            assignCollectionsListQuery.isLoading ||
            docCollectionsQuery.isLoading
          }
          currentCollectionIds={(docCollectionsQuery.data?.items ?? []).map(
            (c) => c.collection_id,
          )}
          saving={assignCollectionsMutation.isPending}
          saveError={assignSaveError}
          onSave={(collectionIds) =>
            assignCollectionsMutation.mutate(collectionIds)
          }
          onClose={() => {
            setAssignDocumentId(null);
            setAssignDocumentName("");
            setAssignSaveError(null);
          }}
        />
      ) : null}

      <DeleteConfirmModal
        open={deleteModalState.open}
        filenames={deleteModalState.filenames}
        onCancel={() =>
          setDeleteModalState({ open: false, documentId: null, filenames: [] })
        }
        onConfirm={() => {
          if (deleteModalState.documentId) {
            deleteMutation.mutate(deleteModalState.documentId);
          } else {
            bulkDeleteMutation.mutate(Array.from(selectedIds));
          }
          setDeleteModalState({ open: false, documentId: null, filenames: [] });
        }}
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
