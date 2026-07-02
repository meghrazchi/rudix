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
import userEvent from "@testing-library/user-event";
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

const chunkRequests: Array<{ offset: number; includeFullText: boolean }> = [];
const reindexRequests: Array<unknown> = [];
const indexedChunks = Array.from({ length: 9 }, (_, index) => ({
  chunk_id: `chunk-${index + 1}`,
  page_number: index + 1,
  chunk_index: index + 1,
  token_count: 20 + index,
  embedding_model: "text-embedding-3-small",
  index_version: "v1",
  section_path: `Handbook > Section ${index + 1}`,
  language: "en",
  chunk_level: 0,
  child_count: 0,
  source_start_offset: index * 200,
  source_end_offset: index * 200 + 160,
  text_preview: `Preview ${index + 1}`,
  text: `Full text ${index + 1}`,
  created_at: "2026-05-15T12:00:00Z",
}));

const server = setupServer(
  http.get(`${apiBaseUrl}/documents/:documentId`, async ({ params }) => {
    const documentId = String(params.documentId);
    if (documentId === "doc-failed") {
      return HttpResponse.json({
        document_id: "doc-failed",
        filename: "failed.pdf",
        file_type: "pdf",
        status: "failed",
        page_count: 5,
        chunk_count: 0,
        checksum: "sum-failed",
        error_message: "Processing failed",
        error_details: {
          stage: "qdrant",
          code: "QDRANT_UPSERT_ERROR",
          category: "unexpected",
          retryable: false,
          message: "qdrant upsert failed",
        },
        lifecycle_timeline: [
          {
            step: "index",
            label: "Index",
            description: "Upsert embedded chunks into vector storage.",
            status: "failed",
            document_id: "doc-failed",
            pipeline_run_id: "run-failed",
            pipeline_type: "document.process",
            started_at: "2026-05-15T10:58:00Z",
            completed_at: "2026-05-15T11:00:00Z",
            duration_ms: 120000,
            logs: ["qdrant upsert failed"],
          },
        ],
        created_at: "2026-05-14T10:00:00Z",
        updated_at: "2026-05-15T11:00:00Z",
      });
    }

    return HttpResponse.json({
      document_id: "doc-indexed",
      filename: "indexed.pdf",
      file_type: "pdf",
      status: "indexed",
      page_count: 9,
      chunk_count: 80,
      checksum: "sum-indexed",
      error_message: null,
      error_details: null,
      language: "en",
      chunking_diagnostics: {
        strategy: "adaptive_hybrid",
        selected_strategy: "page_aware",
        profile_version: "1.0",
        profile_source: "custom_profile",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        embedding_model: "text-embedding-3-small",
        index_version: "v1",
        ocr_applied: true,
        hierarchical_mode: false,
        parent_chunk_count: null,
        child_chunk_count: null,
        reason_codes: ["pdf_ocr_applied"],
        adaptive_signals: {
          file_type: "pdf",
          page_count: 9,
          total_token_count: 5200,
          ocr_applied: true,
          heading_density: 0.3,
          avg_chars_per_page: null,
          avg_paragraph_tokens: null,
        },
        token_distribution: {
          min_tokens: 120,
          max_tokens: 260,
          avg_tokens: 188.5,
          total_tokens: 7917,
        },
      },
      lifecycle_timeline: [
        {
          step: "index",
          label: "Index",
          description: "Upsert embedded chunks into vector storage.",
          status: "completed",
          document_id: "doc-indexed",
          pipeline_run_id: "run-indexed",
          pipeline_type: "document.process",
          started_at: "2026-05-15T10:55:00Z",
          completed_at: "2026-05-15T11:00:00Z",
          duration_ms: 300000,
          logs: ["upserted 80 chunks"],
        },
      ],
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-15T11:00:00Z",
    });
  }),
  http.get(`${apiBaseUrl}/documents/:documentId/status`, async ({ params }) => {
    const documentId = String(params.documentId);
    if (documentId === "doc-failed") {
      return HttpResponse.json({
        document_id: "doc-failed",
        status: "failed",
        error_message: "Processing failed",
        error_details: {
          stage: "qdrant",
          code: "QDRANT_UPSERT_ERROR",
          category: "unexpected",
          retryable: false,
          message: "qdrant upsert failed",
        },
        updated_at: "2026-05-15T11:00:00Z",
      });
    }
    return HttpResponse.json({
      document_id: "doc-indexed",
      status: "indexed",
      error_message: null,
      error_details: null,
      updated_at: "2026-05-15T11:00:00Z",
    });
  }),
  http.get(
    `${apiBaseUrl}/documents/:documentId/chunks`,
    async ({ params, request }) => {
      const documentId = String(params.documentId);
      const url = new URL(request.url);
      const limit = Number.parseInt(url.searchParams.get("limit") ?? "8", 10);
      const offset = Number.parseInt(url.searchParams.get("offset") ?? "0", 10);
      const includeFullText =
        url.searchParams.get("include_full_text") === "true";
      chunkRequests.push({ offset, includeFullText });

      if (documentId === "doc-failed") {
        return HttpResponse.json({
          document_id: documentId,
          items: [],
          total: 0,
          limit,
          offset,
          include_full_text: includeFullText,
        });
      }

      const pageItems = indexedChunks
        .slice(offset, offset + limit)
        .map((chunk) => ({
          ...chunk,
          text: includeFullText ? chunk.text : null,
        }));
      return HttpResponse.json({
        document_id: documentId,
        items: pageItems,
        total: indexedChunks.length,
        limit,
        offset,
        include_full_text: includeFullText,
      });
    },
  ),
  http.get(`${apiBaseUrl}/admin/chunking-profiles/strategies`, () =>
    HttpResponse.json({
      strategies: [
        {
          name: "adaptive_hybrid",
          display_name: "Adaptive Hybrid",
          description: "Adaptive default.",
          suitable_for: ["mixed content"],
          requires_page_structure: false,
          supports_hierarchical: false,
        },
      ],
      default_config: {
        strategy: "adaptive_hybrid",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        language: null,
        min_tokens: 88,
        strategy_options: {},
      },
      feature_chunking_profiles_enabled: true,
    }),
  ),
  http.get(`${apiBaseUrl}/admin/chunking-profiles`, () =>
    HttpResponse.json({
      profiles: [
        {
          profile_id: "profile-1",
          organization_id: "org-1",
          name: "Operations Default",
          slug: "operations-default",
          config: {
            strategy: "adaptive_hybrid",
            chunk_size_tokens: 700,
            chunk_overlap_tokens: 120,
            language: "en",
            min_tokens: 88,
            strategy_options: {},
          },
          is_default: true,
          is_system: false,
          created_at: "2026-05-20T08:00:00Z",
          updated_at: "2026-05-20T08:00:00Z",
          created_by_user_id: "u-1",
          updated_by_user_id: "u-1",
        },
      ],
      total: 1,
      has_org_default: true,
    }),
  ),
  http.post(
    `${apiBaseUrl}/documents/:documentId/reindex`,
    async ({ request }) => {
      reindexRequests.push(await request.json());
      return HttpResponse.json(
        {
          document_id: "doc-indexed",
          status: "processing",
          queue_status: "queued",
        },
        { status: 202 },
      );
    },
  ),
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

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  window.localStorage.clear();
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  chunkRequests.length = 0;
  reindexRequests.length = 0;
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
  Object.defineProperty(window, "confirm", {
    writable: true,
    value: vi.fn(() => true),
  });
});

