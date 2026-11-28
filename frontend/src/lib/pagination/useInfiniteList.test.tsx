import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  resolveListTotal,
  resolveNextPageParam,
  useInfiniteList,
  type PageLike,
  type PageParam,
} from "@/lib/pagination/useInfiniteList";
import {
  parseVirtualizeMinRows,
  tableVirtualizeMinRows,
} from "@/lib/pagination/virtualize";
import { useDebouncedValue } from "@/lib/pagination/useDebouncedValue";

type Row = { id: string };

function page(
  ids: string[],
  extra: Partial<PageLike<Row>> = {},
): PageLike<Row> {
  return { items: ids.map((id) => ({ id })), ...extra };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("resolveNextPageParam", () => {
  it("follows next_cursor when the response has one", () => {
    const first = page(["a"], { next_cursor: "c1", total: 3 });
    expect(resolveNextPageParam(first, [first], { offset: 0 }, 1)).toEqual({
      cursor: "c1",
      offset: 0,
    });
  });

  it("stops a cursor list when the cursor runs out, even below total", () => {
    const first = page(["a"], { next_cursor: "c1", total: 5 });
    const last = page(["b"], { next_cursor: null });
    expect(
      resolveNextPageParam(last, [first, last], { cursor: "c1", offset: 0 }, 1),
    ).toBeUndefined();
  });

  it("uses offset + limit < total without a cursor", () => {
    const first = page(["a", "b"], { total: 3, limit: 2 });
    expect(resolveNextPageParam(first, [first], { offset: 0 }, 50)).toEqual({
      offset: 2,
    });
    const second = page(["c"], { total: 3, limit: 2 });
    expect(
      resolveNextPageParam(second, [first, second], { offset: 2 }, 50),
    ).toBeUndefined();
  });

  it("falls back to the page size when the response has no limit", () => {
    const first = page(["a"], { total: 4 });
    expect(resolveNextPageParam(first, [first], { offset: 0 }, 2)).toEqual({
      offset: 2,
    });
  });

  it("has no next page without a cursor or a total", () => {
    const first = page(["a"]);
    expect(
      resolveNextPageParam(first, [first], { offset: 0 }, 1),
    ).toBeUndefined();
  });

  it("reads the total from the first page that has one", () => {
    expect(resolveListTotal([page([]), page([], { total: 7 })])).toBe(7);
    expect(resolveListTotal([page([])])).toBeNull();
  });
});

describe("useInfiniteList", () => {
  it("appends pages on load more and reports the total", async () => {
    const fetchPage = vi.fn(async ({ offset }: PageParam) =>
      offset === 0
        ? page(["a", "b"], { total: 3, limit: 2 })
        : page(["c"], { total: 3, limit: 2 }),
    );
    const { result } = renderHook(
      () =>
        useInfiniteList<PageLike<Row>, Row>({
          queryKey: ["test", "offset"],
          fetchPage,
          pageSize: 2,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.total).toBe(3);
    expect(result.current.hasMore).toBe(true);

    act(() => result.current.loadMore());
    await waitFor(() =>
      expect(result.current.items.map((row) => row.id)).toEqual([
        "a",
        "b",
        "c",
      ]),
    );
    expect(result.current.hasMore).toBe(false);
    expect(fetchPage).toHaveBeenLastCalledWith({ offset: 2 });

    // No further request once everything is loaded.
    act(() => result.current.loadMore());
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });

  it("passes the cursor of the previous page", async () => {
    const fetchPage = vi.fn(async ({ cursor }: PageParam) =>
      cursor
        ? page(["b"], { next_cursor: null })
        : page(["a"], { next_cursor: "next-1", total: 2 }),
    );
    const { result } = renderHook(
      () =>
        useInfiniteList<PageLike<Row>, Row>({
          queryKey: ["test", "cursor"],
          fetchPage,
          pageSize: 1,
          refetchInterval: () => false,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.hasMore).toBe(true));
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(fetchPage).toHaveBeenLastCalledWith({
      cursor: "next-1",
      offset: 0,
    });
    expect(result.current.total).toBe(2);
    expect(result.current.hasMore).toBe(false);
  });
});

describe("table virtualisation threshold", () => {
  it("parses NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS with a default of 200", () => {
    expect(parseVirtualizeMinRows(undefined)).toBe(200);
    expect(parseVirtualizeMinRows("50")).toBe(50);
    expect(parseVirtualizeMinRows("0")).toBe(200);
    expect(parseVirtualizeMinRows("abc")).toBe(200);
  });

  it("reads the environment", () => {
    vi.stubEnv("NEXT_PUBLIC_TABLE_VIRTUALIZE_MIN_ROWS", "25");
    expect(tableVirtualizeMinRows()).toBe(25);
    vi.unstubAllEnvs();
  });
});

describe("useDebouncedValue", () => {
  it("updates after the delay", async () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 10),
      { initialProps: { value: "a" } },
    );
    rerender({ value: "ab" });
    expect(result.current).toBe("a");
    await waitFor(() => expect(result.current).toBe("ab"));
  });
});
