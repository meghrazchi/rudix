import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

type QuestionPayload = {
  question: string;
  expected_answer?: string | null;
  expected_document_id?: string | null;
  expected_page_number?: number | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
};

let questionStore: Array<{
  evaluation_question_id: string;
  evaluation_set_id: string;
  question: string;
  expected_answer: string | null;
  expected_document_id: string | null;
  expected_page_number: number | null;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}> = [];
let observedQuestionCreatePayload: QuestionPayload | null = null;

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
      items: questionStore,
      total: questionStore.length,
      limit: 200,
      offset: 0,
    }),
  ),
  http.post(`${apiBaseUrl}/evaluation-sets/:setId/questions`, async ({ params, request }) => {
    const payload = (await request.json()) as QuestionPayload;
    observedQuestionCreatePayload = payload;
    const setId = String(params.setId);
    const created = {
      evaluation_question_id: `q-${questionStore.length + 1}`,
      evaluation_set_id: setId,
      question: payload.question,
      expected_answer: payload.expected_answer ?? null,
      expected_document_id: payload.expected_document_id ?? null,
      expected_page_number: payload.expected_page_number ?? null,
      tags: payload.tags ?? [],
      metadata: payload.metadata ?? {},
      created_at: "2026-05-16T12:00:00Z",
      updated_at: "2026-05-16T12:00:00Z",
    };
    questionStore = [...questionStore, created];
    return HttpResponse.json(created, { status: 201 });
  }),
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
        {
          document_id: "doc-2",
          filename: "draft.txt",
          file_type: "txt",
          status: "uploaded",
          page_count: 1,
          chunk_count: 0,
          error_message: null,
          error_details: null,
          created_at: "2026-05-16T10:30:00Z",
          updated_at: "2026-05-16T11:30:00Z",
        },
      ],
      total: 2,
      limit: 200,
      offset: 0,
      status: null,
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
  questionStore = [
    {
      evaluation_question_id: "q-1",
      evaluation_set_id: "set-1",
      question: "Existing question?",
      expected_answer: "Yes",
      expected_document_id: "doc-1",
      expected_page_number: 2,
      tags: ["baseline"],
      metadata: { priority: "high" },
      created_at: "2026-05-16T10:10:00Z",
      updated_at: "2026-05-16T10:10:00Z",
    },
  ];
  observedQuestionCreatePayload = null;
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

  it("lists questions and updates list after creating a new question", async () => {
    renderPage();

    expect(await screen.findByText("Existing question?")).toBeInTheDocument();
    await userEvent.type(
      screen.getByPlaceholderText("What is the retention policy for invoices?"),
      "What is the new SLA?",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Optional expected answer for quality scoring"),
      "99.95%",
    );
    await userEvent.selectOptions(screen.getByLabelText("Expected document"), "doc-2");
    await userEvent.type(screen.getByPlaceholderText("Optional"), "5");
    await userEvent.type(screen.getByPlaceholderText("invoice, policy, legal"), "sla,ops");
    fireEvent.change(screen.getByLabelText("Metadata (JSON object)"), {
      target: { value: '{"priority":"medium","owner":"qa"}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));

    await waitFor(() => {
      expect(observedQuestionCreatePayload).toEqual({
        question: "What is the new SLA?",
        expected_answer: "99.95%",
        expected_document_id: "doc-2",
        expected_page_number: 5,
        tags: ["sla", "ops"],
        metadata: { priority: "medium", owner: "qa" },
      });
    });
    expect(await screen.findByText("What is the new SLA?")).toBeInTheDocument();
  });
});
