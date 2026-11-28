"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  DocumentListItemResponse,
  DocumentListResponse,
  ListDocumentsOptions,
} from "@/lib/api/documents";
import { listDocuments } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { shouldPollDocumentList } from "@/lib/documents-ui";
import { useInfiniteList } from "@/lib/pagination/useInfiniteList";

const LIST_POLL_INTERVAL_MS = 4_000;

/**
 * Documents table data. `sort_by=created_at` uses keyset (cursor) pages that
 * append with "Load more" (`include_total` on the first page); other sorts keep
 * offset pages with page navigation. Both poll while documents are processing.
 */
export function useDocumentsList(listQueryOptions: ListDocumentsOptions) {
  const cursorMode =
    (listQueryOptions.sort_by ?? "created_at") === "created_at";
  const { offset: _offset, ...cursorOptions } = listQueryOptions;

  const offsetQuery = useQuery({
    queryKey: queryKeys.documents.list(listQueryOptions),
    queryFn: () => listDocuments(listQueryOptions),
    enabled: !cursorMode,
    refetchInterval: (query) => {
      const data = query.state.data as DocumentListResponse | undefined;
      return shouldPollDocumentList(data?.items)
        ? LIST_POLL_INTERVAL_MS
        : false;
    },
    refetchIntervalInBackground: true,
  });

  const cursorList = useInfiniteList<
    DocumentListResponse,
    DocumentListItemResponse
  >({
    queryKey: queryKeys.documents.list({
      ...cursorOptions,
      pagination: "cursor",
    }),
    pageSize: listQueryOptions.limit ?? 20,
    enabled: cursorMode,
    fetchPage: ({ cursor }) =>
      listDocuments({
        ...cursorOptions,
        cursor,
        include_total: cursor ? undefined : true,
      }),
    refetchInterval: (data) =>
      shouldPollDocumentList(data?.pages.flatMap((page) => page.items))
        ? LIST_POLL_INTERVAL_MS
        : false,
    refetchIntervalInBackground: true,
  });

  if (cursorMode) {
    return {
      cursorMode,
      documentsQuery: cursorList.query,
      documents: cursorList.items,
      total: cursorList.total,
      hasMore: cursorList.hasMore,
      isLoadingMore: cursorList.isLoadingMore,
      loadMore: cursorList.loadMore,
    };
  }
  return {
    cursorMode,
    documentsQuery: offsetQuery,
    documents: offsetQuery.data?.items ?? [],
    total: offsetQuery.data?.total ?? null,
    hasMore: false,
    isLoadingMore: false,
    loadMore: () => undefined,
  };
}
