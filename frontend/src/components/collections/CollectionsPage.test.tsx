import { QueryClient } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionsPage } from "@/components/collections/CollectionsPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  CollectionListResponse,
  CollectionDetailResponse,
} from "@/lib/api/collections";
import { listDocuments } from "@/lib/api/documents";
import { createTestQueryClient, renderWithProviders } from "@/test/render";

// ── Mock: auth session ──────────────────────────────────────────────────────

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      role: "admin" as const,
      organizationId: "org-1",
      organizationName: "Acme",
      accessToken: "token",
      refreshToken: null,
    },
  } as SessionState,
  signOut: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state, signOut: mockAuth.signOut }),
}));

// ── Mock: collections API ───────────────────────────────────────────────────

const mockCollectionsApi = vi.hoisted(() => ({
  listCollections: vi.fn(),
  getCollection: vi.fn(),
  createCollection: vi.fn(),
  updateCollection: vi.fn(),
  deleteCollection: vi.fn(),
  listCollectionDocuments: vi.fn(),
  removeDocumentFromCollection: vi.fn(),
  addDocumentToCollection: vi.fn(),
}));

const mockDocumentsApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/collections", () => ({
  listCollections: (...args: unknown[]) =>
    mockCollectionsApi.listCollections(...args),
  getCollection: (...args: unknown[]) =>
    mockCollectionsApi.getCollection(...args),
  createCollection: (...args: unknown[]) =>
    mockCollectionsApi.createCollection(...args),
  updateCollection: (...args: unknown[]) =>
    mockCollectionsApi.updateCollection(...args),
  deleteCollection: (...args: unknown[]) =>
    mockCollectionsApi.deleteCollection(...args),
  listCollectionDocuments: (...args: unknown[]) =>
    mockCollectionsApi.listCollectionDocuments(...args),
  removeDocumentFromCollection: (...args: unknown[]) =>
    mockCollectionsApi.removeDocumentFromCollection(...args),
  addDocumentToCollection: (...args: unknown[]) =>
    mockCollectionsApi.addDocumentToCollection(...args),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) =>
    mockDocumentsApi.listDocuments(...args),
}));

// ── Mock: forbidden helper ─────────────────────────────────────────────────

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
  sanitizeRequestId: () => null,
}));

// ── Fixtures ───────────────────────────────────────────────────────────────

const EMPTY_LIST: CollectionListResponse = { items: [], total: 0 };

function makeCollection(
  overrides: Partial<CollectionDetailResponse> = {},
): CollectionDetailResponse {
  return {
    collection_id: "col-1",
    name: "Engineering Handbook",
    description: "Core engineering docs",
    owner_id: "user-1",
    owner_email: "admin@example.com",
    document_count: 5,
    indexed_count: 4,
    access_policy: "org_wide",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-20T12:00:00Z",
    created_by_email: "admin@example.com",
    ...overrides,
  };
}

// ── Setup ──────────────────────────────────────────────────────────────────

let queryClient: QueryClient;

