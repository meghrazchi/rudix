"use client";

import { useEffect, useMemo, useState } from "react";

import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import type { DocumentSortBy, SortOrder } from "@/lib/api/documents";
import { getDocument, getDocumentChunks } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { trackActivationEvent, trackFeatureEvent } from "@/lib/analytics";
import {
  canDeleteDocument,
  resolveDocumentCapabilities,
} from "@/lib/documents-ui";
import { isForbiddenError } from "@/lib/forbidden";
import { useDocumentStatusPolling } from "@/lib/use-document-status-polling";
import { useAuthSession } from "@/lib/use-auth-session";

import {
  CHUNK_PAGE_SIZE,
  DOCUMENT_PAGE_SIZE,
  buildPaginationItems,
  parseFreshnessFilter,
  parseOffset,
  parseQualityFilter,
  parseSortBy,
  parseSortOrder,
  parseStatusFilter,
  type FileTypeFilter,
  type FreshnessFilter,
  type QualityFilter,
  type StatusFilter,
} from "@/components/documents/list/documents-list-format";
import { useAssignCollections } from "@/components/documents/list/useAssignCollections";
import { useDocumentRowMutations } from "@/components/documents/list/useDocumentRowMutations";
import { useDocumentUploads } from "@/components/documents/list/useDocumentUploads";
import { useDocumentsFilterOptions } from "@/components/documents/list/useDocumentsFilterOptions";
import { useDocumentsList } from "@/components/documents/list/useDocumentsList";
import { useIndexingStatusSummary } from "@/components/documents/list/useIndexingStatusSummary";
import { useReindexAll } from "@/components/documents/list/useReindexAll";

