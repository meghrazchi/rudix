import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatSourceQueries } from "@/components/chat/hooks/useChatSourceQueries";
import { useCitationPanel } from "@/components/chat/hooks/useCitationPanel";

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  getDocumentChunks: vi.fn(),
  listCollections: vi.fn(),
  listCollectionDocuments: vi.fn(),
  listAvailableConnectorConnections: vi.fn(),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) => mockApi.listDocuments(...args),
  getDocumentChunks: (...args: unknown[]) => mockApi.getDocumentChunks(...args),
  downloadDocumentFile: vi.fn(),
}));

vi.mock("@/lib/api/collections", () => ({
  listCollections: (...args: unknown[]) => mockApi.listCollections(...args),
  listCollectionDocuments: (...args: unknown[]) =>
    mockApi.listCollectionDocuments(...args),
}));

vi.mock("@/lib/api/connectors", () => ({
  listAvailableConnectorConnections: () =>
    mockApi.listAvailableConnectorConnections(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function doc(index: number) {
  return {
    document_id: `doc-${index}`,
    filename: `file-${index}.pdf`,
    file_type: "pdf",
    status: "indexed",
    chunk_count: 1,
    updated_at: "2026-05-15T00:00:00Z",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.listAvailableConnectorConnections.mockResolvedValue({ items: [] });
  mockApi.listDocuments.mockImplementation(
    async (options: { limit: number; offset: number }) => {
      const all = Array.from({ length: 45 }, (_, i) => doc(i + 1));
      return {
        items: all.slice(options.offset, options.offset + options.limit),
        total: all.length,
        limit: options.limit,
        offset: options.offset,
      };
    },
  );
  mockApi.listCollections.mockImplementation(
    async (options: { offset: number; name_query?: string }) => ({
      items: [
        {
          collection_id: `col-${options.offset}`,
          name: options.name_query ?? "Finance",
          description: null,
        },
      ],
      total: options.name_query ? 1 : 2,
      limit: 1,
      offset: options.offset,
    }),
  );
});

describe("useChatSourceQueries paging (R07-06)", () => {
  it("pages the document picker and keeps picked documents valid", async () => {
    const { result } = renderHook(
      () =>
        useChatSourceQueries({
          scopeMode: "documents",
          selectedCollectionIds: [],
          documentSearchQuery: "",
        }),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.composerIndexedDocuments).toHaveLength(30),
    );
    expect(result.current.documentsPaging.total).toBe(45);
    expect(result.current.documentsPaging.hasMore).toBe(true);

    act(() => result.current.documentsPaging.onLoadMore());
    await waitFor(() =>
      expect(result.current.composerIndexedDocuments).toHaveLength(45),
    );
    expect(result.current.indexedDocumentIdSet.has("doc-45")).toBe(true);
    expect(mockApi.listDocuments).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 30, offset: 30, status: "indexed" }),
    );
  });

  it("searches collections on the server and loads more", async () => {
    const { result } = renderHook(
      () =>
        useChatSourceQueries({
          scopeMode: "collection",
          selectedCollectionIds: [],
          documentSearchQuery: "",
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.collections).toHaveLength(1));
    expect(result.current.collectionsPaging.hasMore).toBe(true);
    act(() => result.current.collectionsPaging.onLoadMore());
    await waitFor(() => expect(result.current.collections).toHaveLength(2));

    act(() => result.current.collectionsSearch.setSearch("Legal"));
    await waitFor(() =>
      expect(mockApi.listCollections).toHaveBeenCalledWith(
        expect.objectContaining({ name_query: "Legal", offset: 0 }),
      ),
    );
    await waitFor(() =>
      expect(result.current.collections.map((c) => c.name)).toEqual(["Legal"]),
    );
  });

  it("reads every page of a selected collection for the scope", async () => {
    mockApi.listCollectionDocuments.mockImplementation(
      async (_id: string, options: { limit: number; offset?: number }) => {
        const all = Array.from({ length: 250 }, (_, i) => doc(i + 1));
        const offset = options.offset ?? 0;
        return {
          items: all.slice(offset, offset + options.limit),
          total: all.length,
        };
      },
    );
    const { result } = renderHook(
      () =>
        useChatSourceQueries({
          scopeMode: "collection",
          selectedCollectionIds: ["col-a"],
          documentSearchQuery: "",
        }),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.collectionDocumentIdSet?.size).toBe(250),
    );
  });
});

describe("useCitationPanel chunk lookup (R07-06)", () => {
  it("fetches only the cited chunk with the chunk_id filter", async () => {
    mockApi.getDocumentChunks.mockResolvedValue({
      document_id: "doc-1",
      items: [{ chunk_id: "chunk-9", text_preview: "cited", text: "cited" }],
      total: 1,
      limit: 1,
      offset: 0,
      include_full_text: true,
    });
    const { result } = renderHook(
      () => useCitationPanel({ selectedCitationTurn: null }),
      { wrapper },
    );

    act(() =>
      result.current.setPreviewCitationSet({
        citations: [
          {
            document_id: "doc-1",
            chunk_id: "chunk-9",
            filename: "a.pdf",
            page_number: 1,
            text_snippet: null,
            score: null,
            similarity_score: null,
            rerank_score: null,
          },
        ],
        initialIndex: 0,
      }),
    );

    await waitFor(() =>
      expect(result.current.activePreviewCitationChunk?.chunk_id).toBe(
        "chunk-9",
      ),
    );
    expect(mockApi.getDocumentChunks).toHaveBeenCalledWith("doc-1", {
      limit: 1,
      include_full_text: true,
      chunk_id: "chunk-9",
    });
  });
});
