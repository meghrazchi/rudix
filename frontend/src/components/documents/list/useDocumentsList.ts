"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  DocumentListResponse,
  ListDocumentsOptions,
} from "@/lib/api/documents";
import { listDocuments } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { shouldPollDocumentList } from "@/lib/documents-ui";

/** Current page of the documents table, polled while documents are processing. */
export function useDocumentsList(listQueryOptions: ListDocumentsOptions) {
  return useQuery({
    queryKey: queryKeys.documents.list(listQueryOptions),
    queryFn: () => listDocuments(listQueryOptions),
    refetchInterval: (query) => {
      const data = query.state.data as DocumentListResponse | undefined;
      return shouldPollDocumentList(data?.items) ? 4_000 : false;
    },
    refetchIntervalInBackground: true,
  });
}
