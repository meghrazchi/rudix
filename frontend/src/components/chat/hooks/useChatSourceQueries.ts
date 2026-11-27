import { useMemo } from "react";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  MAX_INDEXED_DOCS,
  SCOPE_DOCUMENT_PICKER_LIMIT,
  type ChatScopeMode,
} from "@/components/chat/chat-types";
import {
  buildConnectorRootChips,
  getConnectorProviderLabel,
} from "@/components/chat/chat-connectors";
import {
  listCollectionDocuments,
  listCollections,
} from "@/lib/api/collections";
import { listAvailableConnectorConnections } from "@/lib/api/connectors";
import { listDocuments } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";

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

  const documentPickerQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: SCOPE_DOCUMENT_PICKER_LIMIT,
      offset: 0,
      filename_query: documentSearchQuery.trim() || undefined,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: SCOPE_DOCUMENT_PICKER_LIMIT,
        offset: 0,
        filename_query: documentSearchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: keepPreviousData,
  });

  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((doc) => doc.document_id)),
    [indexedDocuments],
  );

  const collectionsListQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "chat-picker"],
    queryFn: () => listCollections({ limit: 200 }),
  });
  const collections = useMemo(
    () => collectionsListQuery.data?.items ?? [],
    [collectionsListQuery.data?.items],
  );

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
      (documentPickerQuery.data?.items ?? []).map((document) => ({
        document_id: document.document_id,
        filename: document.filename,
        chunk_count: document.chunk_count,
        updated_at: document.updated_at ?? null,
      })),
    [documentPickerQuery.data?.items],
  );

  const selectedCollectionDocsQuery = useQuery({
    queryKey: [
      ...queryKeys.collections.all,
      "chat-picker-documents",
      ...selectedCollectionIds.slice().sort(),
    ],
    queryFn: async () => {
      const results = await Promise.all(
        selectedCollectionIds.map((collectionId) =>
          listCollectionDocuments(collectionId, { limit: 200 }),
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
    collectionsListQuery,
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
