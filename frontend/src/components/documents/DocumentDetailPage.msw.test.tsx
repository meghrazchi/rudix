import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
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

describe("DocumentDetailPage MSW", () => {
  it("loads indexed document detail metadata", async () => {
    renderPage("doc-indexed");

    expect(await screen.findByText("indexed.pdf")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle timeline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask in Chat" })).toHaveAttribute(
      "href",
      "/chat?document_id=doc-indexed",
    );
  });

  it("loads failed document safe message and structured details", async () => {
    renderPage("doc-failed");

    expect(await screen.findByText("failed.pdf")).toBeInTheDocument();
    expect(screen.getByText("Processing error")).toBeInTheDocument();
    expect(screen.getByText(/QDRANT_UPSERT_ERROR/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ask in Chat" })).not.toBeInTheDocument();
  });
});
