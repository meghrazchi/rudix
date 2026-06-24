import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationsPage } from "@/components/evaluations/EvaluationsPage";
import type {
  EvaluationQuestionListResponse,
  EvaluationRunDetailResponse,
  EvaluationSetListResponse,
} from "@/lib/api/evaluations";
import type { DocumentListResponse } from "@/lib/api/documents";
import type { ChunkingProfileList } from "@/lib/schemas/chunking-profiles";
import type { SessionState } from "@/lib/auth-session";

const RUN_HISTORY_KEY = "rudix.evaluations.run-history.v1";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
  useRouter: () => ({ push: mockNavigation.push }),
}));

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
  listChunkingProfiles: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/evaluations", () => ({
  listEvaluationSets: (...args: unknown[]) =>
    mockApi.listEvaluationSets(...args),
  listEvaluationQuestions: (...args: unknown[]) =>
    mockApi.listEvaluationQuestions(...args),
  createEvaluationSet: (...args: unknown[]) =>
    mockApi.createEvaluationSet(...args),
  createEvaluationQuestion: (...args: unknown[]) =>
    mockApi.createEvaluationQuestion(...args),
  runEvaluation: (...args: unknown[]) => mockApi.runEvaluation(...args),
  getEvaluationRun: (...args: unknown[]) => mockApi.getEvaluationRun(...args),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) => mockApi.listDocuments(...args),
}));

vi.mock("@/lib/api/chunking-profiles", () => ({
  listChunkingProfiles: (...args: unknown[]) =>
    mockApi.listChunkingProfiles(...args),
}));

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

