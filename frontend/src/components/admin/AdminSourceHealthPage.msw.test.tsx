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
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminSourceHealthPage } from "@/components/admin/AdminSourceHealthPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

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

let reindexCallCount = 0;
let sourcesRequestCount = 0;

const SUMMARY = {
  total_sources: 5,
  indexed: 3,
  failed_indexing: 1,
  pending: 1,
  ocr_required: 1,
  ocr_low_confidence: 1,
  table_extraction_warnings: 0,
  missing_metadata: 0,
  stale: 0,
  deprecated: 0,
  expired: 0,
  unreviewed: 0,
  needs_review: 0,
  generated_at: "2026-08-19T00:00:00Z",
};

const CHARTS = {
  status_distribution: [{ status: "indexed", count: 3 }],
  indexing_failures: [],
  stale_by_collection: [],
  ocr_quality_distribution: [],
  review_needs_by_owner: [],
  connector_freshness: [],
  generated_at: "2026-08-19T00:00:00Z",
};

function sourcesResponse() {
  return {
    rows: [
      {
        source_type: "file",
        source_id: "doc-1",
        source_name: "handbook.pdf",
        connector_name: null,
        collection_id: null,
        collection_name: null,
        owner_id: "user-1",
        owner_name: "Ada Lovelace",
        status: "indexed",
        last_indexed_at: "2026-08-15T00:00:00Z",
        last_updated_at: "2026-08-16T00:00:00Z",
        freshness: "fresh",
        trust_status: "current",
        ocr_quality: "high",
        review_status: "current",
        graph_indexed: "completed",
        missing_metadata: false,
        error_message: null,
        available_actions: ["reindex", "assign_reviewer", "open_document"],
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
  };
}

const server = setupServer(
  http.get(`${apiBaseUrl}/auth/effective-permissions`, () =>
    HttpResponse.json({
      permissions: ["documents:manage", "collections:manage"],
      role: "admin",
      custom_role_id: null,
    }),
  ),
  http.get(`${apiBaseUrl}/admin/source-health/summary`, () =>
    HttpResponse.json(SUMMARY),
  ),
  http.get(`${apiBaseUrl}/admin/source-health/charts`, () =>
    HttpResponse.json(CHARTS),
  ),
  http.get(`${apiBaseUrl}/admin/source-health/sources`, () => {
    sourcesRequestCount += 1;
    return HttpResponse.json(sourcesResponse());
  }),
  http.post(`${apiBaseUrl}/documents/doc-1/reindex`, () => {
    reindexCallCount += 1;
    return HttpResponse.json({
      document_id: "doc-1",
      status: "processing",
      queue_status: "queued",
    });
  }),
);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminSourceHealthPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  reindexCallCount = 0;
  sourcesRequestCount = 0;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;

  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "access-token",
    },
  };
});

describe("AdminSourceHealthPage MSW", () => {
  it("loads summary, charts, and the source table over the network", async () => {
    renderPage();

    await screen.findByText("Source health");
    await screen.findByText("Total sources");
    await screen.findByText("handbook.pdf");
    expect(sourcesRequestCount).toBe(1);
  });

  it("re-indexes a document and refetches the source list", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("handbook.pdf");
    await user.click(await screen.findByText("Re-index"));

    await waitFor(() => {
      expect(reindexCallCount).toBe(1);
    });
    await waitFor(() => {
      expect(sourcesRequestCount).toBe(2);
    });
  });

  it("shows a forbidden state and makes no admin requests for non-admin roles", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-user",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "access-token",
      },
    };
    renderPage();

    await screen.findByText("Admin access restricted");
    expect(sourcesRequestCount).toBe(0);
  });
});
