import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";
import type {
  EvaluationQuestionListResponse,
  EvaluationRunDetailResponse,
  EvaluationSetListResponse,
} from "@/lib/api/evaluations";
import type { DocumentListResponse } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listEvaluationSets: vi.fn(),
  listEvaluationQuestions: vi.fn(),
  createEvaluationSet: vi.fn(),
  createEvaluationQuestion: vi.fn(),
  runEvaluation: vi.fn(),
  getEvaluationRun: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/evaluations", () => ({
  listEvaluationSets: (...args: unknown[]) => mockApi.listEvaluationSets(...args),
  listEvaluationQuestions: (...args: unknown[]) => mockApi.listEvaluationQuestions(...args),
  createEvaluationSet: (...args: unknown[]) => mockApi.createEvaluationSet(...args),
  createEvaluationQuestion: (...args: unknown[]) => mockApi.createEvaluationQuestion(...args),
  runEvaluation: (...args: unknown[]) => mockApi.runEvaluation(...args),
  getEvaluationRun: (...args: unknown[]) => mockApi.getEvaluationRun(...args),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) => mockApi.listDocuments(...args),
}));

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

function buildSetList(): EvaluationSetListResponse {
  return {
    items: [
      {
        evaluation_set_id: "set-1",
        name: "Regression Set",
        description: "test",
        question_count: 2,
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T11:00:00Z",
      },
    ],
    total: 1,
    limit: 100,
    offset: 0,
  };
}

function buildQuestionList(): EvaluationQuestionListResponse {
  return {
    evaluation_set_id: "set-1",
    items: [
      {
        evaluation_question_id: "q-1",
        evaluation_set_id: "set-1",
        question: "What is the SLA?",
        expected_answer: "99.9%",
        expected_document_id: null,
        expected_page_number: 4,
        tags: ["sla"],
        metadata: {},
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T10:00:00Z",
      },
    ],
    total: 1,
    limit: 200,
    offset: 0,
  };
}

function buildDocuments(): DocumentListResponse {
  return {
    items: [
      {
        document_id: "doc-1",
        filename: "policy.pdf",
        file_type: "pdf",
        status: "indexed",
        page_count: 4,
        chunk_count: 8,
        error_message: null,
        error_details: null,
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T10:00:00Z",
      },
    ],
    total: 1,
    limit: 200,
    offset: 0,
    status: "indexed",
    sort_by: "updated_at",
    sort_order: "desc",
  };
}

function buildRunDetail(): EvaluationRunDetailResponse {
  return {
    evaluation_run_id: "run-1",
    evaluation_set_id: "set-1",
    status: "completed",
    config: {
      top_k: 5,
      rerank: true,
    },
    summary: {
      question_total_count: 2,
      question_success_count: 1,
      question_failure_count: 1,
      faithfulness_score: 0.82,
      answer_relevance_score: 0.78,
      citation_accuracy_score: 0.75,
      latency_ms_average: 380,
      cost_usd_total: 1.25,
    },
    failure_reason: null,
    failure_type: null,
    started_at: "2026-05-16T10:00:00Z",
    completed_at: "2026-05-16T10:02:00Z",
    created_at: "2026-05-16T10:00:00Z",
    updated_at: "2026-05-16T10:02:00Z",
    results: {
      items: [
        {
          evaluation_result_id: "r-1",
          evaluation_question_id: "q-1",
          question: "What is the SLA?",
          status: "completed",
          generated_answer: "SLA is 99.9%.",
          retrieval_score: 0.8,
          faithfulness_score: 0.82,
          citation_accuracy_score: 0.75,
          answer_relevance_score: 0.78,
          latency_ms: 380,
          metrics: {},
          failure_reason: null,
          failure_type: null,
          details: {},
          created_at: "2026-05-16T10:01:00Z",
          updated_at: "2026-05-16T10:01:00Z",
        },
        {
          evaluation_result_id: "r-2",
          evaluation_question_id: "q-2",
          question: "Where is the retention note?",
          status: "failed",
          generated_answer: null,
          retrieval_score: null,
          faithfulness_score: null,
          citation_accuracy_score: null,
          answer_relevance_score: null,
          latency_ms: null,
          metrics: {},
          failure_reason: "No supporting chunks found",
          failure_type: "NotFound",
          details: {},
          created_at: "2026-05-16T10:01:20Z",
          updated_at: "2026-05-16T10:01:20Z",
        },
      ],
      total: 2,
      limit: 200,
      offset: 0,
    },
  };
}

