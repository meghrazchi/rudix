import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
let observedRunPayload: {
  evaluation_set_id: string;
  config?: {
    top_k?: number;
    rerank?: boolean;
    model_name?: string | null;
    selected_document_ids?: string[];
    metric_options?: Record<string, unknown>;
  };
} | null = null;

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
  http.post(`${apiBaseUrl}/evaluations/run`, async ({ request }) => {
    const payload = (await request.json()) as {
      evaluation_set_id: string;
      config?: {
        top_k?: number;
        rerank?: boolean;
        model_name?: string | null;
        selected_document_ids?: string[];
        metric_options?: Record<string, unknown>;
      };
    };
    observedRunPayload = payload;
    return HttpResponse.json(
      {
        evaluation_run_id: "run-msw-1",
        status: "queued",
      },
      { status: 202 },
    );
  }),
  http.get(`${apiBaseUrl}/evaluations/runs/:runId`, async ({ params }) =>
    HttpResponse.json({
      evaluation_run_id: String(params.runId),
      evaluation_set_id: "set-1",
      status: "queued",
      config: {},
      summary: null,
      failure_reason: null,
      failure_type: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-05-16T12:00:00Z",
      updated_at: "2026-05-16T12:00:00Z",
      results: {
        items: [],
        total: 0,
        limit: 200,
        offset: 0,
      },
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
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  process.env.NEXT_PUBLIC_EVALUATION_RUN_POLL_INTERVAL_MS = "20";
  process.env.NEXT_PUBLIC_EVALUATION_RESULTS_PAGE_SIZE = "2";
  mockNavigation.searchParams = new URLSearchParams();
  mockNavigation.push.mockReset();
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
  observedRunPayload = null;
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

  it("queues a run and redirects to run detail/progress view", async () => {
    renderPage();

    await screen.findByRole("button", { name: "Run evaluation" });
    await userEvent.click(screen.getByRole("button", { name: "Run evaluation" }));

    await userEvent.type(
      screen.getByPlaceholderText("Optional backend-supported model identifier"),
      "custom-eval-model",
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /policy\.pdf/i }));
    fireEvent.change(screen.getByLabelText("Metric options (JSON object)"), {
      target: { value: '{"faithfulness":true,"max_latency_ms":900}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }));

    await waitFor(() => {
      expect(observedRunPayload).toEqual({
        evaluation_set_id: "set-1",
        config: {
          top_k: 5,
          rerank: true,
          model_name: "custom-eval-model",
          selected_document_ids: ["doc-1"],
          metric_options: { faithfulness: true, max_latency_ms: 900 },
        },
      });
      expect(mockNavigation.push).toHaveBeenCalledWith("/evaluations/runs/run-msw-1");
    });
  });

  it("shows actionable 409 conflict error and preserves run form state", async () => {
    server.use(
      http.post(`${apiBaseUrl}/evaluations/run`, async () =>
        HttpResponse.json({ detail: "active run exists" }, { status: 409 }),
      ),
    );

    renderPage();

    await screen.findByRole("button", { name: "Run evaluation" });
    await userEvent.click(screen.getByRole("button", { name: "Run evaluation" }));
    await userEvent.type(
      screen.getByPlaceholderText("Optional backend-supported model identifier"),
      "retry-model",
    );
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }));

    expect(
      await screen.findByText(
        "An evaluation run is already active for this set. Open the existing run or wait for completion.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("retry-model")).toBeInTheDocument();
    expect(mockNavigation.push).not.toHaveBeenCalled();
  });

  it("polls queued run detail until completed and renders summary metrics", async () => {
    let runDetailRequests = 0;
    server.use(
      http.get(`${apiBaseUrl}/evaluations/runs/:runId`, async ({ params }) => {
        runDetailRequests += 1;
        if (runDetailRequests < 2) {
          return HttpResponse.json({
            evaluation_run_id: String(params.runId),
            evaluation_set_id: "set-1",
            status: "queued",
            config: {},
            summary: null,
            failure_reason: null,
            failure_type: null,
            started_at: null,
            completed_at: null,
            created_at: "2026-05-16T12:00:00Z",
            updated_at: "2026-05-16T12:00:00Z",
            results: {
              items: [],
              total: 2,
              limit: 200,
              offset: 0,
            },
          });
        }

        return HttpResponse.json({
          evaluation_run_id: String(params.runId),
          evaluation_set_id: "set-1",
          status: "completed",
          config: { top_k: 5, rerank: true },
          summary: {
            question_total_count: 2,
            question_success_count: 2,
            question_failure_count: 0,
            retrieval_hit_rate: 1.0,
            context_precision: 0.85,
            context_recall: 0.9,
            faithfulness_score: 0.88,
            answer_relevance_score: 0.84,
            citation_accuracy_score: 0.86,
            refusal_accuracy: null,
            latency_ms_average: 240,
            cost_usd_total: 0.12,
          },
          failure_reason: null,
          failure_type: null,
          started_at: "2026-05-16T12:00:00Z",
          completed_at: "2026-05-16T12:00:30Z",
          created_at: "2026-05-16T12:00:00Z",
          updated_at: "2026-05-16T12:00:30Z",
          results: {
            items: [],
            total: 2,
            limit: 200,
            offset: 0,
          },
        });
      }),
    );

    renderPage("run-polling-1");

    expect(await screen.findByText("Run status: queued")).toBeInTheDocument();
    expect(await screen.findByText("Run status: completed")).toBeInTheDocument();
    expect(screen.getByText("Retrieval hit rate")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
  });

  it("renders failed run detail fields from API", async () => {
    server.use(
      http.get(`${apiBaseUrl}/evaluations/runs/:runId`, async ({ params }) =>
        HttpResponse.json({
          evaluation_run_id: String(params.runId),
          evaluation_set_id: "set-1",
          status: "failed",
          config: { top_k: 5 },
          summary: null,
          failure_reason: "Evaluator worker timeout",
          failure_type: "WorkerTimeout",
          started_at: "2026-05-16T12:00:00Z",
          completed_at: "2026-05-16T12:00:30Z",
          created_at: "2026-05-16T12:00:00Z",
          updated_at: "2026-05-16T12:00:30Z",
          results: {
            items: [],
            total: 1,
            limit: 200,
            offset: 0,
          },
        }),
      ),
    );

    renderPage("run-failed-msw");

    expect(await screen.findByText("Run status: failed")).toBeInTheDocument();
    expect(await screen.findByText(/Evaluator worker timeout/i)).toBeInTheDocument();
    expect(await screen.findByText(/\(WorkerTimeout\)/i)).toBeInTheDocument();
  });

  it("supports paginated run results with next/previous controls", async () => {
    const observedOffsets: string[] = [];
    const sourceResults = [
      {
        evaluation_result_id: "r-1",
        evaluation_question_id: "q-1",
        question: "Question one?",
        status: "completed",
        generated_answer: "Answer one",
        retrieval_score: 0.9,
        faithfulness_score: 0.9,
        citation_accuracy_score: 0.9,
        answer_relevance_score: 0.9,
        latency_ms: 100,
        metrics: {},
        failure_reason: null,
        failure_type: null,
        details: {},
        created_at: "2026-05-16T12:00:00Z",
        updated_at: "2026-05-16T12:00:00Z",
      },
      {
        evaluation_result_id: "r-2",
        evaluation_question_id: "q-2",
        question: "Question two?",
        status: "completed",
        generated_answer: "Answer two",
        retrieval_score: 0.8,
        faithfulness_score: 0.8,
        citation_accuracy_score: 0.8,
        answer_relevance_score: 0.8,
        latency_ms: 200,
        metrics: {},
        failure_reason: null,
        failure_type: null,
        details: {},
        created_at: "2026-05-16T12:00:00Z",
        updated_at: "2026-05-16T12:00:00Z",
      },
      {
        evaluation_result_id: "r-3",
        evaluation_question_id: "q-3",
        question: "Question three?",
        status: "failed",
        generated_answer: null,
        retrieval_score: null,
        faithfulness_score: null,
        citation_accuracy_score: null,
        answer_relevance_score: null,
        latency_ms: 300,
        metrics: {},
        failure_reason: "No supporting chunks found",
        failure_type: "NotFound",
        details: {},
        created_at: "2026-05-16T12:00:00Z",
        updated_at: "2026-05-16T12:00:00Z",
      },
    ];

    server.use(
      http.get(`${apiBaseUrl}/evaluations/runs/:runId`, async ({ params, request }) => {
        const url = new URL(request.url);
        const offset = Number.parseInt(url.searchParams.get("offset") ?? "0", 10);
        const limit = Number.parseInt(url.searchParams.get("limit") ?? "2", 10);
        observedOffsets.push(String(offset));
        return HttpResponse.json({
          evaluation_run_id: String(params.runId),
          evaluation_set_id: "set-1",
          status: "completed",
          config: {},
          summary: {
            question_total_count: sourceResults.length,
          },
          failure_reason: null,
          failure_type: null,
          started_at: "2026-05-16T12:00:00Z",
          completed_at: "2026-05-16T12:00:30Z",
          created_at: "2026-05-16T12:00:00Z",
          updated_at: "2026-05-16T12:00:30Z",
          results: {
            items: sourceResults.slice(offset, offset + limit),
            total: sourceResults.length,
            limit,
            offset,
          },
        });
      }),
    );

    renderPage("run-paginated-1");

    expect(await screen.findByText("Question one?")).toBeInTheDocument();
    expect(screen.getByText("Question two?")).toBeInTheDocument();
    expect(screen.queryByText("Question three?")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Question three?")).toBeInTheDocument();
    expect(screen.queryByText("Question one?")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Question one?")).toBeInTheDocument();

    expect(observedOffsets).toContain("0");
    expect(observedOffsets).toContain("2");
  });
});
