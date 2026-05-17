import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";
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

const server = setupServer(
  http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
    HttpResponse.json({
      items: [
        {
          evaluation_set_id: "set-1",
          name: "Regression Set",
          description: "Baseline checks",
          question_count: 3,
          created_at: "2026-05-16T10:00:00Z",
          updated_at: "2026-05-16T11:00:00Z",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    }),
  ),
  http.get(`${apiBaseUrl}/evaluation-sets/:setId/questions`, async ({ params }) =>
    HttpResponse.json({
      evaluation_set_id: String(params.setId),
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    }),
  ),
  http.get(`${apiBaseUrl}/documents`, async () =>
    HttpResponse.json({
      items: [
        {
          document_id: "doc-1",
          filename: "policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 2,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-16T10:00:00Z",
          updated_at: "2026-05-16T11:00:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    }),
  ),
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
      <EvaluationsPage />
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
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "u-1",
      email: "owner@example.com",
      role: "owner",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("EvaluationsPage list states (MSW)", () => {
  it("shows loading state then renders evaluation sets", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () => {
        await delay(120);
        return HttpResponse.json({
          items: [
            {
              evaluation_set_id: "set-1",
              name: "Regression Set",
              description: "Baseline checks",
              question_count: 3,
              created_at: "2026-05-16T10:00:00Z",
              updated_at: "2026-05-16T11:00:00Z",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }),
    );

    renderPage();

    expect(screen.getByText("Loading evaluation sets...")).toBeInTheDocument();
    const matches = await screen.findAllByText("Regression Set");
    expect(matches.length).toBeGreaterThan(0);
  });

  it("shows empty state when there are no evaluation sets", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 100,
          offset: 0,
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("No evaluation sets yet. Create one to start question benchmarking."),
    ).toBeInTheDocument();
  });

  it("shows error state when evaluation set request fails", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
        HttpResponse.json({ detail: "service down" }, { status: 503 }),
      ),
    );

    renderPage();

    expect(await screen.findByText(/The service is temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
