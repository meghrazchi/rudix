import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DocumentDetailPage } from "@/components/documents/DocumentDetailPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const chunks = [
  {
    chunk_id: "cited-chunk",
    page_number: 4,
    chunk_index: 3,
    token_count: 120,
    embedding_model: "text-embedding-3-small",
    index_version: "v1",
    text_preview: "The cited passage text lives here.",
    text: null,
    created_at: "2026-05-20T08:10:00Z",
  },
  {
    chunk_id: "other-chunk",
    page_number: 5,
    chunk_index: 4,
    token_count: 98,
    embedding_model: "text-embedding-3-small",
    index_version: "v1",
    text_preview: "An unrelated passage.",
    text: null,
    created_at: "2026-05-20T08:11:00Z",
  },
];

const server = setupServer(
  http.get(`${apiBaseUrl}/documents/:documentId`, () =>
    HttpResponse.json({
      document_id: "doc-indexed",
      filename: "Policy.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 10,
      chunk_count: 2,
      checksum: "sha256:test",
      error_message: null,
      error_details: null,
      lifecycle_timeline: [],
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T11:00:00Z",
    }),
  ),
  http.get(`${apiBaseUrl}/documents/:documentId/status`, () =>
    HttpResponse.json({
      document_id: "doc-indexed",
      status: "indexed",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-15T11:00:00Z",
    }),
  ),
  http.get(`${apiBaseUrl}/documents/:documentId/chunks`, ({ request }) => {
    const url = new URL(request.url);
    const limit = Number.parseInt(url.searchParams.get("limit") ?? "8", 10);
    const offset = Number.parseInt(url.searchParams.get("offset") ?? "0", 10);
    return HttpResponse.json({
      document_id: "doc-indexed",
      items: chunks.slice(offset, offset + limit),
      total: chunks.length,
      limit,
      offset,
      include_full_text: false,
    });
  }),
);

function renderPage(documentId: string) {
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

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  Element.prototype.scrollIntoView = vi.fn();
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
});

describe("DocumentDetailPage — citation deep-link support", () => {
  it("does not show citation callout when no chunk_id in URL", async () => {
    mockNavigation.searchParams = new URLSearchParams("back=%2Fchat");

    renderPage("doc-indexed");

    await screen.findByRole("heading", { name: "Policy.pdf" });
    expect(screen.queryByText("Citation evidence")).not.toBeInTheDocument();
  });

  it("shows the citation callout card when chunk_id is in URL", async () => {
    mockNavigation.searchParams = new URLSearchParams(
      "chunk_id=cited-chunk&snippet=The+cited+passage+text+lives+here.&back=%2Fchat",
    );

    renderPage("doc-indexed");

    expect(await screen.findByText("Citation evidence")).toBeInTheDocument();
    expect(
      screen.getAllByText("The cited passage text lives here.").length,
    ).toBeGreaterThan(0);
  });

  it("shows truncated chunk ID in the citation callout", async () => {
    mockNavigation.searchParams = new URLSearchParams(
      "chunk_id=cited-chunk&back=%2Fchat",
    );

    renderPage("doc-indexed");

    await screen.findByText("Citation evidence");
    // chunk ID is displayed truncated with an ellipsis
    expect(screen.getByText(/Chunk: cited-ch/)).toBeInTheDocument();
  });

  it("auto-selects the chunks tab when chunk_id is present", async () => {
    mockNavigation.searchParams = new URLSearchParams(
      "chunk_id=cited-chunk&back=%2Fchat",
    );

    renderPage("doc-indexed");

    // Chunks tab content should be visible without clicking the tab
    expect(await screen.findByText("Chunk #3")).toBeInTheDocument();
  });

  it("marks the cited chunk with the 'cited' badge", async () => {
    mockNavigation.searchParams = new URLSearchParams(
      "chunk_id=cited-chunk&back=%2Fchat",
    );

    renderPage("doc-indexed");

    // The cited badge should appear next to the highlighted chunk
    expect(await screen.findByText("cited")).toBeInTheDocument();
  });

  it("hides chunk pagination controls when in citation deep-link mode", async () => {
    mockNavigation.searchParams = new URLSearchParams(
      "chunk_id=cited-chunk&back=%2Fchat",
    );

    renderPage("doc-indexed");

    await screen.findByText("Citation evidence");
    await screen.findByText("Chunk #3");

    expect(
      screen.queryByRole("button", { name: /previous/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /next/i }),
    ).not.toBeInTheDocument();
  });
});