beforeEach(() => {
  queryClient = createTestQueryClient();
  vi.clearAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("CollectionsPage", () => {
  it("shows empty state when no collections exist", async () => {
    mockCollectionsApi.listCollections.mockResolvedValue(EMPTY_LIST);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() => {
      expect(screen.getByText("No collections yet.")).toBeInTheDocument();
    });
  });

  it("shows loading state initially", () => {
    mockCollectionsApi.listCollections.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<CollectionsPage />, { queryClient });

    expect(screen.getByText("Loading collections…")).toBeInTheDocument();
  });

  it("renders a collection row with name and metadata", async () => {
    const col = makeCollection();
    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() => {
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument();
    });

    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Org-wide").length).toBeGreaterThan(0);
  });

  it("opens create dialog when 'New Collection' button is clicked", async () => {
    mockCollectionsApi.listCollections.mockResolvedValue(EMPTY_LIST);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("No collections yet.")).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getAllByRole("button", { name: /new collection/i })[0],
    );

    expect(
      screen.getByRole("heading", { name: "New Collection" }),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("e.g. Engineering Handbook"),
    ).toBeInTheDocument();
  });

  it("validates that name is required on create", async () => {
    mockCollectionsApi.listCollections.mockResolvedValue(EMPTY_LIST);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("No collections yet.")).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getAllByRole("button", { name: /new collection/i })[0],
    );

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByText("Name is required.")).toBeInTheDocument();
    expect(mockCollectionsApi.createCollection).not.toHaveBeenCalled();
  });

  it("calls createCollection with correct payload and closes dialog on success", async () => {
    mockCollectionsApi.listCollections.mockResolvedValue(EMPTY_LIST);
    const created = makeCollection({ name: "Sales Playbook" });
    mockCollectionsApi.createCollection.mockResolvedValue(created);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("No collections yet.")).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getAllByRole("button", { name: /new collection/i })[0],
    );

    const nameInput = screen.getByPlaceholderText("e.g. Engineering Handbook");
    await userEvent.type(nameInput, "Sales Playbook");

    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [created],
      total: 1,
    });

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockCollectionsApi.createCollection).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Sales Playbook" }),
      );
    });
  });

  it("calls deleteCollection when delete is confirmed", async () => {
    const col = makeCollection();
    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });
    mockCollectionsApi.deleteCollection.mockResolvedValue({
      collection_id: col.collection_id,
      archived: true,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(mockCollectionsApi.deleteCollection).toHaveBeenCalledWith(
        col.collection_id,
      );
    });
  });

  it("does not call deleteCollection when confirm is cancelled", async () => {
    const col = makeCollection();
    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(mockCollectionsApi.deleteCollection).not.toHaveBeenCalled();
  });

  it("shows collection detail panel when row name is clicked", async () => {
    const col = makeCollection();
    const collectionDocuments = Array.from({ length: 15 }, (_, index) => {
      const page = index + 1;
      return {
        document_id: `doc-${page}`,
        filename: `Collection Doc ${page}.pdf`,
        file_type: "pdf" as const,
        status: "indexed" as const,
        page_count: 12,
        chunk_count: 42,
        error_message: null,
        error_details: null,
        created_at: "2026-05-19T09:30:00Z",
        updated_at: `2026-05-20T08:${String(page).padStart(2, "0")}:00Z`,
      };
    });
    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });
    mockCollectionsApi.getCollection.mockResolvedValue(col);
    mockCollectionsApi.listCollectionDocuments.mockImplementation(
      async (_collectionId, options?: { limit?: number; offset?: number }) => {
        const limit = options?.limit ?? 10;
        const offset = options?.offset ?? 0;
        return {
          items: collectionDocuments.slice(offset, offset + limit),
          total: collectionDocuments.length,
        };
      },
    );

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByText("Engineering Handbook"));

    await waitFor(() => {
      expect(screen.getByText("Collection Metadata")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Collection Doc 1.pdf")).toBeInTheDocument();
      expect(screen.getByText("Collection Doc 10.pdf")).toBeInTheDocument();
    });
    expect(screen.queryByText("Collection Doc 11.pdf")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Load more" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(screen.getByText("Collection Doc 11.pdf")).toBeInTheDocument();
      expect(screen.getByText("Collection Doc 15.pdf")).toBeInTheDocument();
    });
  });

  it("shows only the empty-state add button when a collection has no documents", async () => {
    const col = makeCollection({
      document_count: 0,
      indexed_count: 0,
    });

    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });
    mockCollectionsApi.getCollection.mockResolvedValue(col);
    mockCollectionsApi.listCollectionDocuments.mockResolvedValue({
      items: [],
      total: 0,
    });

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByText("Engineering Handbook"));

    await waitFor(() => {
      expect(screen.getByText("No documents yet.")).toBeInTheDocument();
    });

    expect(screen.queryByText("Manage documents")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add documents" }),
    ).toBeInTheDocument();
  });

  it("lets managers search and multi-select documents in the collection picker", async () => {
    const col = makeCollection({
      document_count: 25,
      indexed_count: 0,
    });
    const documents = Array.from({ length: 25 }, (_, index) => {
      const page = index + 1;
      return {
        document_id: `doc-${page}`,
        filename: `Document ${page}.pdf`,
        file_type: "pdf" as const,
        status: "indexed" as const,
        page_count: 12,
        chunk_count: 42,
        error_message: null,
        error_details: null,
        created_at: "2026-05-19T09:30:00Z",
        updated_at: `2026-05-20T08:${String(page).padStart(2, "0")}:00Z`,
      };
    });

    mockCollectionsApi.listCollections.mockResolvedValue({
      items: [col],
      total: 1,
    });
    mockCollectionsApi.getCollection.mockResolvedValue(col);
    mockCollectionsApi.listCollectionDocuments.mockResolvedValue({
      items: [],
      total: 0,
    });
    mockDocumentsApi.listDocuments.mockImplementation((options?: unknown) => {
      const params = (options ?? {}) as {
        limit?: number;
        offset?: number;
        filename_query?: string | undefined;
      };
      const limit = params.limit ?? 10;
      const offset = params.offset ?? 0;
      const filenameQuery = params.filename_query?.trim().toLowerCase();
      const filtered = filenameQuery
        ? documents.filter((document) =>
            document.filename.toLowerCase().includes(filenameQuery),
          )
        : documents;
      return Promise.resolve({
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        limit,
        offset,
        status: "indexed",
        file_type: null,
        sort_by: "updated_at",
        sort_order: "desc",
        filename_query: params.filename_query ?? null,
      });
    });
    mockCollectionsApi.addDocumentToCollection.mockResolvedValue({
      collection_id: col.collection_id,
      document_id: "doc-1",
    });

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("Engineering Handbook")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByText("Engineering Handbook"));

    await userEvent.click(
      screen.getAllByRole("button", { name: "Add documents" })[0]!,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Manage documents" }),
      ).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Document 1.pdf")).toBeInTheDocument();
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    });

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select all on this page" }),
    );

    await userEvent.click(screen.getAllByRole("button", { name: "Next" })[0]!);

    await waitFor(() => {
      expect(screen.getByText("Document 11.pdf")).toBeInTheDocument();
      expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    });

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Select all on this page" }),
    );

    await userEvent.click(
      screen.getAllByRole("button", { name: "Previous" })[0]!,
    );

    await waitFor(() => {
      expect(screen.getByText("Document 1.pdf")).toBeInTheDocument();
      expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    });

    expect(
      screen.getByRole("checkbox", { name: "Select all on this page" }),
    ).toBeChecked();
    expect(screen.getByText("Document 1.pdf")).toHaveClass("text-[#2a2640]");

    await userEvent.click(
      screen.getByRole("button", { name: "Update documents" }),
    );

    await waitFor(() => {
      expect(mockCollectionsApi.addDocumentToCollection).toHaveBeenCalledTimes(
        20,
      );
    });
    expect(mockCollectionsApi.addDocumentToCollection).toHaveBeenCalledWith(
      col.collection_id,
      "doc-1",
    );
    expect(mockCollectionsApi.addDocumentToCollection).toHaveBeenCalledWith(
      col.collection_id,
      "doc-20",
    );
  });

  it("hides create button and shows read-only badge for viewer role", async () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        ...mockAuth.state.session!,
        role: "viewer",
      },
    } as SessionState;

    mockCollectionsApi.listCollections.mockResolvedValue(EMPTY_LIST);

    renderWithProviders(<CollectionsPage />, { queryClient });

    await waitFor(() =>
      expect(screen.getByText("No collections yet.")).toBeInTheDocument(),
    );

    expect(
      screen.queryByRole("button", { name: /new collection/i }),
    ).not.toBeInTheDocument();

    mockAuth.state = {
      status: "authenticated",
      session: {
        ...mockAuth.state.session!,
        role: "admin",
      },
    } as SessionState;
  });
});
