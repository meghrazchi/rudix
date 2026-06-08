import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDeletionStatusPage } from "@/components/admin/AdminDeletionStatusPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  AdminDocumentDeletionItem,
  AdminDocumentDeletionListResponse,
} from "@/lib/api/documents";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listAdminDocumentDeletion: vi.fn(),
  retryDeleteDocument: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/documents")>();
  return {
    ...actual,
    listAdminDocumentDeletion: (opts?: unknown) =>
      mockApi.listAdminDocumentDeletion(opts),
    retryDeleteDocument: (documentId: string) =>
      mockApi.retryDeleteDocument(documentId),
  };
});

const EMPTY_RESPONSE: AdminDocumentDeletionListResponse = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0,
};

const SAMPLE_ITEM: AdminDocumentDeletionItem = {
  document_id: "doc-uuid-1",
  filename: "contract.pdf",
  file_type: "pdf",
  status: "delete_requested",
  organization_id: "org-uuid-1",
  deletion_requested_at: "2026-06-02T08:00:00Z",
  deletion_hold_reason: null,
  error_message: null,
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-06-02T08:00:00Z",
};

const RETAINED_ITEM: AdminDocumentDeletionItem = {
  document_id: "doc-uuid-2",
  filename: "legal-brief.pdf",
  file_type: "pdf",
  status: "retained_by_policy",
  organization_id: "org-uuid-1",
  deletion_requested_at: "2026-06-01T12:00:00Z",
  deletion_hold_reason: "Document is under legal_hold and cannot be deleted.",
  error_message: null,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-06-01T12:00:00Z",
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage() {
  const queryClient = makeQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminDeletionStatusPage />
    </QueryClientProvider>,
  );
}

describe("AdminDeletionStatusPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        organizationId: "org-1",
        organizationName: "Test Org",
        role: "admin",
        email: "admin@example.com",
        displayName: "Admin",
        token: "tok",
        expiresAt: Date.now() + 3_600_000,
      },
    } as SessionState;
  });

  it("shows empty state when no documents are in deletion lifecycle", async () => {
    mockApi.listAdminDocumentDeletion.mockResolvedValue(EMPTY_RESPONSE);
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText(/no documents in deletion states/i),
      ).toBeInTheDocument();
    });
  });

  it("renders delete_requested documents with retry button", async () => {
    mockApi.listAdminDocumentDeletion.mockResolvedValue({
      ...EMPTY_RESPONSE,
      items: [SAMPLE_ITEM],
      total: 1,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("contract.pdf")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    // status badge in the table row
    expect(screen.getAllByText(/delete requested/i).length).toBeGreaterThan(0);
  });

  it("renders retained_by_policy documents with hold reason and no retry button", async () => {
    mockApi.listAdminDocumentDeletion.mockResolvedValue({
      ...EMPTY_RESPONSE,
      items: [RETAINED_ITEM],
      total: 1,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("legal-brief.pdf")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/document is under legal_hold/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /retry/i }),
    ).not.toBeInTheDocument();
  });

  it("calls retryDeleteDocument when retry button is clicked", async () => {
    mockApi.listAdminDocumentDeletion.mockResolvedValue({
      ...EMPTY_RESPONSE,
      items: [SAMPLE_ITEM],
      total: 1,
    });
    mockApi.retryDeleteDocument.mockResolvedValue({
      document_id: "doc-uuid-1",
      status: "delete_requested",
      queue_status: "queued",
    });
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /retry/i }),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(mockApi.retryDeleteDocument).toHaveBeenCalledWith("doc-uuid-1");
    });
    expect(
      await screen.findByText(/retry queued for document/i),
    ).toBeInTheDocument();
  });

  it("shows forbidden state for non-admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        organizationId: "org-1",
        organizationName: "Test Org",
        role: "member",
        email: "member@example.com",
        displayName: "Member",
        token: "tok",
        expiresAt: Date.now() + 3_600_000,
      },
    } as SessionState;
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/admin access required/i)).toBeInTheDocument();
    });
  });
});
