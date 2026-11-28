"use client";

import { useState } from "react";

import {
  listCollections,
  type CollectionListItemResponse,
  type CollectionListResponse,
} from "@/lib/api/collections";
import { queryKeys } from "@/lib/api/query";
import { useDebouncedValue } from "@/lib/pagination/useDebouncedValue";
import { useInfiniteList } from "@/lib/pagination/useInfiniteList";

export const COLLECTION_SELECTOR_PAGE_SIZE = 50;

/**
 * Collections for a selector: server-side `name_query` search (debounced),
 * offset pages with `total`, and load more, instead of one 200-row request.
 */
export function useCollectionSearchList({
  scope,
  enabled = true,
  pageSize = COLLECTION_SELECTOR_PAGE_SIZE,
}: {
  /** Distinguishes selectors in the query cache, e.g. "for-upload". */
  scope: string;
  enabled?: boolean;
  pageSize?: number;
}) {
  const [search, setSearch] = useState("");
  const nameQuery = useDebouncedValue(search.trim());

  const list = useInfiniteList<
    CollectionListResponse,
    CollectionListItemResponse
  >({
    queryKey: queryKeys.collectionViews.picker(scope, nameQuery),
    pageSize,
    enabled,
    keepPreviousPages: true,
    fetchPage: ({ offset }) =>
      listCollections({
        limit: pageSize,
        offset,
        name_query: nameQuery || undefined,
      }),
  });

  return { ...list, search, setSearch, nameQuery };
}

export type CollectionSearchList = ReturnType<typeof useCollectionSearchList>;