/** State, queries, and actions of the documents page. */
export function useDocumentsPage() {
  const tp = useTranslations("documents.page");
  const filterOptions = useDocumentsFilterOptions();

  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const capabilities = resolveDocumentCapabilities(state.session?.role);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() =>
    parseStatusFilter(searchParams.get("status")),
  );
  const [freshnessFilter, setFreshnessFilter] = useState<FreshnessFilter>(() =>
    parseFreshnessFilter(searchParams.get("freshness")),
  );
  const [qualityFilter, setQualityFilter] = useState<QualityFilter>(() =>
    parseQualityFilter(searchParams.get("quality_state")),
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
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [filenameSearch, setFilenameSearch] = useState("");
  const [debouncedFilenameSearch, setDebouncedFilenameSearch] = useState("");
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>("all");
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
      freshness: freshnessFilter === "all" ? undefined : freshnessFilter,
      quality_state: qualityFilter === "all" ? undefined : qualityFilter,
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
      freshnessFilter,
      qualityFilter,
      fileTypeFilter,
      debouncedFilenameSearch,
    ],
  );

  const documentsList = useDocumentsList(listQueryOptions);
  const { documentsQuery, cursorMode } = documentsList;
  const indexingStatusQuery = useIndexingStatusSummary();

  const {
    deleteMutation,
    bulkDeleteMutation,
    reindexMutation,
    downloadMutation,
  } = useDocumentRowMutations({
    tp,
    selectedDocumentId,
    setSelectedDocumentId,
    setSelectedIds,
    setActionFeedback,
    setActionRequestId,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.documents.detail(selectedDocumentId ?? ""),
    queryFn: () => getDocument(selectedDocumentId ?? ""),
    enabled: Boolean(selectedDocumentId),
  });

  const statusQuery = useDocumentStatusPolling(selectedDocumentId, {
    enabled: Boolean(selectedDocumentId),
    initialStatus: detailQuery.data?.status ?? null,
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

  const uploads = useDocumentUploads({
    tp,
    capabilities,
    setSelectedDocumentId,
    setChunksOffset,
    setActionFeedback,
    setActionRequestId,
  });
  const assign = useAssignCollections({
    tp,
    isUploadModalOpen: uploads.isUploadModalOpen,
    setActionFeedback,
    setActionRequestId,
  });
  const reindexAll = useReindexAll({
    tp,
    capabilities,
    setSelectedDocumentId,
    setActionFeedback,
    setActionRequestId,
  });

  const documents = documentsList.documents;
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
    offset + DOCUMENT_PAGE_SIZE < (documentsList.total ?? 0),
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
    if (freshnessFilter !== "all") {
      params.set("freshness", freshnessFilter);
    }
    if (qualityFilter !== "all") {
      params.set("quality_state", qualityFilter);
    }
    params.set("sort_by", sortBy);
    params.set("sort_order", sortOrder);
    if (offset > 0 && !cursorMode) {
      params.set("offset", String(offset));
    }
    const serialized = params.toString();
    return serialized ? `/documents?${serialized}` : "/documents";
  }, [
    offset,
    cursorMode,
    sortBy,
    sortOrder,
    statusFilter,
    freshnessFilter,
    qualityFilter,
  ]);

  const totalDocumentsCount = documentsList.total ?? documents.length;
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

  useEffect(() => {
    if (uploadedStatusCount > 0) {
      void trackFeatureEvent("feature.documents.uploaded", {
        surface: "app",
        route: "/documents",
        pageKey: "documents",
        featureArea: "documents",
        count: uploadedStatusCount,
      });
    }
  }, [uploadedStatusCount]);

  useEffect(() => {
    if (indexedStatusCount > 0) {
      void trackFeatureEvent("feature.documents.indexed", {
        surface: "app",
        route: "/documents",
        pageKey: "documents",
        featureArea: "documents",
        count: indexedStatusCount,
      });
      void trackActivationEvent("activation.first_indexed_document", {
        surface: "app",
        route: "/documents",
        pageKey: "documents",
        featureArea: "documents",
        count: indexedStatusCount,
      });
    }
  }, [indexedStatusCount]);

  const currentPage = Math.floor(offset / DOCUMENT_PAGE_SIZE) + 1;
  const totalPages = Math.max(
    1,
    Math.ceil(Math.max(totalDocumentsCount, 1) / DOCUMENT_PAGE_SIZE),
  );
  const paginationItems = buildPaginationItems(currentPage, totalPages);

  return {
    ...filterOptions,
    ...uploads,
    ...assign,
    ...reindexAll,
    tp,
    capabilities,
    statusFilter,
    setStatusFilter,
    freshnessFilter,
    setFreshnessFilter,
    qualityFilter,
    setQualityFilter,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    offset,
    setOffset,
    selectedDocumentId,
    setSelectedDocumentId,
    chunksOffset,
    setChunksOffset,
    actionFeedback,
    setActionFeedback,
    actionRequestId,
    setActionRequestId,
    filenameSearch,
    setFilenameSearch,
    debouncedFilenameSearch,
    fileTypeFilter,
    setFileTypeFilter,
    selectedIds,
    setSelectedIds,
    deleteModalState,
    setDeleteModalState,
    documentsQuery,
    documentsList,
    cursorMode,
    indexingStatusQuery,
    deleteMutation,
    bulkDeleteMutation,
    reindexMutation,
    downloadMutation,
    detailQuery,
    statusQuery,
    chunksQuery,
    documents,
    selectedDetail,
    selectedStatus,
    selectedChunks,
    listForbidden,
    detailForbidden,
    pendingDeleteDocumentId,
    pendingReindexDocumentId,
    pendingDownloadDocumentId,
    isBulkDeleting,
    selectableDocumentIds,
    allSelectableSelected,
    someSelected,
    canGoPrevDocuments,
    canGoNextDocuments,
    canGoPrevChunks,
    canGoNextChunks,
    currentListHref,
    totalDocumentsCount,
    allDocumentsStatusCount,
    indexedStatusCount,
    processingStatusCount,
    failedStatusCount,
    reindexAllEligibleCount,
    indexedUsagePercent,
    currentPage,
    paginationItems,
  };
}

export type DocumentsPageController = ReturnType<typeof useDocumentsPage>;
