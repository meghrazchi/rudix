import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { DocumentListResponse } from "@/lib/api/documents";
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
  uploadDocument: (file: File, metadata?: unknown, signal?: AbortSignal) =>
    mockApi.uploadDocument(file, metadata, signal),
  UPLOAD_LANGUAGES: [],
  UPLOAD_RETENTION_CLASSES: [],
  listDocuments: (options?: unknown) => mockApi.listDocuments(options),
  getDocument: (documentId: string) => mockApi.getDocument(documentId),
  getDocumentStatus: (documentId: string) =>
    mockApi.getDocumentStatus(documentId),
  getDocumentChunks: (documentId: string, options?: unknown) =>
    mockApi.getDocumentChunks(documentId, options),
  deleteDocument: (documentId: string) => mockApi.deleteDocument(documentId),
  reindexDocument: (documentId: string) => mockApi.reindexDocument(documentId),
  downloadDocumentFile: (documentId: string) =>
    mockApi.downloadDocumentFile(documentId),
}));

function makeListResponse(
  status: "indexed" | "processing" = "indexed",
): DocumentListResponse {
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

function makeEmptyListResponse(): DocumentListResponse {
  return {
    items: [],
    total: 0,
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
    mockNavigation.searchParams = new URLSearchParams();
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

  it("renders documents table columns including updated timestamp and actions", async () => {
    renderPage();

    expect(await screen.findByText("policy.pdf")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Filename" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Type" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Status" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Pages" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Chunks" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Created" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Updated" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Actions" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download" }),
    ).toBeInTheDocument();
  });

  it("renders distinct lifecycle status badges", async () => {
    mockApi.listDocuments.mockResolvedValueOnce({
      items: [
        {
          document_id: "doc-uploaded",
          filename: "uploaded.pdf",
          file_type: "pdf",
          status: "uploaded",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          document_id: "doc-processing",
          filename: "processing.pdf",
          file_type: "pdf",
          status: "processing",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          document_id: "doc-indexed",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          document_id: "doc-failed",
          filename: "failed.pdf",
          file_type: "pdf",
          status: "failed",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          document_id: "doc-deleting",
          filename: "deleting.pdf",
          file_type: "pdf",
          status: "deleting",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
        {
          document_id: "doc-deleted",
          filename: "deleted.pdf",
          file_type: "pdf",
          status: "deleted",
          page_count: 1,
          chunk_count: 1,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
      ],
      total: 6,
      limit: 20,
      offset: 0,
      status: null,
      sort_by: "created_at",
      sort_order: "desc",
    });

    renderPage();

    expect(await screen.findByText("uploaded.pdf")).toBeInTheDocument();
    expect(screen.getByText("uploaded")).toHaveClass("bg-amber-100");
    expect(screen.getByText("processing")).toHaveClass("bg-blue-100");
    expect(screen.getByText("indexed")).toHaveClass("bg-emerald-100");
    expect(screen.getByText("failed")).toHaveClass("bg-rose-100");
    expect(screen.getByText("deleting")).toHaveClass("bg-slate-200");
    expect(screen.getByText("deleted")).toHaveClass("bg-slate-300");
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

    await userEvent.click(
      screen.getByRole("button", { name: /Upload document(s)?/i }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();

    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(mockApi.uploadDocument).toHaveBeenCalledTimes(1);
    });
    expect(mockApi.uploadDocument).toHaveBeenCalledWith(
      expect.any(File),
      expect.any(Object),
      expect.any(AbortSignal),
    );
  });

  it("uploads multiple files sequentially and shows queue progress", async () => {
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
    mockApi.uploadDocument
      .mockResolvedValueOnce({
        document_id: "doc-2",
        filename: "guide-a.pdf",
        status: "uploaded",
        queue_status: "queued",
        checksum: "xyz-a",
        message: "Document uploaded and queued for processing.",
      })
      .mockResolvedValueOnce({
        document_id: "doc-3",
        filename: "guide-b.pdf",
        status: "uploaded",
        queue_status: "queued",
        checksum: "xyz-b",
        message: "Document uploaded and queued for processing.",
      });

    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(
      screen.getByRole("button", { name: /Upload document(s)?/i }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();

    const firstFile = new File(["alpha"], "guide-a.pdf", {
      type: "application/pdf",
    });
    const secondFile = new File(["beta"], "guide-b.pdf", {
      type: "application/pdf",
    });
    await userEvent.upload(uploadInput as HTMLInputElement, [
      firstFile,
      secondFile,
    ]);

    await waitFor(() => {
      expect(mockApi.uploadDocument).toHaveBeenCalledTimes(2);
    });
    expect(mockApi.uploadDocument).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ name: "guide-a.pdf" }),
      expect.any(Object),
      expect.any(AbortSignal),
    );
    expect(mockApi.uploadDocument).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ name: "guide-b.pdf" }),
      expect.any(Object),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("2/2 done")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        /Uploaded 2\/2 file\(s\)\. Processing has been queued\./i,
      ).length,
    ).toBeGreaterThan(0);
  });

  it("rejects unsupported mime type before calling upload api", async () => {
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
    await userEvent.click(
      screen.getByRole("button", { name: /Upload document(s)?/i }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();

    const file = new File(["hello"], "guide.pdf", { type: "application/json" });
    await userEvent.upload(uploadInput as HTMLInputElement, file);

    await waitFor(() => {
      expect(mockApi.uploadDocument).not.toHaveBeenCalled();
      expect(
        screen.getAllByText(/Unsupported MIME type/i).length,
      ).toBeGreaterThan(0);
    });
  });

  it("shows safe 413 and 415 upload errors", async () => {
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
    await userEvent.click(
      screen.getByRole("button", { name: /Upload document(s)?/i }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();
    const file = new File(["hello"], "guide.pdf", { type: "application/pdf" });

    mockApi.uploadDocument.mockRejectedValueOnce(
      normalizeApiError({ status: 413, payload: { detail: "too large" } }),
    );
    await userEvent.upload(uploadInput as HTMLInputElement, file);
    await waitFor(() => {
      expect(
        screen.getAllByText(/uploaded file is too large/i).length,
      ).toBeGreaterThan(0);
    });

    mockApi.uploadDocument.mockRejectedValueOnce(
      normalizeApiError({ status: 415, payload: { detail: "unsupported" } }),
    );
    await userEvent.upload(uploadInput as HTMLInputElement, file);
    await waitFor(() => {
      expect(
        screen.getAllByText(/file type is not supported/i).length,
      ).toBeGreaterThan(0);
    });
  });

  it("cancels active and pending uploads when modal closes", async () => {
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

    const resolveFirstRef: { current: (() => void) | null } = {
      current: null,
    };
    let activeSignal: AbortSignal | undefined;
    mockApi.uploadDocument
      .mockImplementationOnce(
        (_file: File, _metadata: unknown, signal?: AbortSignal) =>
          new Promise((resolve) => {
            activeSignal = signal;
            resolveFirstRef.current = () => {
              resolve({
                document_id: "doc-2",
                filename: "guide-a.pdf",
                status: "uploaded",
                queue_status: "queued",
                checksum: "xyz-a",
                message: "Document uploaded and queued for processing.",
              });
            };
          }),
      )
      .mockImplementationOnce(() =>
        Promise.resolve({
          document_id: "doc-3",
          filename: "guide-b.pdf",
          status: "uploaded",
          queue_status: "queued",
          checksum: "xyz-b",
          message: "Document uploaded and queued for processing.",
        }),
      );

    renderPage();
    await screen.findByText("policy.pdf");

    await userEvent.click(
      screen.getByRole("button", { name: /Upload document(s)?/i }),
    );

    const uploadInput = screen
      .getByRole("dialog")
      .querySelector('input[type="file"]');
    expect(uploadInput).toBeTruthy();

    const firstFile = new File(["alpha"], "guide-a.pdf", {
      type: "application/pdf",
    });
    const secondFile = new File(["beta"], "guide-b.pdf", {
      type: "application/pdf",
    });
    await userEvent.upload(uploadInput as HTMLInputElement, [
      firstFile,
      secondFile,
    ]);

    await waitFor(() => {
      expect(mockApi.uploadDocument).toHaveBeenCalledTimes(1);
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Close upload center" }),
    );

    if (typeof resolveFirstRef.current === "function") {
      resolveFirstRef.current();
    }

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(
        screen.getByText(/Upload queue canceled by user\./i),
      ).toBeInTheDocument();
    });

    expect(activeSignal?.aborted).toBe(true);
    expect(mockApi.uploadDocument).toHaveBeenCalledTimes(1);
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

  it("shows empty-state upload CTA for permitted users", async () => {
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
    mockApi.listDocuments.mockResolvedValueOnce(makeEmptyListResponse());

    renderPage();

    expect(await screen.findByText("No documents found")).toBeInTheDocument();
    const emptyStateUploadButton = screen.getByRole("button", {
      name: "Upload document",
    });
    expect(emptyStateUploadButton).toBeInTheDocument();

    await userEvent.click(emptyStateUploadButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
