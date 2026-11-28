"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  addDocumentToCollection,
  getCollection,
  listCollectionDocuments,
  refreshCollectionRules,
  removeDocumentFromCollection,
  type CollectionDocumentItem,
  type CollectionDocumentsResponse,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { useInfiniteList } from "@/lib/pagination/useInfiniteList";

import { fetchAllCollectionDocuments } from "@/components/collections/collection-documents";
import { COLLECTION_DOCS_INITIAL_LIMIT } from "@/components/collections/collection-format";

/** Queries, mutations, and local state of the collection detail drawer. */
export function useCollectionDetailDrawer(collectionId: string) {
  const tc = useTranslations("collections.page");
  const queryClient = useQueryClient();
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [isDocumentPickerOpen, setIsDocumentPickerOpen] = useState(false);
  const [documentSaveError, setDocumentSaveError] = useState<string | null>(
    null,
  );

  const detailQuery = useQuery({
    queryKey: queryKeys.collections.detail(collectionId),
    queryFn: () => getCollection(collectionId),
  });

  // Offset pages with `total` and load more (R07-06).
  const docsList = useInfiniteList<
    CollectionDocumentsResponse,
    CollectionDocumentItem
  >({
    queryKey: queryKeys.collections.documents(collectionId, {
      limit: COLLECTION_DOCS_INITIAL_LIMIT,
      pagination: "offset",
    }),
    pageSize: COLLECTION_DOCS_INITIAL_LIMIT,
    fetchPage: ({ offset }) =>
      listCollectionDocuments(collectionId, {
        limit: COLLECTION_DOCS_INITIAL_LIMIT,
        offset,
      }),
  });
  const docsQuery = docsList.query;

  // Full membership for the document picker's add/remove diff.
  const allCollectionDocsQuery = useQuery({
    queryKey: queryKeys.collectionViews.allDocuments(collectionId),
    queryFn: () => fetchAllCollectionDocuments(collectionId),
  });

  const refreshRulesMutation = useMutation({
    mutationFn: () => refreshCollectionRules(collectionId),
    onSuccess: async (result) => {
      setActionFeedback(
        `Rules refreshed — ${result.matched_count} document${result.matched_count === 1 ? "" : "s"} matched.`,
      );
      await invalidateAfterMutation(queryClient, "collection.rules.refresh");
      await invalidateAfterMutation(queryClient, "collection.document.add");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
    },
  });

  const removeDocMutation = useMutation({
    mutationFn: (documentId: string) =>
      removeDocumentFromCollection(collectionId, documentId),
    onSuccess: async () => {
      setActionFeedback(tc("docRemovedFeedback"));
      await invalidateAfterMutation(queryClient, "collection.document.remove");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
    },
  });

  const manageDocumentsMutation = useMutation({
    mutationFn: async (documentIds: string[]) => {
      const currentDocumentIds = new Set(
        (allCollectionDocsQuery.data?.items ?? []).map(
          (doc) => doc.document_id,
        ),
      );
      const nextDocumentIds = new Set(documentIds);

      const toAdd = Array.from(nextDocumentIds).filter(
        (documentId) => !currentDocumentIds.has(documentId),
      );
      const toRemove = Array.from(currentDocumentIds).filter(
        (documentId) => !nextDocumentIds.has(documentId),
      );

      await Promise.all([
        ...toAdd.map((documentId) =>
          addDocumentToCollection(collectionId, documentId),
        ),
        ...toRemove.map((documentId) =>
          removeDocumentFromCollection(collectionId, documentId),
        ),
      ]);
    },
    onSuccess: async () => {
      setIsDocumentPickerOpen(false);
      setDocumentSaveError(null);
      setActionFeedback(tc("docSavedFeedback"));
      await invalidateAfterMutation(queryClient, "collection.document.add");
      await invalidateAfterMutation(queryClient, "collection.document.remove");
    },
    onError: (error) => {
      setDocumentSaveError(getApiErrorMessage(error));
    },
  });

  const detail = detailQuery.data;
  const docs = docsQuery.data
    ? { items: docsList.items, total: docsList.total ?? docsList.items.length }
    : undefined;
  const progress =
    detail && detail.document_count > 0
      ? Math.round((detail.indexed_count / detail.document_count) * 100)
      : 0;
  const canLoadMore = Boolean(docs) && docsList.hasMore;
  const existingDocumentIds = (allCollectionDocsQuery.data?.items ?? []).map(
    (doc) => doc.document_id,
  );

  const fileIcon = (type: string) =>
    type === "pdf"
      ? "picture_as_pdf"
      : type === "docx"
        ? "article"
        : "description";

  return {
    tc,
    collectionId,
    loadMoreDocs: docsList.loadMore,
    isLoadingMoreDocs: docsList.isLoadingMore,
    actionFeedback,
    isDocumentPickerOpen,
    setIsDocumentPickerOpen,
    documentSaveError,
    setDocumentSaveError,
    detailQuery,
    docsQuery,
    allCollectionDocsQuery,
    refreshRulesMutation,
    removeDocMutation,
    manageDocumentsMutation,
    detail,
    docs,
    progress,
    canLoadMore,
    existingDocumentIds,
    fileIcon,
  };
}

export type CollectionDrawerController = ReturnType<
  typeof useCollectionDetailDrawer
>;
