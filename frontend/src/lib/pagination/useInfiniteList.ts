"use client";

import { useMemo } from "react";

import {
  useInfiniteQuery,
  type InfiniteData,
  type QueryKey,
} from "@tanstack/react-query";

/** The fields every paged list response in the API shares. */
export type PageLike<TItem> = {
  items: TItem[];
  total?: number | null;
  limit?: number | null;
  next_cursor?: string | null;
};

/** Where the next page starts: a keyset cursor or an offset. */
export type PageParam = { cursor?: string; offset: number };

export const FIRST_PAGE: PageParam = { offset: 0 };

/** The first `total` any page reported (cursor pages after the first omit it). */
export function resolveListTotal<TItem>(
  pages: ReadonlyArray<PageLike<TItem>>,
): number | null {
  for (const page of pages) {
    if (typeof page.total === "number") {
      return page.total;
    }
  }
  return null;
}

/**
 * Next page from `next_cursor` when the list is cursor-paged, else from
 * `offset + limit < total`. A list is cursor-paged once any page returned a
 * cursor; after that a missing cursor means the end, never an offset fallback.
 */
export function resolveNextPageParam<TItem>(
  lastPage: PageLike<TItem>,
  allPages: ReadonlyArray<PageLike<TItem>>,
  lastPageParam: PageParam,
  pageSize: number,
): PageParam | undefined {
  const nextCursor = lastPage.next_cursor?.trim();
  if (nextCursor) {
    return { cursor: nextCursor, offset: 0 };
  }
  const cursorPaged =
    Boolean(lastPageParam.cursor) ||
    allPages.some((page) => Boolean(page.next_cursor?.trim()));
  if (cursorPaged) {
    return undefined;
  }
  const total = resolveListTotal(allPages);
  if (total === null) {
    return undefined;
  }
  const limit =
    typeof lastPage.limit === "number" && lastPage.limit > 0
      ? lastPage.limit
      : pageSize;
  const nextOffset = lastPageParam.offset + limit;
  return nextOffset < total ? { offset: nextOffset } : undefined;
}

export type UseInfiniteListOptions<TPage extends PageLike<TItem>, TItem> = {
  queryKey: QueryKey;
  fetchPage: (param: PageParam) => Promise<TPage>;
  pageSize: number;
  enabled?: boolean;
  refetchInterval?:
    | number
    | false
    | ((data: InfiniteData<TPage, PageParam> | undefined) => number | false);
  refetchIntervalInBackground?: boolean;
  retry?: boolean | ((failureCount: number, error: Error) => boolean);
  keepPreviousPages?: boolean;
};

/** `useInfiniteQuery` for list endpoints, flattened into items, total, and load-more. */
export function useInfiniteList<TPage extends PageLike<TItem>, TItem>(
  options: UseInfiniteListOptions<TPage, TItem>,
) {
  const { refetchInterval } = options;
  const query = useInfiniteQuery({
    queryKey: options.queryKey,
    initialPageParam: FIRST_PAGE,
    queryFn: ({ pageParam }) => options.fetchPage(pageParam),
    getNextPageParam: (lastPage, allPages, lastPageParam) =>
      resolveNextPageParam<TItem>(
        lastPage,
        allPages,
        lastPageParam,
        options.pageSize,
      ),
    enabled: options.enabled ?? true,
    refetchInterval:
      typeof refetchInterval === "function"
        ? (current) => refetchInterval(current.state.data)
        : refetchInterval,
    refetchIntervalInBackground: options.refetchIntervalInBackground,
    retry: options.retry,
    placeholderData: options.keepPreviousPages
      ? (previous) => previous
      : undefined,
  });

  const pages = query.data?.pages;
  const items = useMemo(
    () => (pages ?? []).flatMap((page) => page.items),
    [pages],
  );
  const total = useMemo(() => resolveListTotal(pages ?? []), [pages]);

  return {
    query,
    items,
    total,
    hasMore: Boolean(query.hasNextPage),
    isLoadingMore: query.isFetchingNextPage,
    loadMore: () => {
      if (query.hasNextPage && !query.isFetchingNextPage) {
        void query.fetchNextPage();
      }
    },
  };
}

export type InfiniteListResult<TItem> = {
  items: TItem[];
  total: number | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
};
