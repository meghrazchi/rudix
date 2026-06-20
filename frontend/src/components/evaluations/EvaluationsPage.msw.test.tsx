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
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
  useRouter: () => ({ push: mockNavigation.push }),
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
  http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
    HttpResponse.json({
      items: [
        {
          evaluation_set_id: "set-1",
          name: "Regression Set",
          description: "Baseline checks",
          question_count: 1,
          status: "active",
          version: 1,
          scope: {},
          created_at: "2026-05-16T10:00:00Z",
          updated_at: "2026-05-16T11:00:00Z",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    }),
  ),
  http.get(
    `${apiBaseUrl}/evaluation-sets/:setId/questions`,
    async ({ params }) =>
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
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: null,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
  ),
  http.get(`${apiBaseUrl}/evaluations/runs/:runId`, async ({ params }) =>
    HttpResponse.json({
      evaluation_run_id: String(params.runId),
      evaluation_set_id: "set-1",
      status: "completed",
      config: {},
      summary: null,
      failure_reason: null,
      failure_type: null,
      started_at: "2026-05-16T12:00:00Z",
      completed_at: "2026-05-16T12:05:00Z",
      created_at: "2026-05-16T12:00:00Z",
      updated_at: "2026-05-16T12:05:00Z",
      results: {
        items: [],
        total: 0,
        limit: 20,
        offset: 0,
      },
    }),
  ),
  http.post(`${apiBaseUrl}/evaluation-sets`, async () =>
    HttpResponse.json(
      {
        evaluation_set_id: "set-2",
        name: "Created set",
        description: null,
        question_count: 0,
        status: "active",
        version: 1,
        scope: {},
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T10:00:00Z",
      },
      { status: 201 },
    ),
  ),
  http.post(
    `${apiBaseUrl}/evaluation-sets/:setId/questions`,
    async ({ params }) =>
      HttpResponse.json(
        {
          evaluation_question_id: "q-created",
          evaluation_set_id: String(params.setId),
          question: "new",
          expected_answer: null,
          expected_document_id: null,
          expected_page_number: null,
          tags: [],
          metadata: {},
          created_at: "2026-05-16T10:00:00Z",
          updated_at: "2026-05-16T10:00:00Z",
        },
        { status: 201 },
      ),
  ),
  http.post(`${apiBaseUrl}/evaluations/run`, async () =>
    HttpResponse.json(
      {
        evaluation_run_id: "run-msw-1",
        status: "queued",
      },
      { status: 202 },
    ),
  ),
);

function renderPage(initialRunId?: string | null) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <EvaluationsPage initialRunId={initialRunId ?? null} />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  mockNavigation.searchParams = new URLSearchParams();
  mockNavigation.push.mockReset();

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

describe("EvaluationsPage states (MSW)", () => {
  it("shows loading then dataset content", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () => {
        await delay(100);
        return HttpResponse.json({
          items: [
            {
              evaluation_set_id: "set-1",
              name: "Regression Set",
              description: "Baseline checks",
              question_count: 1,
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

    expect(
      screen.getByText("Loading evaluation datasets..."),
    ).toBeInTheDocument();
    const matches = await screen.findAllByText("Regression Set");
    expect(matches.length).toBeGreaterThan(0);
  });

  it("shows unavailable backend state on 503", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
        HttpResponse.json({ detail: "down" }, { status: 503 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Evaluation backend is currently unavailable"),
    ).toBeInTheDocument();
  });

  it("shows forbidden state on 403", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluation-sets`, async () =>
        HttpResponse.json(
          { detail: "forbidden", request_id: "eval-403" },
          { status: 403 },
        ),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Evaluation access is restricted"),
    ).toBeInTheDocument();
    expect(screen.getByText("Trace ID:")).toBeInTheDocument();
  });

  it("renders run detail using route run id", async () => {
    renderPage("run-msw-1");

    expect(await screen.findByText("Run detail")).toBeInTheDocument();
    expect(screen.getByText("Case results")).toBeInTheDocument();
  });
});