describe("DocumentDetailPage MSW", () => {
  it("loads indexed document detail metadata", async () => {
    renderPage("doc-indexed");

    expect(
      await screen.findByRole("heading", { name: "indexed.pdf" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Lifecycle timeline")).toBeInTheDocument();
    expect(screen.getByText("Upserted to Qdrant")).toBeInTheDocument();
    expect(screen.getByText("Ready for chat")).toBeInTheDocument();
    expect(screen.getByText("upserted 80 chunks")).toBeInTheDocument();
    expect(screen.getByText("Document preview")).toBeInTheDocument();
    expect(screen.getByText("View Original PDF")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Chunking diagnostics" }),
    ).toBeInTheDocument();
    expect(screen.getByText("pdf_ocr_applied")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));
    expect(await screen.findByText("Chunk #1")).toBeInTheDocument();
    expect(await screen.findByText("Preview 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask in Chat" })).toHaveAttribute(
      "href",
      "/chat?document_id=doc-indexed",
    );
  });

  it("loads failed document safe message and structured details", async () => {
    renderPage("doc-failed");

    expect(
      await screen.findByRole("heading", { name: "failed.pdf" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Processing error")).toBeInTheDocument();
    expect(screen.getByText(/QDRANT_UPSERT_ERROR/)).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Ask in Chat" }),
    ).not.toBeInTheDocument();
  });

  it("paginates chunk preview results", async () => {
    renderPage("doc-indexed");

    await screen.findByRole("heading", { name: "indexed.pdf" });
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));
    expect(await screen.findByText("Chunk #1")).toBeInTheDocument();
    expect(screen.getByText("Chunk #8")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Chunk #9")).toBeInTheDocument();
    expect(
      chunkRequests.some(
        (request) => request.offset === 8 && request.includeFullText === false,
      ),
    ).toBe(true);
  });

  it("refetches and shows full chunk text when toggle is enabled", async () => {
    renderPage("doc-indexed");

    await screen.findByRole("heading", { name: "indexed.pdf" });
    await userEvent.click(screen.getByRole("tab", { name: /chunks/i }));
    expect(await screen.findByText("Preview 1")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("checkbox", { name: /include full chunk text/i }),
    );

    expect(await screen.findByText("Full text 1")).toBeInTheDocument();
    expect(
      chunkRequests.some(
        (request) => request.offset === 0 && request.includeFullText,
      ),
    ).toBe(true);
  });
});
