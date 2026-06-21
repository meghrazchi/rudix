import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentVersionHistoryPanel } from "@/components/documents/DocumentVersionHistoryPanel";
import { getDocumentVersions } from "@/lib/api/documents";

vi.mock("@/lib/api/documents", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/documents")>(
      "@/lib/api/documents",
    );
  return {
    ...actual,
    getDocumentVersions: vi.fn(),
  };
});

const mockedGetVersions = vi.mocked(getDocumentVersions);

function makeVersion(
  overrides: Partial<{
    version_id: string;
    version_number: number;
    change_reason: string;
    filename: string;
    status: string;
    is_current: boolean;
    content_hash: string | null;
    indexed_at: string | null;
    chunk_count: number | null;
    page_count: number | null;
    embedding_model: string | null;
    index_version: string | null;
    chunking_profile_snapshot: Record<string, unknown> | null;
  }> = {},
) {
  return {
    version_id: `ver-${overrides.version_number ?? 1}`,
    document_id: "doc-abc",
    version_number: 1,
    change_reason: "initial_upload",
    content_hash: "abc123def456",
    extraction_hash: null,
    chunking_profile_snapshot: null,
    embedding_model: null,
    embedding_vector_dimension: null,
    index_version: null,
    filename: "report.pdf",
    page_count: null,
    chunk_count: null,
    status: "indexed",
    indexed_at: null,
    is_current: true,
    source_updated_at: null,
    created_by_user_id: null,
    created_at: "2026-06-24T10:00:00Z",
    ...overrides,
  };
}

function makeListResponse(items: ReturnType<typeof makeVersion>[]) {
  return {
    document_id: "doc-abc",
    items,
    total: items.length,
  };
}

function renderPanel(documentId = "doc-abc") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DocumentVersionHistoryPanel documentId={documentId} />
    </QueryClientProvider>,
  );
}

describe("DocumentVersionHistoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockedGetVersions.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText(/loading version history/i)).toBeInTheDocument();
  });

  it("shows empty state when no versions returned", async () => {
    mockedGetVersions.mockResolvedValue(makeListResponse([]));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/no version history yet/i)).toBeInTheDocument();
    });
  });

  it("shows error state when request fails", async () => {
    mockedGetVersions.mockRejectedValue(new Error("Network error"));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });

  it("renders version card for single initial upload", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([makeVersion({ version_number: 1, is_current: true })]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("v1")).toBeInTheDocument();
    });
    expect(screen.getByText(/initial upload/i)).toBeInTheDocument();
    expect(screen.getByText(/active/i)).toBeInTheDocument();
  });

  it("renders multiple versions newest first", async () => {
    const versions = [
      makeVersion({ version_number: 3, change_reason: "reindex", is_current: true }),
      makeVersion({ version_number: 2, change_reason: "connector_sync", is_current: false }),
      makeVersion({ version_number: 1, change_reason: "initial_upload", is_current: false }),
    ];
    mockedGetVersions.mockResolvedValue(makeListResponse(versions));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("v3")).toBeInTheDocument();
    });
    const vLabels = screen.getAllByText(/^v\d+$/);
    expect(vLabels.map((el) => el.textContent)).toEqual(["v3", "v2", "v1"]);
  });

  it("shows version count summary", async () => {
    const versions = [
      makeVersion({ version_number: 2, is_current: true }),
      makeVersion({ version_number: 1, is_current: false }),
    ];
    mockedGetVersions.mockResolvedValue(makeListResponse(versions));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/2 versions recorded/i)).toBeInTheDocument();
    });
  });

  it("shows singular version count", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([makeVersion({ version_number: 1, is_current: true })]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/1 version recorded/i)).toBeInTheDocument();
    });
  });

  it("does not show active badge on non-current versions", async () => {
    const versions = [
      makeVersion({ version_number: 2, is_current: true }),
      makeVersion({ version_number: 1, is_current: false }),
    ];
    mockedGetVersions.mockResolvedValue(makeListResponse(versions));
    renderPanel();
    await waitFor(() => {
      const badges = screen.getAllByText(/active/i);
      expect(badges).toHaveLength(1);
    });
  });

  it("renders connector_sync change reason label", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, change_reason: "connector_sync", is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/connector sync/i)).toBeInTheDocument();
    });
  });

  it("renders reindex change reason label", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 2, change_reason: "reindex", is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/re-indexed/i)).toBeInTheDocument();
    });
  });

  it("shows short content hash", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, content_hash: "abc123def456abc123", is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      // First 12 chars of hash are displayed
      expect(screen.getByText(/abc123def456/)).toBeInTheDocument();
    });
  });

  it("omits content hash section when hash is null", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, content_hash: null, is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.queryByText(/content hash/i)).not.toBeInTheDocument();
    });
  });

  it("shows embedding model when present", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({
          version_number: 1,
          embedding_model: "text-embedding-3-small",
          is_current: true,
        }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("text-embedding-3-small")).toBeInTheDocument();
    });
  });

  it("shows chunking strategy from snapshot", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({
          version_number: 1,
          chunking_profile_snapshot: { strategy: "paragraph" },
          is_current: true,
        }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("paragraph")).toBeInTheDocument();
    });
  });

  it("calls getDocumentVersions with correct document id", async () => {
    mockedGetVersions.mockResolvedValue(makeListResponse([]));
    renderPanel("my-doc-id");
    await waitFor(() => {
      expect(mockedGetVersions).toHaveBeenCalledWith("my-doc-id");
    });
  });

  it("shows indexed_at when present", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({
          version_number: 1,
          indexed_at: "2026-06-24T12:30:00Z",
          is_current: true,
        }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/indexed at/i)).toBeInTheDocument();
    });
  });

  it("shows page count when present", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, page_count: 42, is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
    });
  });

  it("shows chunk count when present", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, chunk_count: 128, is_current: true }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("128")).toBeInTheDocument();
    });
  });

  it("tombstone version shows not-current", async () => {
    mockedGetVersions.mockResolvedValue(
      makeListResponse([
        makeVersion({ version_number: 1, change_reason: "tombstone", status: "deleted", is_current: false }),
      ]),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.queryByText(/active/i)).not.toBeInTheDocument();
      expect(screen.getByText(/tombstoned/i)).toBeInTheDocument();
    });
  });
});
