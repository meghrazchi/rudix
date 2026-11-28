"use client";

import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  createCollection,
  deleteCollection,
  listCollections,
  setCollectionRules,
  updateCollection,
  type CollectionAccessPolicy,
  type CollectionDetailResponse,
  type CollectionListItemResponse,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import {
  extractRequestIdFromError,
  isEndpointNotFoundError,
  isForbiddenError,
} from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { useAuthSession } from "@/lib/use-auth-session";

import type { CollectionFormState } from "@/components/collections/CollectionDialog";
import {
  COLLECTIONS_PAGE_SIZE,
  resolveCollectionCapabilities,
} from "@/components/collections/collection-format";

/** State, list query, and mutations of the collections page. */
export function useCollectionsPage() {
  const tc = useTranslations("collections.page");
  const queryClient = useQueryClient();
  const { state } = useAuthSession();
  const capabilities = resolveCollectionCapabilities(state.session?.role);
  const collectionsEnabled =
    getFrontendRuntimeConfig().features.collectionsEnabled;

  const [offset, setOffset] = useState(0);
  const [nameSearch, setNameSearch] = useState("");
  const [debouncedNameSearch, setDebouncedNameSearch] = useState("");
  const [accessFilter, setAccessFilter] = useState<
    CollectionAccessPolicy | "all"
  >("all");
  const [sortBy, setSortBy] = useState<"updated" | "name" | "docs">("updated");
  const [selectedCollectionId, setSelectedCollectionId] = useState<
    string | null
  >(null);
  const [dialogMode, setDialogMode] = useState<
    "create" | { mode: "edit"; collection: CollectionDetailResponse } | null
  >(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [actionRequestId, setActionRequestId] = useState<string | null>(null);
  const [dialogSaveError, setDialogSaveError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedNameSearch(nameSearch);
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [nameSearch]);

  const listQueryOptions = useMemo(
    () => ({
      limit: COLLECTIONS_PAGE_SIZE,
      offset,
      name_query: debouncedNameSearch || undefined,
    }),
    [offset, debouncedNameSearch],
  );

  const collectionsQuery = useQuery({
    queryKey: queryKeys.collections.list(listQueryOptions),
    queryFn: () => listCollections(listQueryOptions),
    enabled: collectionsEnabled,
    retry: (failureCount, error) =>
      !isEndpointNotFoundError(error) && failureCount < 2,
  });

  const allCollections = useMemo(
    () => collectionsQuery.data?.items ?? [],
    [collectionsQuery.data?.items],
  );
  const total = collectionsQuery.data?.total ?? 0;
  const listForbidden = isForbiddenError(collectionsQuery.error);

  // Client-side filter + sort
  const visibleCollections = useMemo(() => {
    let list =
      accessFilter === "all"
        ? allCollections
        : allCollections.filter((c) => c.access_policy === accessFilter);
    if (sortBy === "name")
      list = [...list].sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "docs")
      list = [...list].sort((a, b) => b.document_count - a.document_count);
    return list;
  }, [allCollections, accessFilter, sortBy]);

  // Summary metrics
  const totalDocs = allCollections.reduce((s, c) => s + c.document_count, 0);
  const indexedDocs = allCollections.reduce((s, c) => s + c.indexed_count, 0);
  const restrictedCount = allCollections.filter(
    (c) => c.access_policy !== "org_wide",
  ).length;

  const totalPages = Math.max(
    1,
    Math.ceil(Math.max(total, 1) / COLLECTIONS_PAGE_SIZE),
  );
  const currentPage = Math.floor(offset / COLLECTIONS_PAGE_SIZE) + 1;

  const createMutation = useMutation({
    mutationFn: (form: CollectionFormState) =>
      createCollection({
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
        is_dynamic: form.is_dynamic,
        rule_schema: form.is_dynamic ? form.rule_schema : null,
      }),
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(tc("feedbackCreated", { name: result.name }));
      setActionRequestId(null);
      setSelectedCollectionId(result.collection_id);
      await invalidateAfterMutation(queryClient, "collection.create");
    },
    onError: (error) => {
      setDialogSaveError(getApiErrorMessage(error));
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      collectionId,
      form,
    }: {
      collectionId: string;
      form: CollectionFormState;
    }) => {
      const updated = await updateCollection(collectionId, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        access_policy: form.access_policy,
      });
      if (form.is_dynamic) {
        await setCollectionRules(collectionId, form.rule_schema);
      }
      return updated;
    },
    onSuccess: async (result) => {
      setDialogMode(null);
      setDialogSaveError(null);
      setActionFeedback(tc("feedbackUpdated", { name: result.name }));
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.update");
    },
    onError: (error) => {
      setDialogSaveError(getApiErrorMessage(error));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (collectionId: string) => deleteCollection(collectionId),
    onSuccess: async (_, collectionId) => {
      if (selectedCollectionId === collectionId) setSelectedCollectionId(null);
      setActionFeedback(tc("feedbackDeleted"));
      setActionRequestId(null);
      await invalidateAfterMutation(queryClient, "collection.delete");
    },
    onError: (error) => {
      setActionFeedback(getApiErrorMessage(error));
      setActionRequestId(extractRequestIdFromError(error));
    },
  });

  function handleCreateSave(form: CollectionFormState) {
    setDialogSaveError(null);
    createMutation.mutate(form);
  }
  function handleEditSave(form: CollectionFormState) {
    if (!dialogMode || dialogMode === "create") return;
    setDialogSaveError(null);
    updateMutation.mutate({
      collectionId: dialogMode.collection.collection_id,
      form,
    });
  }
  function handleDeleteCollection(col: CollectionListItemResponse) {
    if (!window.confirm(tc("deleteConfirm", { name: col.name }))) return;
    deleteMutation.mutate(col.collection_id);
  }

  const isLoading = collectionsEnabled && collectionsQuery.isLoading;
  const isError = collectionsEnabled && collectionsQuery.isError;
  const showGrid = collectionsEnabled && !isLoading && !isError;

  return {
    tc,
    capabilities,
    collectionsEnabled,
    offset,
    setOffset,
    nameSearch,
    setNameSearch,
    accessFilter,
    setAccessFilter,
    sortBy,
    setSortBy,
    selectedCollectionId,
    setSelectedCollectionId,
    dialogMode,
    setDialogMode,
    actionFeedback,
    actionRequestId,
    dialogSaveError,
    setDialogSaveError,
    collectionsQuery,
    allCollections,
    total,
    listForbidden,
    visibleCollections,
    totalDocs,
    indexedDocs,
    restrictedCount,
    totalPages,
    currentPage,
    createMutation,
    updateMutation,
    deleteMutation,
    handleCreateSave,
    handleEditSave,
    handleDeleteCollection,
    isLoading,
    isError,
    showGrid,
  };
}

export type CollectionsPageController = ReturnType<typeof useCollectionsPage>;