describe("EvaluationsPage", () => {
  beforeEach(() => {
    mockApi.listEvaluationSets.mockReset();
    mockApi.listEvaluationQuestions.mockReset();
    mockApi.createEvaluationSet.mockReset();
    mockApi.createEvaluationQuestion.mockReset();
    mockApi.runEvaluation.mockReset();
    mockApi.getEvaluationRun.mockReset();
    mockApi.listDocuments.mockReset();

    mockApi.listEvaluationSets.mockResolvedValue(buildSetList());
    mockApi.listEvaluationQuestions.mockResolvedValue(buildQuestionList());
    mockApi.listDocuments.mockResolvedValue(buildDocuments());
    mockApi.createEvaluationQuestion.mockResolvedValue({
      evaluation_question_id: "q-new",
      evaluation_set_id: "set-1",
      question: "New question?",
      expected_answer: null,
      expected_document_id: null,
      expected_page_number: null,
      tags: [],
      metadata: {},
      created_at: "2026-05-16T12:30:00Z",
      updated_at: "2026-05-16T12:30:00Z",
    });
    mockApi.createEvaluationSet.mockResolvedValue({
      evaluation_set_id: "set-2",
      name: "New Set",
      description: "new description",
      question_count: 0,
      created_at: "2026-05-16T12:00:00Z",
      updated_at: "2026-05-16T12:00:00Z",
    });
    mockApi.runEvaluation.mockResolvedValue({
      evaluation_run_id: "run-1",
      status: "queued",
    });
    mockApi.getEvaluationRun.mockResolvedValue(buildRunDetail());
  });

  it("renders run summary metrics and failed/low-score inspection controls", async () => {
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

    renderPage();

    await screen.findByRole("button", { name: "Run evaluation" });
    await userEvent.click(screen.getByRole("button", { name: "Run evaluation" }));

    await screen.findByText("Run status: completed");

    expect(screen.getAllByText("Faithfulness").length).toBeGreaterThan(0);
    expect(screen.getAllByText("82.0%").length).toBeGreaterThan(0);
    expect(screen.getByText("Answer relevance")).toBeInTheDocument();
    expect(screen.getAllByText("78.0%").length).toBeGreaterThan(0);
    expect(screen.getByText("Citation accuracy")).toBeInTheDocument();
    expect(screen.getAllByText("75.0%").length).toBeGreaterThan(0);

    expect(screen.getByRole("button", { name: "Failed/low (1)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Failed/low (1)" }));

    await waitFor(() => {
      expect(screen.getByText("No supporting chunks found")).toBeInTheDocument();
    });
  });

  it("renders permission-aware controls for viewer role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "viewer@example.com",
        role: "viewer",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();

    await screen.findByRole("button", { name: "Run evaluation" });

    expect(
      screen.getByText("Your role can view evaluation sets but only owner/admin can create new sets."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your role can inspect results but only owner/admin can run evaluations."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your role can view questions but only owner/admin can add new questions."),
    ).toBeInTheDocument();

    const runButton = screen.getByRole("button", { name: "Run evaluation" });
    expect(runButton).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Create evaluation set" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add question" })).not.toBeInTheDocument();
  });

  it("renders question create permissions for member vs admin", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-4",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-4",
      },
    };

    renderPage();
    await screen.findByText("Question management");

    expect(
      await screen.findByText("Your role can view questions but only owner/admin can add new questions."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add question" })).not.toBeInTheDocument();
  });

  it("validates question form fields before submission", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-5",
        email: "admin2@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-5",
      },
    };

    renderPage();

    await screen.findByRole("button", { name: "Add question" });

    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(await screen.findByText("Question is required.")).toBeInTheDocument();
    expect(mockApi.createEvaluationQuestion).not.toHaveBeenCalled();

    await userEvent.type(
      screen.getByPlaceholderText("What is the retention policy for invoices?"),
      "How long do we keep logs?",
    );
    await userEvent.type(screen.getByPlaceholderText("Optional"), "invalid");
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(await screen.findByText("Expected page must be a positive integer.")).toBeInTheDocument();
    expect(mockApi.createEvaluationQuestion).not.toHaveBeenCalled();

    await userEvent.clear(screen.getByPlaceholderText("Optional"));
    fireEvent.change(screen.getByLabelText("Metadata (JSON object)"), {
      target: { value: "{bad" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(await screen.findByText("Metadata must be valid JSON.")).toBeInTheDocument();
    expect(mockApi.createEvaluationQuestion).not.toHaveBeenCalled();
  });

  it("validates create set modal input and submits the set", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-3",
        email: "owner@example.com",
        role: "owner",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-3",
      },
    };

    renderPage();

    await screen.findByRole("button", { name: "Create evaluation set" });
    const setTitleMatches = await screen.findAllByText("Regression Set");
    expect(setTitleMatches.length).toBeGreaterThan(0);
    expect(screen.getByText(/Created:/i)).toBeInTheDocument();
    expect(screen.getByText(/Updated:/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create evaluation set" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create set" }));
    expect(await screen.findByText("Set name is required.")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Set name"), "Smoke test set");
    await userEvent.type(screen.getByLabelText("Description"), "Validates retrieval quality");
    await userEvent.click(screen.getByRole("button", { name: "Create set" }));

    await waitFor(() => {
      expect(mockApi.createEvaluationSet).toHaveBeenCalled();
      const [payload] = mockApi.createEvaluationSet.mock.calls[0] ?? [];
      expect(payload).toEqual({
        name: "Smoke test set",
        description: "Validates retrieval quality",
      });
    });
  });
});
