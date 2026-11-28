import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionsPage } from "@/components/collections/CollectionsPage";
import { PolicyEditor } from "@/components/collections/PolicyEditor";
import { fetchAllCollectionDocuments } from "@/components/collections/collection-documents";
import type { SessionState } from "@/lib/auth-session";
import { makePagedCollections } from "@/test/msw/handlers";
import { createTestQueryClient, renderWithProviders } from "@/test/render";

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
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state, signOut: vi.fn() }),
}));

const mockApi = vi.hoisted(() => ({
  listCollections: vi.fn(),
  listCollectionDocuments: vi.fn(),
  getCollectionPolicy: vi.fn(),
  listTeamMembers: vi.fn(),
}));

vi.mock("@/lib/api/collections", () => ({
  listCollections: (...args: unknown[]) => mockApi.listCollections(...args),
  listCollectionDocuments: (...args: unknown[]) =>
    mockApi.listCollectionDocuments(...args),
  getCollectionPolicy: (...args: unknown[]) =>
    mockApi.getCollectionPolicy(...args),
  updateCollectionPolicy: vi.fn(),
}));

vi.mock("@/lib/api/team", () => ({
  getTeamCapabilities: () => ({ listMembersEnabled: true }),
  listTeamMembers: (...args: unknown[]) => mockApi.listTeamMembers(...args),
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  isEndpointNotFoundError: () => false,
  extractRequestIdFromError: () => null,
  sanitizeRequestId: () => null,
}));

const collections = makePagedCollections(30);

function member(index: number) {
  return {
    member_id: `m-${index}`,
    user_id: `u-${index}`,
    name: `Member ${index}`,
    email: `member${index}@example.com`,
    role: "member",
    status: "active",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.listCollections.mockImplementation(
    async (options?: { limit?: number; offset?: number }) => {
      const limit = options?.limit ?? 20;
      const offset = options?.offset ?? 0;
      return {
        items: collections.slice(offset, offset + limit),
        total: collections.length,
      };
    },
  );
});

describe("CollectionsPage load more (R07-06)", () => {
  it("shows the count and appends the next offset page", async () => {
    renderWithProviders(<CollectionsPage />, {
      queryClient: createTestQueryClient(),
    });

    expect(await screen.findByText("Collection 1")).toBeInTheDocument();
    expect(screen.getByText("Showing 20 of 30")).toBeInTheDocument();
    expect(screen.queryByText("Collection 21")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Collection 30")).toBeInTheDocument();
    expect(screen.getByText("Showing 30 of 30")).toBeInTheDocument();
    expect(mockApi.listCollections).toHaveBeenLastCalledWith(
      expect.objectContaining({ limit: 20, offset: 20 }),
    );
  });
});

describe("PolicyEditor member picker (R07-06)", () => {
  it("searches members on the server and loads more", async () => {
    mockApi.getCollectionPolicy.mockResolvedValue({
      collection_id: "col-1",
      access_policy: "selected_members",
      grants: [],
    });
    mockApi.listTeamMembers.mockImplementation(
      async (params: { limit: number; offset?: number; search?: string }) => {
        const all = Array.from({ length: 60 }, (_, i) => member(i + 1));
        const matching = params.search
          ? all.filter((m) => m.name === params.search)
          : all;
        const offset = params.offset ?? 0;
        return {
          items: matching.slice(offset, offset + params.limit),
          total: matching.length,
          limit: params.limit,
          offset,
        };
      },
    );

    renderWithProviders(
      <PolicyEditor collectionId="col-1" collectionName="Engineering" />,
      { queryClient: createTestQueryClient() },
    );

    expect(await screen.findByText("Member 1")).toBeInTheDocument();
    expect(screen.getByText(/Showing 50 of 60/)).toBeInTheDocument();
    expect(mockApi.listTeamMembers).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, offset: 0 }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Member 60")).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText("Search: Members with access"),
      "Member 7",
    );
    await waitFor(() =>
      expect(mockApi.listTeamMembers).toHaveBeenCalledWith(
        expect.objectContaining({ search: "Member 7" }),
      ),
    );
    expect(await screen.findByText("Showing 1 of 1")).toBeInTheDocument();
  });
});

describe("fetchAllCollectionDocuments", () => {
  it("reads every page instead of stopping at 200 rows", async () => {
    const docs = Array.from({ length: 450 }, (_, i) => ({
      document_id: `d-${i}`,
    }));
    mockApi.listCollectionDocuments.mockImplementation(
      async (_id: string, options: { limit: number; offset?: number }) => {
        const offset = options.offset ?? 0;
        return {
          items: docs.slice(offset, offset + options.limit),
          total: docs.length,
        };
      },
    );

    const result = await fetchAllCollectionDocuments("col-1");

    expect(result.items).toHaveLength(450);
    expect(result.total).toBe(450);
    expect(mockApi.listCollectionDocuments.mock.calls).toEqual([
      ["col-1", { limit: 200 }],
      ["col-1", { limit: 200, offset: 200 }],
      ["col-1", { limit: 200, offset: 400 }],
    ]);
  });

  it("stops on an empty page", async () => {
    mockApi.listCollectionDocuments.mockResolvedValue({
      items: [],
      total: 5,
    });
    const result = await fetchAllCollectionDocuments("col-1");
    expect(result.items).toHaveLength(0);
    expect(mockApi.listCollectionDocuments).toHaveBeenCalledTimes(1);
  });
});
