import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useTranslations } from "next-intl";

import { useChatSourceQueries } from "@/components/chat/hooks/useChatSourceQueries";
import type { PersistedChatSettings } from "@/components/chat/hooks/useChatSettings";
import type { ChatScopeMode } from "@/components/chat/chat-types";
import type { ChatQueryRequest } from "@/lib/api/chat";

export function useChatScope({
  persistedSettings,
  documentIdFromQuery,
  collectionIdFromQuery,
  connectorIdFromQuery,
  activeOrgId,
}: {
  persistedSettings: PersistedChatSettings | null;
  documentIdFromQuery: string | null;
  collectionIdFromQuery: string | null;
  connectorIdFromQuery: string | null;
  activeOrgId: string | null;
}) {
  const tc = useTranslations("chat.page");
  const lastAppliedDocumentIdFromQueryRef = useRef<string | null>(null);
  const lastAppliedCollectionIdFromQueryRef = useRef<string | null>(null);
  const lastAppliedConnectorIdFromQueryRef = useRef<string | null>(null);
  const [documentSearchQuery, setDocumentSearchQuery] = useState("");

  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>(
    () => persistedSettings?.selectedDocumentIds ?? [],
  );
  const [scopeMode, setScopeMode] = useState<ChatScopeMode>(
    () => persistedSettings?.scopeMode ?? "all",
  );
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>(
    () => persistedSettings?.selectedCollectionIds ?? [],
  );
  const [selectedConnectorConnectionIds, setSelectedConnectorConnectionIds] =
    useState<string[]>(
      () => persistedSettings?.selectedConnectorConnectionIds ?? [],
    );
  const [selectedProviderSourceIds, setSelectedProviderSourceIds] = useState<
    string[]
  >(() => persistedSettings?.selectedProviderSourceIds ?? []);

  const prevOrgIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevOrgIdRef.current === null) {
      prevOrgIdRef.current = activeOrgId;
      return;
    }
    if (activeOrgId !== prevOrgIdRef.current) {
      prevOrgIdRef.current = activeOrgId;
      setScopeMode("all");
      setSelectedCollectionIds([]);
      setSelectedDocumentIds([]);
      setSelectedConnectorConnectionIds([]);
      setSelectedProviderSourceIds([]);
      lastAppliedDocumentIdFromQueryRef.current = null;
      lastAppliedCollectionIdFromQueryRef.current = null;
      lastAppliedConnectorIdFromQueryRef.current = null;
    }
  }, [activeOrgId]);

  const {
    indexedDocumentsQuery,
    indexedDocumentIdSet,
    documentPickerQuery,
    documentsPaging,
    collectionsListQuery,
    collectionsSearch,
    collectionsPaging,
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
  } = useChatSourceQueries({
    scopeMode,
    selectedCollectionIds,
    documentSearchQuery,
  });

  useLayoutEffect(() => {
    if (!documentIdFromQuery) {
      lastAppliedDocumentIdFromQueryRef.current = null;
      return;
    }

    if (!indexedDocumentIdSet.has(documentIdFromQuery)) {
      return;
    }

    if (lastAppliedDocumentIdFromQueryRef.current === documentIdFromQuery) {
      return;
    }

    setScopeMode("documents");
    setSelectedCollectionIds([]);
    setSelectedDocumentIds([documentIdFromQuery]);
    setSelectedConnectorConnectionIds([]);
    setSelectedProviderSourceIds([]);
    lastAppliedDocumentIdFromQueryRef.current = documentIdFromQuery;
  }, [documentIdFromQuery, indexedDocumentIdSet]);

  useLayoutEffect(() => {
    if (!collectionIdFromQuery) {
      lastAppliedCollectionIdFromQueryRef.current = null;
      return;
    }

    if (documentIdFromQuery) {
      return;
    }

    if (lastAppliedCollectionIdFromQueryRef.current === collectionIdFromQuery) {
      return;
    }

    setScopeMode("collection");
    setSelectedDocumentIds([]);
    setSelectedCollectionIds([collectionIdFromQuery]);
    setSelectedConnectorConnectionIds([]);
    setSelectedProviderSourceIds([]);
    lastAppliedCollectionIdFromQueryRef.current = collectionIdFromQuery;
  }, [collectionIdFromQuery, documentIdFromQuery]);

  useLayoutEffect(() => {
    if (!connectorIdFromQuery) {
      lastAppliedConnectorIdFromQueryRef.current = null;
      return;
    }

    if (documentIdFromQuery || collectionIdFromQuery) {
      return;
    }

    if (lastAppliedConnectorIdFromQueryRef.current === connectorIdFromQuery) {
      return;
    }

    setScopeMode("connectors");
    setSelectedCollectionIds([]);
    setSelectedDocumentIds([]);
    setSelectedConnectorConnectionIds([connectorIdFromQuery]);
    setSelectedProviderSourceIds([]);
    lastAppliedConnectorIdFromQueryRef.current = connectorIdFromQuery;
  }, [collectionIdFromQuery, connectorIdFromQuery, documentIdFromQuery]);

  const filteredSelectedDocumentIds = useMemo(() => {
    const validSelectedDocumentIds = selectedDocumentIds.filter((documentId) =>
      indexedDocumentIdSet.has(documentId),
    );
    if (
      documentIdFromQuery &&
      indexedDocumentIdSet.has(documentIdFromQuery) &&
      !validSelectedDocumentIds.includes(documentIdFromQuery)
    ) {
      return [documentIdFromQuery, ...validSelectedDocumentIds];
    }
    return validSelectedDocumentIds;
  }, [documentIdFromQuery, indexedDocumentIdSet, selectedDocumentIds]);

  const hasConnectorScopeSelection =
    selectedConnectorConnectionIds.length > 0 ||
    selectedProviderSourceIds.length > 0;
  const requiresUploadedDocuments =
    scopeMode !== "none" && scopeMode !== "connectors";

  const effectiveDocumentIds = useMemo(() => {
    if (scopeMode === "none") {
      return [];
    }
    if (scopeMode === "collection") {
      if (collectionDocumentIdSet && collectionDocumentIdSet.size > 0) {
        return Array.from(collectionDocumentIdSet);
      }
      return [];
    }
    if (scopeMode === "connectors") {
      return [];
    }
    if (scopeMode === "documents" || scopeMode === "all") {
      return filteredSelectedDocumentIds;
    }
    return [];
  }, [scopeMode, collectionDocumentIdSet, filteredSelectedDocumentIds]);

  const scopeWarning = useMemo<string | null>(() => {
    if (scopeMode === "collection") {
      if (selectedCollectionIds.length === 0)
        return tc("scopeSelectCollectionWarning");
      if (selectedCollectionDocsQuery.isLoading) return null;
      if (
        collectionDocumentIdSet !== null &&
        collectionDocumentIdSet.size === 0
      ) {
        return tc("scopeEmptyCollectionsWarning");
      }
    }
    if (scopeMode === "connectors" && !hasConnectorScopeSelection) {
      return tc("scopeSelectConnectorWarning");
    }
    return null;
  }, [
    scopeMode,
    selectedCollectionIds.length,
    selectedCollectionDocsQuery.isLoading,
    collectionDocumentIdSet,
    hasConnectorScopeSelection,
    tc,
  ]);

  const totalDocumentsInAllScope =
    totalIndexedDocuments + connectorDocumentCount;
  const hasAvailableDocuments = totalDocumentsInAllScope > 0;
  const contextScopeItemCount =
    scopeMode === "collection"
      ? selectedCollectionIds.length
      : scopeMode === "connectors"
        ? selectedConnectorConnectionIds.length +
          selectedProviderSourceIds.length
        : effectiveDocumentIds.length > 0
          ? effectiveDocumentIds.length
          : totalDocumentsInAllScope;

  const isScopeInvalid = scopeWarning !== null;

  function buildScopeLabel(): string {
    if (scopeMode === "none") return tc("scopeNoRetrieval");
    const parts: string[] = [];
    if (scopeMode === "all") {
      if (filteredSelectedDocumentIds.length > 0) {
        parts.push(
          tc("scopeAllDocumentsSelected", {
            n: filteredSelectedDocumentIds.length,
          }),
        );
      } else {
        parts.push(
          tc("scopeAllDocuments", { count: totalDocumentsInAllScope }),
        );
      }
    }
    if (scopeMode === "collection") {
      const collectionCount = selectedCollectionIds.length;
      parts.push(tc("scopeCollectionsSelected", { n: collectionCount }));
    }
    if (scopeMode === "documents") {
      const fileCount = filteredSelectedDocumentIds.length;
      if (fileCount > 0) {
        parts.push(tc("documentsSelected", { count: fileCount }));
      } else {
        parts.push(
          tc("scopeAllDocuments", { count: totalDocumentsInAllScope }),
        );
      }
    }
    if (scopeMode === "connectors") {
      const connectionCount = selectedConnectorConnectionIds.length;
      const sourceCount = selectedProviderSourceIds.length;
      if (connectionCount > 0) {
        parts.push(tc("scopeConnections", { n: connectionCount }));
      }
      if (sourceCount > 0) {
        parts.push(tc("scopeSourceRoots", { n: sourceCount }));
      }
      if (parts.length === 0) {
        parts.push(tc("scopeConnectorDefault"));
      }
    }
    if (parts.length > 0) {
      return parts.join(" · ");
    }
    return tc("scopeAllDocuments", { count: totalDocumentsInAllScope });
  }

  function buildSourceScopePayload(): ChatQueryRequest["source_scope"] | null {
    if (scopeMode === "none") {
      return null;
    }
    if (scopeMode === "connectors") {
      if (!hasConnectorScopeSelection) {
        return null;
      }
      return {
        mode: "connector_sources",
        connection_ids: selectedConnectorConnectionIds,
        provider_source_ids: selectedProviderSourceIds,
      };
    }
    if (scopeMode === "collection" && selectedCollectionIds.length > 0) {
      return {
        mode: "collections",
        collection_ids: selectedCollectionIds,
      };
    }
    return null;
  }

  function toggleCollection(collectionId: string) {
    setSelectedCollectionIds((previous) =>
      previous.includes(collectionId)
        ? previous.filter((value) => value !== collectionId)
        : [...previous, collectionId],
    );
  }

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const validPrevious = previous.filter((value) =>
        indexedDocumentIdSet.has(value),
      );
      if (validPrevious.includes(documentId)) {
        return validPrevious.filter((value) => value !== documentId);
      }
      return [...validPrevious, documentId];
    });
  }

  function toggleConnectorConnection(connectionId: string) {
    setScopeMode("connectors");
    setSelectedConnectorConnectionIds((previous) =>
      previous.includes(connectionId)
        ? previous.filter((value) => value !== connectionId)
        : [...previous, connectionId],
    );
  }

  function toggleProviderSource(providerSourceId: string) {
    setScopeMode("connectors");
    setSelectedProviderSourceIds((previous) =>
      previous.includes(providerSourceId)
        ? previous.filter((value) => value !== providerSourceId)
        : [...previous, providerSourceId],
    );
  }

  function applyScopeMode(mode: ChatScopeMode) {
    setScopeMode(mode);
    if (mode !== "documents") setSelectedDocumentIds([]);
    if (mode !== "collection") setSelectedCollectionIds([]);
    if (mode !== "connectors") {
      setSelectedConnectorConnectionIds([]);
      setSelectedProviderSourceIds([]);
    }
  }

  return {
    scopeMode,
    selectedDocumentIds,
    selectedCollectionIds,
    selectedConnectorConnectionIds,
    selectedProviderSourceIds,
    documentSearchQuery,
    setDocumentSearchQuery,
    indexedDocumentsQuery,
    documentPickerQuery,
    documentsPaging,
    collectionsListQuery,
    collectionsSearch,
    collectionsPaging,
    collections,
    connectorConnectionsQuery,
    connectorConnections,
    composerCollections,
    composerConnectorConnections,
    composerIndexedDocuments,
    totalIndexedDocuments,
    filteredSelectedDocumentIds,
    hasConnectorScopeSelection,
    requiresUploadedDocuments,
    effectiveDocumentIds,
    scopeWarning,
    isScopeInvalid,
    hasAvailableDocuments,
    contextScopeItemCount,
    buildScopeLabel,
    buildSourceScopePayload,
    toggleCollection,
    toggleDocument,
    toggleConnectorConnection,
    toggleProviderSource,
    applyScopeMode,
  };
}

export type ChatScopeController = ReturnType<typeof useChatScope>;
