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
    expect(getDocumentStatusRefetchInterval("uploaded", 1111)).toBe(1111);
    expect(getDocumentStatusRefetchInterval("processing", 1111)).toBe(1111);
    expect(getDocumentStatusRefetchInterval("deleting", 1111)).toBe(1111);
    expect(getDocumentStatusRefetchInterval("indexed", 1111)).toBe(false);
    expect(getDocumentStatusRefetchInterval("failed", 1111)).toBe(false);
    expect(getDocumentStatusRefetchInterval("deleted", 1111)).toBe(false);
    expect(getDocumentStatusRefetchInterval(null, 1111)).toBe(false);
  });

  it("builds query options with polling that stops on terminal status", () => {
    useDocumentStatusPolling("doc-1", {
      initialStatus: "processing",
      pollIntervalMs: 1234,
      refetchInBackground: true,
    });

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
    expect(options.refetchIntervalInBackground).toBe(true);
    expect(
      options.refetchInterval({ state: { data: { status: "processing" } } }),
    ).toBe(1234);
    expect(
      options.refetchInterval({ state: { data: { status: "indexed" } } }),
    ).toBe(false);
  });

  it("disables the status query when document id is missing", () => {
    useDocumentStatusPolling(null, { enabled: true });

    const options = mockUseQuery.mock.calls[0][0] as { enabled: boolean };
    expect(options.enabled).toBe(false);
  });
});
