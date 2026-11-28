"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getDocumentCollections,
  listCollections,
  setDocumentCollections,
} from "@/lib/api/collections";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";

import type { DocumentsPageTranslator } from "@/components/documents/list/documents-list-format";

type UseAssignCollectionsArgs = {
  tp: DocumentsPageTranslator;
  isUploadModalOpen: boolean;
  setActionFeedback: Dispatch<SetStateAction<string | null>>;
  setActionRequestId: Dispatch<SetStateAction<string | null>>;
};

/** Collection lists for the upload modal and the assign-collections dialog. */
export function useAssignCollections({
  tp,
  isUploadModalOpen,
  setActionFeedback,
  setActionRequestId,
}: UseAssignCollectionsArgs) {
  const queryClient = useQueryClient();
  const [assignDocumentId, setAssignDocumentId] = useState<string | null>(null);
  const [assignDocumentName, setAssignDocumentName] = useState<string>("");
  const [assignSaveError, setAssignSaveError] = useState<string | null>(null);

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

  return {
    assignDocumentId,
    setAssignDocumentId,
    assignDocumentName,
    setAssignDocumentName,
    assignSaveError,
    setAssignSaveError,
    allCollectionsQuery,
    assignCollectionsListQuery,
    docCollectionsQuery,
    assignCollectionsMutation,
  };
}
