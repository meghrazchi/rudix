import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { DocumentListResponse } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  uploadDocument: vi.fn(),
  listDocuments: vi.fn(),
  getDocument: vi.fn(),
  getDocumentStatus: vi.fn(),
  getDocumentChunks: vi.fn(),
  deleteDocument: vi.fn(),
  reindexDocument: vi.fn(),
  downloadDocumentFile: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  uploadDocument: (file: File) => mockApi.uploadDocument(file),
  listDocuments: (options?: unknown) => mockApi.listDocuments(options),
  getDocument: (documentId: string) => mockApi.getDocument(documentId),
  getDocumentStatus: (documentId: string) => mockApi.getDocumentStatus(documentId),
  getDocumentChunks: (documentId: string, options?: unknown) => mockApi.getDocumentChunks(documentId, options),
  deleteDocument: (documentId: string) => mockApi.deleteDocument(documentId),
  reindexDocument: (documentId: string) => mockApi.reindexDocument(documentId),
  downloadDocumentFile: (documentId: string) =>
    mockApi.downloadDocumentFile(documentId),
}));

function makeListResponse(status: "indexed" | "processing" = "indexed"): DocumentListResponse {
  return {
    items: [
      {
        document_id: "doc-1",
        filename: "policy.pdf",
        file_type: "pdf",
        status,
        page_count: 3,
        chunk_count: 12,
        error_message: null,
        error_details: null,
        created_at: "2026-05-14T00:00:00Z",
        updated_at: "2026-05-14T00:00:00Z",
      },
    ],
    total: 1,
    limit: 20,
    offset: 0,
    status: null,
    sort_by: "created_at",
    sort_order: "desc",
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentsPage />
    </QueryClientProvider>,
  );
}

describe("DocumentsPage", () => {
  const createObjectUrlMock = vi.fn(() => "blob:mock-url");
  const revokeObjectUrlMock = vi.fn();

  beforeEach(() => {
    createObjectUrlMock.mockClear();
    revokeObjectUrlMock.mockClear();
    URL.createObjectURL = createObjectUrlMock;
    URL.revokeObjectURL = revokeObjectUrlMock;

    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "user@example.com",
        role: "viewer",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    mockApi.listDocuments.mockReset();
    mockApi.getDocument.mockReset();
    mockApi.getDocumentStatus.mockReset();
    mockApi.getDocumentChunks.mockReset();
    mockApi.uploadDocument.mockReset();
    mockApi.deleteDocument.mockReset();
    mockApi.reindexDocument.mockReset();
    mockApi.downloadDocumentFile.mockReset();

    mockApi.listDocuments.mockResolvedValue(makeListResponse("indexed"));
    mockApi.getDocument.mockResolvedValue({
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 3,
      chunk_count: 12,
      checksum: "abc",
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T00:00:00Z",
      updated_at: "2026-05-14T00:00:00Z",
    });
    mockApi.getDocumentStatus.mockResolvedValue({
      document_id: "doc-1",
      status: "indexed",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-14T00:00:00Z",
    });
    mockApi.getDocumentChunks.mockResolvedValue({
      document_id: "doc-1",
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
      include_full_text: false,
    });
    mockApi.uploadDocument.mockResolvedValue({
      document_id: "doc-2",
      filename: "guide.pdf",
      status: "uploaded",
      queue_status: "queued",
      checksum: "xyz",
      message: "Document uploaded and queued for processing.",
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
    mockApi.downloadDocumentFile.mockResolvedValue(new Blob(["pdf-bytes"]));
  });

  it("shows read-only state for viewer role and disables mutation actions", async () => {
    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.getByText("Read-only role")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeDisabled();
  });

  it("enables delete but keeps re-index disabled for member role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Read-only role")).not.toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Re-index" })).toBeDisabled();
  });

  it("uploads a supported file for roles that can upload", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-3",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-3",
      },
    };

    renderPage();
    await screen.findByText("policy.pdf");

    const uploadInput = document.querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();

    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(mockApi.uploadDocument).toHaveBeenCalledTimes(1);
    });
    expect(mockApi.uploadDocument).toHaveBeenCalledWith(expect.any(File));
  });

  it("downloads a document file from list actions", async () => {
    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(screen.getByRole("button", { name: "Download" }));

    await waitFor(() => {
      expect(mockApi.downloadDocumentFile).toHaveBeenCalledTimes(1);
    });
    expect(mockApi.downloadDocumentFile).toHaveBeenCalledWith("doc-1");
    expect(createObjectUrlMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrlMock).toHaveBeenCalledTimes(1);
  });
});
