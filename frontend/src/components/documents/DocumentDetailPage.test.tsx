import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    mockApi.deleteDocument.mockReset();
    mockApi.reindexDocument.mockReset();

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
      "/rag-pipeline?document_id=doc-1",
    );
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeEnabled();
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
  });
});
