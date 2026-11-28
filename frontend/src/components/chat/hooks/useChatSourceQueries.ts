import { useMemo } from "react";

import { useQuery } from "@tanstack/react-query";

import {
  MAX_INDEXED_DOCS,
  SCOPE_DOCUMENT_PICKER_LIMIT,
  type ChatScopeMode,
} from "@/components/chat/chat-types";
import {
  buildConnectorRootChips,
  getConnectorProviderLabel,
} from "@/components/chat/chat-connectors";
import { fetchAllCollectionDocuments } from "@/components/collections/collection-documents";
import { useCollectionSearchList } from "@/components/collections/useCollectionSearchList";
import { listAvailableConnectorConnections } from "@/lib/api/connectors";
import {
  listDocuments,
  type DocumentListItemResponse,
  type DocumentListResponse,
} from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { useInfiniteList } from "@/lib/pagination/useInfiniteList";

export function useChatSourceQueries({
  scopeMode,
  selectedCollectionIds,
  documentSearchQuery,
}: {
  scopeMode: ChatScopeMode;
  selectedCollectionIds: string[];
  documentSearchQuery: string;
}) {
  const indexedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: MAX_INDEXED_DOCS,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: MAX_INDEXED_DOCS,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const indexedDocuments = useMemo(
    () =>
      indexedDocumentsQuery.data?.items.filter(
        (item) => item.status === "indexed",
      ) ?? [],
    [indexedDocumentsQuery.data?.items],
  );

  // Server-side filename search, offset pages with `total`, and load more.
  const documentPicker = useInfiniteList<
    DocumentListResponse,
    DocumentListItemResponse
  >({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: SCOPE_DOCUMENT_PICKER_LIMIT,
      filename_query: documentSearchQuery.trim() || undefined,
      sort_by: "updated_at",
      sort_order: "desc",
      pagination: "offset",
    }),
    pageSize: SCOPE_DOCUMENT_PICKER_LIMIT,
    keepPreviousPages: true,
    fetchPage: ({ offset }) =>
      listDocuments({
        status: "indexed",
        limit: SCOPE_DOCUMENT_PICKER_LIMIT,
        offset,
        filename_query: documentSearchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });
  const documentPickerQuery = documentPicker.query;
  const pickerDocuments = documentPicker.items;

  // Documents picked from any loaded picker page stay valid even when they
  // fall outside the first NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS indexed rows.
  const indexedDocumentIdSet = useMemo(() => {
    const ids = new Set(indexedDocuments.map((doc) => doc.document_id));
    for (const doc of pickerDocuments) {
      if (doc.status === "indexed") {
        ids.add(doc.document_id);
      }
    }
    return ids;
  }, [indexedDocuments, pickerDocuments]);

  // Server-side name search with load more instead of one 200-row page.
  const collectionsSearch = useCollectionSearchList({ scope: "chat-picker" });
  const collectionsListQuery = collectionsSearch.query;
  const collections = collectionsSearch.items;

  const connectorConnectionsQuery = useQuery({
    queryKey: [...queryKeys.connectorConnections, "chat-picker"],
    queryFn: () => listAvailableConnectorConnections(),
  });
  const connectorConnections = useMemo(
    () => connectorConnectionsQuery.data?.items ?? [],
    [connectorConnectionsQuery.data?.items],
  );
  const connectorDocumentCount = useMemo(
    () =>
      connectorConnections.reduce(
        (total, connection) => total + connection.source_count,
        0,
      ),
    [connectorConnections],
  );

  const composerCollections = useMemo(
    () =>
      collections.map((collection) => ({
        collection_id: collection.collection_id,
        name: collection.name,
        description: collection.description ?? null,
      })),
    [collections],
  );

  const composerConnectorConnections = useMemo(
    () =>
      connectorConnections.map((connection) => ({
        id: connection.id,
        display_name: connection.display_name,
        provider_label: getConnectorProviderLabel(connection.provider_key),
        external_account_id: connection.external_account_id ?? null,
        rootChips: buildConnectorRootChips(connection),
      })),
    [connectorConnections],
  );

  const composerIndexedDocuments = useMemo(
    () =>
      pickerDocuments.map((document) => ({
        document_id: document.document_id,
        filename: document.filename,
        chunk_count: document.chunk_count,
        updated_at: document.updated_at ?? null,
      })),
    [pickerDocuments],
  );

  const selectedCollectionDocsQuery = useQuery({
    queryKey: [
      ...queryKeys.collections.all,
      "chat-picker-documents",
      ...selectedCollectionIds.slice().sort(),
    ],
    // Every page of each selected collection, so the scope is never cut at 200.
    queryFn: async () => {
      const results = await Promise.all(
        selectedCollectionIds.map((collectionId) =>
          fetchAllCollectionDocuments(collectionId),
        ),
      );
      return results;
    },
    enabled: scopeMode === "collection" && selectedCollectionIds.length > 0,
  });

  const collectionDocumentIdSet = useMemo(() => {
    if (scopeMode !== "collection" || selectedCollectionIds.length === 0) {
      return null;
    }
    const ids = new Set<string>();
    for (const response of selectedCollectionDocsQuery.data ?? []) {
      for (const doc of response.items ?? []) {
        if (doc.status === "indexed") {
          ids.add(doc.document_id);
        }
      }
    }
    return ids;
  }, [
    scopeMode,
    selectedCollectionIds.length,
    selectedCollectionDocsQuery.data,
  ]);

  const totalIndexedDocuments =
    indexedDocumentsQuery.data?.total ?? indexedDocuments.length;

  return {
    indexedDocumentsQuery,
    indexedDocuments,
    indexedDocumentIdSet,
    documentPickerQuery,
    documentsPaging: {
      total: documentPicker.total,
      hasMore: documentPicker.hasMore,
      isLoadingMore: documentPicker.isLoadingMore,
      onLoadMore: documentPicker.loadMore,
    },
    collectionsListQuery,
    collectionsSearch,
    collectionsPaging: {
      total: collectionsSearch.total,
      hasMore: collectionsSearch.hasMore,
      isLoadingMore: collectionsSearch.isLoadingMore,
      onLoadMore: collectionsSearch.loadMore,
    },
    collections,
    connectorConnectionsQuery,
    connectorConnections,
    connectorDocumentCount,
    composerCollections,
    composerConnectorConnections,
    composerIndexedDocuments,
    selectedCollectionDocsQuery,
    collectionDocumentIdSet,
    totalIndexedDocuments,
  };
}
