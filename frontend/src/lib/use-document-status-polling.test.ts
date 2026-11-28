import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/api/query";
import {
  getDocumentStatusRefetchInterval,
  useDocumentStatusPolling,
} from "@/lib/use-document-status-polling";

const mockUseQuery = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => mockUseQuery(options),
}));

describe("useDocumentStatusPolling", () => {
  beforeEach(() => {
    mockUseQuery.mockReset();
    mockUseQuery.mockReturnValue({ data: undefined });
  });

  it("computes refetch interval for terminal and non-terminal statuses", () => {
    expect(getDocumentStatusRefetchInterval("uploaded", null, 1111)).toBe(1111);
    expect(getDocumentStatusRefetchInterval("processing", null, 1111)).toBe(
      1111,
    );
    expect(getDocumentStatusRefetchInterval("deleting", null, 1111)).toBe(1111);
    expect(getDocumentStatusRefetchInterval("indexed", null, 1111)).toBe(false);
    expect(
      getDocumentStatusRefetchInterval("indexed", "extracting", 1111),
    ).toBe(1111);
    expect(getDocumentStatusRefetchInterval("failed", null, 1111)).toBe(false);
    expect(getDocumentStatusRefetchInterval("deleted", null, 1111)).toBe(false);
    expect(getDocumentStatusRefetchInterval(null, null, 1111)).toBe(false);
  });

  it("builds query options with polling that stops on terminal status", () => {
    renderHook(() =>
      useDocumentStatusPolling("doc-1", {
        initialStatus: "processing",
        pollIntervalMs: 1234,
      }),
    );

    expect(mockUseQuery).toHaveBeenCalledTimes(1);
    const options = mockUseQuery.mock.calls[0][0] as {
      enabled: boolean;
      queryKey: readonly unknown[];
      refetchInterval: (query: {
        state: { data?: { status?: string } };
      }) => number | false;
      refetchIntervalInBackground: boolean;
    };
    expect(options.enabled).toBe(true);
    expect(options.queryKey).toEqual(queryKeys.documents.status("doc-1"));
    // R07-07: never poll in a hidden tab.
    expect(options.refetchIntervalInBackground).toBe(false);
    expect(
      options.refetchInterval({ state: { data: { status: "processing" } } }),
    ).toBe(1234);
    expect(
      options.refetchInterval({ state: { data: { status: "indexed" } } }),
    ).toBe(false);
  });

  it("disables the status query when document id is missing", () => {
    renderHook(() => useDocumentStatusPolling(null, { enabled: true }));

    const options = mockUseQuery.mock.calls[0][0] as { enabled: boolean };
    expect(options.enabled).toBe(false);
  });
});
