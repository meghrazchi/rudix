import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentDetailPage } from "@/components/documents/DocumentDetailPage";
import { normalizeApiError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

  const mockApi = vi.hoisted(() => ({
    getDocument: vi.fn(),
    getDocumentStatus: vi.fn(),
    getDocumentChunks: vi.fn(),
    deleteDocument: vi.fn(),
    reindexDocument: vi.fn(),
  }));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  getDocument: (documentId: string) => mockApi.getDocument(documentId),
  getDocumentStatus: (documentId: string) => mockApi.getDocumentStatus(documentId),
  getDocumentChunks: (documentId: string, options?: unknown) => mockApi.getDocumentChunks(documentId, options),
  deleteDocument: (documentId: string) => mockApi.deleteDocument(documentId),
  reindexDocument: (documentId: string) => mockApi.reindexDocument(documentId),
}));

function renderPage(documentId = "doc-1") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentDetailPage documentId={documentId} />
    </QueryClientProvider>,
  );
}

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    mockNavigation.searchParams = new URLSearchParams();
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };
    mockApi.getDocument.mockReset();
    mockApi.getDocumentStatus.mockReset();
    mockApi.getDocumentChunks.mockReset();
    mockApi.deleteDocument.mockReset();
    mockApi.reindexDocument.mockReset();
    Object.defineProperty(window, "confirm", {
      writable: true,
      value: vi.fn(() => true),
    });

    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 12,
      chunk_count: 120,
      checksum: "abc123",
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValue({
      document_id: "doc-1",
      status: "indexed",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentChunks.mockResolvedValue({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          text_preview: "Preview text for the first chunk.",
          text: null,
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: false,
    });
    mockApi.deleteDocument.mockResolvedValue({
      document_id: "doc-1",
      status: "deleting",
    });
    mockApi.reindexDocument.mockResolvedValue({
      document_id: "doc-1",
      status: "processing",
      queue_status: "queued",
    });
  });

  it("renders indexed metadata and actions with preserved back link", async () => {
    mockNavigation.searchParams = new URLSearchParams({
      back: "/documents?status=failed&sort_by=updated_at&sort_order=asc&offset=20",
    });

    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle timeline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to documents" })).toHaveAttribute(
      "href",
      "/documents?status=failed&sort_by=updated_at&sort_order=asc&offset=20",
    );
    expect(screen.getByRole("link", { name: "Ask in Chat" })).toHaveAttribute(
      "href",
      "/chat?document_id=doc-1",
    );
    expect(screen.getByRole("link", { name: "View Pipeline" })).toHaveAttribute(
      "href",
      "/rag-pipeline?run_type=document.process&document_id=doc-1",
    );
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeEnabled();
    expect(await screen.findByText("Chunk #1")).toBeInTheDocument();
    expect(await screen.findByText("Model text-embedding-3-small")).toBeInTheDocument();
    expect(await screen.findByText("Preview text for the first chunk.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /include full chunk text/i })).toBeInTheDocument();
  });

  it("fetches full chunk text when full-text toggle is enabled", async () => {
    mockApi.getDocumentChunks.mockResolvedValueOnce({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          text_preview: "Preview text for the first chunk.",
          text: null,
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: false,
    });
    mockApi.getDocumentChunks.mockResolvedValueOnce({
      document_id: "doc-1",
      items: [
        {
          chunk_id: "chunk-1",
          page_number: 1,
          chunk_index: 1,
          token_count: 42,
          embedding_model: "text-embedding-3-small",
          index_version: "v1",
          text_preview: "Preview text for the first chunk.",
          text: "FULL CHUNK TEXT",
          created_at: "2026-05-14T11:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      include_full_text: true,
    });

    renderPage();

    expect(await screen.findByText("Preview text for the first chunk.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /include full chunk text/i }));

    await waitFor(() => {
      expect(mockApi.getDocumentChunks).toHaveBeenCalledWith(
        "doc-1",
        expect.objectContaining({ include_full_text: true }),
      );
    });
    expect(await screen.findByText("FULL CHUNK TEXT")).toBeInTheDocument();
  });

  it("shows failed document safe error details and disables ask in chat", async () => {
    mockApi.getDocument.mockResolvedValueOnce({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "failed",
      page_count: 0,
      chunk_count: 0,
      checksum: "abc123",
      error_message: "Processing failed",
      error_details: {
        stage: "embedding",
        code: "EMBED_TIMEOUT",
        category: "transient",
        retryable: true,
        message: "Embedding provider timeout",
      },
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T10:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValueOnce({
      document_id: "doc-1",
      status: "failed",
      error_message: "Processing failed",
      error_details: {
        stage: "embedding",
        code: "EMBED_TIMEOUT",
        category: "transient",
        retryable: true,
        message: "Embedding provider timeout",
      },
      updated_at: "2026-05-15T10:00:00Z",
    });

    renderPage();

    expect(await screen.findByText("Processing error")).toBeInTheDocument();
    expect(screen.getByText("Processing failed")).toBeInTheDocument();
    expect(screen.getByText(/EMBED_TIMEOUT/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ask in Chat" })).not.toBeInTheDocument();
    expect(screen.getByText("Ask in Chat")).toBeInTheDocument();
  });

  it("uses safe not-found behavior for inaccessible documents", async () => {
    mockApi.getDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 403,
        payload: { detail: "forbidden internal detail" },
      }),
    );

    renderPage();

    expect(await screen.findByText("Document not found")).toBeInTheDocument();
    expect(screen.queryByText("forbidden internal detail")).not.toBeInTheDocument();
  });

  it("keeps rendering document details when live status endpoint fails", async () => {
    mockApi.getDocumentStatus.mockRejectedValueOnce(
      normalizeApiError({
        status: 404,
        payload: { detail: "status endpoint unavailable" },
      }),
    );

    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Document not found")).not.toBeInTheDocument();
  });

  it("accepts a safe chat back-link from citation deep links", async () => {
    mockNavigation.searchParams = new URLSearchParams({
      back: "/chat",
    });

    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to documents" })).toHaveAttribute("href", "/chat");
  });

  it("hides admin actions for viewer role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "viewer@example.com",
        role: "viewer",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-index" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /include full chunk text/i })).not.toBeInTheDocument();
  });

  it("requires confirmation before delete and supports delete success flow", async () => {
    renderPage();
    await screen.findByText("policy.pdf");

    const confirmMock = vi.mocked(window.confirm);
    confirmMock.mockReturnValueOnce(false);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(mockApi.deleteDocument).not.toHaveBeenCalled();

    confirmMock.mockReturnValueOnce(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(mockApi.deleteDocument).toHaveBeenCalledWith("doc-1");
    });
    expect(await screen.findByText(/Delete requested\. Current status: deleting\./i)).toBeInTheDocument();
  });

  it("shows conflict-safe messages for delete and re-index mutations", async () => {
    mockApi.deleteDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 409,
        payload: { detail: "cannot delete while processing" },
      }),
    );
    mockApi.reindexDocument.mockRejectedValueOnce(
      normalizeApiError({
        status: 409,
        payload: { detail: "cannot reindex while deleting" },
      }),
    );

    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(
      await screen.findByText(/cannot be deleted in its current lifecycle state/i),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Re-index" }));
    expect(
      await screen.findByText(/cannot be re-indexed in its current lifecycle state/i),
    ).toBeInTheDocument();
  });

  it("supports successful re-index mutation flow", async () => {
    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(screen.getByRole("button", { name: "Re-index" }));
    await waitFor(() => {
      expect(mockApi.reindexDocument).toHaveBeenCalledWith("doc-1");
    });
    expect(await screen.findByText(/Re-index requested\. Queue status: queued\./i)).toBeInTheDocument();
  });
});