function buildSetList(): EvaluationSetListResponse {
  return {
    items: [
      {
        evaluation_set_id: "set-1",
        name: "Regression Set",
        description: "baseline",
        question_count: 2,
        status: "active",
        version: 1,
        scope: {},
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T11:00:00Z",
      },
      {
        evaluation_set_id: "set-2",
        name: "Finance Set",
        description: "finance questions",
        question_count: 1,
        status: "active",
        version: 1,
        scope: {},
        created_at: "2026-05-17T10:00:00Z",
        updated_at: "2026-05-17T11:00:00Z",
      },
    ],
    total: 2,
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
        expected_document_id: "doc-1",
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

function buildChunkingProfiles(): ChunkingProfileList {
  return {
    profiles: [
      {
        profile_id: "profile-default",
        organization_id: "org-1",
        name: "Default Recursive",
        slug: "default-recursive",
        config: {
          strategy: "token_recursive",
          chunk_size_tokens: 700,
          chunk_overlap_tokens: 120,
          language: null,
          min_tokens: null,
          strategy_options: {},
        },
        is_default: true,
        is_system: false,
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T10:00:00Z",
        created_by_user_id: "u-1",
        updated_by_user_id: "u-1",
      },
      {
        profile_id: "profile-heading",
        organization_id: "org-1",
        name: "Heading Aware",
        slug: "heading-aware",
        config: {
          strategy: "heading_aware",
          chunk_size_tokens: 900,
          chunk_overlap_tokens: 80,
          language: null,
          min_tokens: null,
          strategy_options: {},
        },
        is_default: false,
        is_system: false,
        created_at: "2026-05-16T10:00:00Z",
        updated_at: "2026-05-16T10:00:00Z",
        created_by_user_id: "u-1",
        updated_by_user_id: "u-1",
      },
    ],
    total: 2,
    has_org_default: true,
  };
}

function buildRunDetail(
  overrides?: Partial<EvaluationRunDetailResponse>,
): EvaluationRunDetailResponse {
  return {
    evaluation_run_id: "run-1",
    evaluation_set_id: "set-1",
    status: "completed",
    config: { top_k: 5, rerank: true, run_name: "Regression smoke run" },
    summary: {
      question_total_count: 2,
      question_success_count: 1,
      question_failure_count: 1,
      retrieval_hit_rate: 0.9,
      faithfulness_score: 0.8,
      answer_relevance_score: 0.82,
      citation_accuracy_score: 0.75,
      latency_ms_average: 430,
      cost_usd_total: 0.13,
      baseline_score: 0.7,
      latest_score: 0.8,
      score_delta: 0.1,
      comparison_targets: [
        {
          label: "Default Recursive",
          chunking_strategy: "token_recursive",
          profile_version: "cfg-default",
          overall_score: 0.8,
          retrieval_hit_rate: 0.9,
          citation_accuracy_score: 0.75,
          faithfulness_score: 0.82,
          chunk_count_total: 8,
          chunk_tokens_average: 140,
          not_found_rate: 0.1,
          regression_flags: [],
        },
        {
          label: "Heading Aware",
          chunking_strategy: "heading_aware",
          profile_version: "cfg-heading",
          overall_score: 0.74,
          retrieval_hit_rate: 0.82,
          citation_accuracy_score: 0.7,
          faithfulness_score: 0.78,
          chunk_count_total: 6,
          chunk_tokens_average: 170,
          not_found_rate: 0.15,
          regression_flags: [
            {
              metric: "retrieval_hit_rate",
              value: 0.82,
            },
          ],
        },
      ],
      best_by_document_type: {
        pdf: {
          label: "Default Recursive",
          score: 0.8,
        },
      },
      best_by_use_case: {
        unlabeled: {
          label: "Default Recursive",
          score: 0.8,
        },
      },
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
          metrics: { confidence_score: 0.77 },
          failure_reason: null,
          failure_type: null,
          details: {
            citations: [
              {
                document_id: "doc-1",
                chunk_id: "chunk-1",
                filename: "policy.pdf",
                page_number: 4,
              },
            ],
          },
          created_at: "2026-05-16T10:01:00Z",
          updated_at: "2026-05-16T10:01:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    },
    ...overrides,
  };
}

describe("EvaluationsPage redesign", () => {
  beforeEach(() => {
    mockNavigation.searchParams = new URLSearchParams();
    mockNavigation.push.mockReset();

    localStorage.clear();

    mockApi.listEvaluationSets.mockReset();
    mockApi.listEvaluationQuestions.mockReset();
    mockApi.createEvaluationSet.mockReset();
    mockApi.createEvaluationQuestion.mockReset();
    mockApi.runEvaluation.mockReset();
    mockApi.getEvaluationRun.mockReset();
    mockApi.listDocuments.mockReset();
    mockApi.listChunkingProfiles.mockReset();

    mockApi.listEvaluationSets.mockResolvedValue(buildSetList());
    mockApi.listEvaluationQuestions.mockResolvedValue(buildQuestionList());
    mockApi.listDocuments.mockResolvedValue(buildDocuments());
    mockApi.listChunkingProfiles.mockResolvedValue(buildChunkingProfiles());
    mockApi.runEvaluation.mockResolvedValue({
      evaluation_run_id: "run-created",
      status: "queued",
    });
    mockApi.getEvaluationRun.mockResolvedValue(buildRunDetail());

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

  it("renders redesigned sections and KPI cards for a selected run", async () => {
    renderPage("run-1");

    expect(
      await screen.findByRole("heading", {
        name: "Track RAG quality before shipping answers",
      }),
    ).toBeInTheDocument();

    expect(screen.getByText("Hit Rate @ 10")).toBeInTheDocument();
    expect(screen.getByText("Precision")).toBeInTheDocument();
    expect(screen.getByText("Faithfulness")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Evaluation Sets" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Recent Runs" }),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("Run detail")).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Case results")).toBeInTheDocument();
    expect(screen.getByText("Baseline vs latest")).toBeInTheDocument();
    expect(
      screen.getByText("Chunking strategy comparison"),
    ).toBeInTheDocument();
  });

  it("supports starting a run from the primary CTA", async () => {
    renderPage();

    await screen.findByText("Evaluation datasets");
    await userEvent.click(
      screen.getByRole("button", { name: "Start evaluation run" }),
    );

    await screen.findByRole("dialog", { name: "Start evaluation run" });
    fireEvent.change(screen.getByLabelText("Model override"), {
      target: { value: "gpt-5.4-mini" },
    });
    await userEvent.click(screen.getByLabelText(/Default Recursive/i));
    await userEvent.click(screen.getByLabelText(/Heading Aware/i));
    fireEvent.change(screen.getByLabelText("Metric options JSON"), {
      target: { value: '{"faithfulness":true}' },
    });
    fireEvent.change(screen.getByLabelText("Min retrieval hit rate"), {
      target: { value: "0.7" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Queue run" }));

    await waitFor(() => {
      expect(mockApi.runEvaluation).toHaveBeenCalledWith(
        expect.objectContaining({
          evaluation_set_id: "set-1",
          config: expect.objectContaining({
            top_k: 5,
            rerank: true,
            model_name: "gpt-5.4-mini",
            selected_document_ids: [],
            metric_options: { faithfulness: true },
            comparison_targets: [
              { chunking_profile_id: "profile-default" },
              { chunking_profile_id: "profile-heading" },
            ],
            regression_thresholds: {
              retrieval_hit_rate_min: 0.7,
            },
          }),
        }),
      );
      expect(mockNavigation.push).toHaveBeenCalledWith(
        "/evaluations/runs/run-created",
      );
    });
  });

  it("applies run status filter against available run history", async () => {
    localStorage.setItem(
      RUN_HISTORY_KEY,
      JSON.stringify([
        {
          runId: "run-failed",
          runName: "Failed run",
          datasetId: "set-1",
          datasetName: "Regression Set",
          status: "failed",
          score: 0.2,
          regressions: 2,
          startedBy: "qa@example.com",
          passRate: 0.1,
          citationAccuracy: 0.3,
          retrievalHitRate: 0.5,
          latencyMsAverage: 900,
          costUsdTotal: 0.2,
          durationMs: 1000,
          startedAt: "2026-05-17T10:00:00Z",
          completedAt: "2026-05-17T10:01:00Z",
          createdAt: "2026-05-17T10:00:00Z",
          updatedAt: "2026-05-17T10:01:00Z",
          isComparisonAvailable: false,
        },
      ]),
    );

    renderPage("run-1");

    await screen.findByText("Run inspector");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");

    const inspectorHeading = screen.getByRole("heading", {
      name: "Run inspector",
    });
    const inspectorSection = inspectorHeading.closest("section");
    expect(inspectorSection).not.toBeNull();

    if (!inspectorSection) {
      return;
    }

    expect(
      within(inspectorSection).getByText("Failed run"),
    ).toBeInTheDocument();
    expect(
      within(inspectorSection).queryByText("Regression smoke run"),
    ).not.toBeInTheDocument();
  });

  it("shows restricted actions for member role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage("run-1");

    await screen.findByText("Evaluation datasets");

    const startButton = screen.getByRole("button", {
      name: "Start evaluation run",
    });
    expect(startButton).toBeDisabled();

    expect(
      screen.queryByRole("button", { name: "New Set" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Your role can review evaluation results but only owner/admin can start new runs.",
      ),
    ).toBeInTheDocument();
  });

  it("renders empty dataset state", async () => {
    mockApi.listEvaluationSets.mockResolvedValue({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    });

    renderPage();

    expect(
      await screen.findByText("No evaluation sets yet"),
    ).toBeInTheDocument();
    expect(screen.getByText("No evaluation runs yet")).toBeInTheDocument();
  });
});
