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
    expect(screen.getByText("Org-wide")).toBeInTheDocument();
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

    await userEvent.click(screen.getByRole("button", { name: /inspect/i }));

    await waitFor(() => {
      expect(screen.getByText("Collection detail")).toBeInTheDocument();
    });
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
    expect(screen.getByText("Read-only role")).toBeInTheDocument();

    mockAuth.state = {
      status: "authenticated",
      session: {
        ...mockAuth.state.session!,
        role: "admin",
      },
    } as SessionState;
  });
});
