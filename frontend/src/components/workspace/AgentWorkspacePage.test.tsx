import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentWorkspacePage } from "@/components/workspace/AgentWorkspacePage";
import type {
  AgentRunDetailResponse,
  AgentRunListItem,
  AgentRunListResponse,
  AgentRuntimeRequest,
} from "@/lib/api/agent";
import type { WorkflowPlanPreviewResponse } from "@/lib/api/workflow-planner";

// ── Mock: agent API ───────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listAgentRuns: vi.fn(),
  getAgentRun: vi.fn(),
  createAgentRun: vi.fn(),
  cancelAgentRun: vi.fn(),
  decideAgentRunApproval: vi.fn(),
  listAgentApprovals: vi.fn(),
  commentAgentRunApproval: vi.fn(),
  previewWorkflowPlan: vi.fn(),
  listCollections: vi.fn(),
  listAvailableConnectorConnections: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/agent", () => ({
  listAgentRuns: (...args: unknown[]) => mockApi.listAgentRuns(...args),
  getAgentRun: (...args: unknown[]) => mockApi.getAgentRun(...args),
  createAgentRun: (...args: unknown[]) => mockApi.createAgentRun(...args),
  cancelAgentRun: (...args: unknown[]) => mockApi.cancelAgentRun(...args),
  decideAgentRunApproval: (...args: unknown[]) =>
    mockApi.decideAgentRunApproval(...args),
  listAgentApprovals: (...args: unknown[]) =>
    mockApi.listAgentApprovals(...args),
  commentAgentRunApproval: (...args: unknown[]) =>
    mockApi.commentAgentRunApproval(...args),
}));

vi.mock("@/lib/api/workflow-planner", () => ({
  previewWorkflowPlan: (...args: unknown[]) =>
    mockApi.previewWorkflowPlan(...args),
}));

vi.mock("@/lib/api/collections", () => ({
  listCollections: (...args: unknown[]) => mockApi.listCollections(...args),
}));

vi.mock("@/lib/api/connectors", () => ({
  listAvailableConnectorConnections: (...args: unknown[]) =>
    mockApi.listAvailableConnectorConnections(...args),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) => mockApi.listDocuments(...args),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

const NOW = "2026-06-16T10:00:00.000Z";

function makeListItem(
  overrides: Partial<AgentRunListItem> = {},
): AgentRunListItem {
  return {
    run_id: "run-abc-1",
    status: "completed",
    objective: "Summarise quarterly results",
    total_cost_usd: 0.0014,
    trace_request_id: "trace-xyz",
    error_message: null,
    started_at: NOW,
    completed_at: NOW,
    cancelled_at: null,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

function makeListResponse(
  runs: AgentRunListItem[] = [],
  total?: number,
): AgentRunListResponse {
  return { runs, total: total ?? runs.length, limit: 20, offset: 0 };
}

function makeDetailResponse(
  overrides: Partial<AgentRunDetailResponse> = {},
): AgentRunDetailResponse {
  return {
    run_id: "run-abc-1",
    organization_id: "org-1",
    user_id: "user-1",
    status: "completed",
    surface: "api",
    objective: "Summarise quarterly results",
    max_steps: 12,
    max_parallel_tool_calls: 1,
    budget: {},
    costs: {},
    outcome: {
      answer: "Q3 revenue was $42M.",
      citations: [
        {
          title: "Q3 Report",
          snippet: "Q3 revenue reached $42M.",
          document_id: "doc-1",
        },
      ],
      confidence: { score: 0.91, category: "high" },
      not_found: false,
      mode: "answer",
    },
    observations: {},
    total_cost_usd: 0.0014,
    trace_request_id: "trace-xyz",
    error_message: null,
    error_details: {},
    started_at: NOW,
    completed_at: NOW,
    cancelled_at: null,
    created_at: NOW,
    updated_at: NOW,
    steps: [
      {
        step_id: "step-1",
        sequence: 1,
        step_name: "search_documents",
        status: "completed",
        inputs: { query: "quarterly results" },
        outputs: { total: 3 },
        metrics: {},
        observation: {},
        error_message: null,
        error_details: {},
        started_at: NOW,
        completed_at: NOW,
        duration_ms: 210,
        created_at: NOW,
        updated_at: NOW,
      },
    ],
    tool_calls: [
      {
        tool_call_id: "tc-1",
        agent_step_id: "step-1",
        call_id: "call-abc",
        tool_name: "fetch_document",
        surface: "api",
        effect_policy: "read_only",
        status: "completed",
        attempt_number: 1,
        arguments: { query: "quarterly results" },
        output: { total: 3 },
        error: {},
        input_size_bytes: 40,
        output_size_bytes: 60,
        latency_ms: 180,
        started_at: NOW,
        completed_at: NOW,
        created_at: NOW,
        updated_at: NOW,
      },
    ],
    approvals: [],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentWorkspacePage />
    </QueryClientProvider>,
  );
}

function makePlanPreview(
  overrides: Partial<WorkflowPlanPreviewResponse> = {},
): WorkflowPlanPreviewResponse {
  return {
    objective:
      "Build an audit evidence pack from the selected sources with citations.",
    mode: "compare",
    plan: [
      {
        step_name: "discover_documents",
        tool_name: "search_documents",
        rationale: "Find indexed accessible documents to ground the workflow.",
        arguments: { query: "audit evidence" },
      },
      {
        step_name: "grounded_answer",
        tool_name: "answer_from_context",
        rationale: "Return a grounded answer with citations and confidence.",
        arguments: { question: "Audit evidence" },
      },
    ],
    workflow_type: "audit_evidence_pack",
    planner_strategy: "comparison",
    planner_high_risk: true,
    requires_approval: false,
    requested_actions: [],
    request: {
      objective:
        "Build an audit evidence pack from the selected sources with citations.",
      mode: "compare",
      question:
        "Build an audit evidence pack from the selected sources with citations.",
      document_query:
        "Build an audit evidence pack from the selected sources with citations.",
      rerank: true,
      budget: {
        max_steps: 12,
        max_tool_calls: 30,
      },
    },
    ...overrides,
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("AgentWorkspacePage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockApi.listAgentApprovals.mockResolvedValue({ items: [], total: 0 });
    mockApi.commentAgentRunApproval.mockResolvedValue({});
    mockApi.listDocuments.mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 3,
          chunk_count: 6,
          error_message: null,
          error_details: null,
          created_at: NOW,
          updated_at: NOW,
        },
      ],
      total: 1,
      limit: 30,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    mockApi.listCollections.mockResolvedValue({
      items: [
        {
          collection_id: "collection-1",
          name: "Finance",
          description: "Finance policy set",
          owner_id: "user-1",
          owner_email: "owner@example.com",
          document_count: 2,
          indexed_count: 2,
          access_policy: "org_wide",
          is_dynamic: false,
          last_rule_evaluated_at: null,
          created_at: NOW,
          updated_at: NOW,
        },
      ],
      total: 1,
    });
    mockApi.listAvailableConnectorConnections.mockResolvedValue({
      items: [
        {
          id: "connector-1",
          provider_key: "confluence",
          provider: {
            key: "confluence",
            display_name: "Confluence",
            enabled_by_default: true,
            has_oauth: true,
            capabilities: {
              auth_type: "oauth2",
              capabilities: [],
              rate_limits: [],
              export_formats: [],
              max_page_size: null,
              notes: null,
            },
            config_schema: {
              type: "object",
              properties: {},
            },
          },
          display_name: "Confluence workspace",
          external_account_id: "acct-1",
          collection_id: null,
          status: "active",
          auth_config: { space_keys: ["ENG"] },
          last_sync_at: NOW,
          error_message: null,
          source_count: 3,
          indexed_document_count: 4,
          sync_job_count: 1,
          created_at: NOW,
          updated_at: NOW,
        },
      ],
      total: 1,
    });
    mockApi.previewWorkflowPlan.mockImplementation(
      async (payload: { request?: AgentRuntimeRequest }) =>
        makePlanPreview({
          objective:
            payload.request?.objective ??
            "Build an audit evidence pack from the selected sources with citations.",
          mode:
            (payload.request?.mode as WorkflowPlanPreviewResponse["mode"]) ??
            "compare",
          request: {
            ...(payload.request ?? {
              objective:
                "Build an audit evidence pack from the selected sources with citations.",
              mode: "compare",
              question:
                "Build an audit evidence pack from the selected sources with citations.",
              document_query:
                "Build an audit evidence pack from the selected sources with citations.",
              rerank: true,
              budget: {
                max_steps: 12,
                max_tool_calls: 30,
              },
            }),
          },
        }),
    );
  });

  describe("run list", () => {
    it("shows empty state when no runs exist", async () => {
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([]));
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("No runs yet")).toBeInTheDocument();
      });
    });

    it("renders run list items with status badge and objective", async () => {
      const run = makeListItem({ objective: "Analyse compliance docs" });
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([run]));
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Analyse compliance docs")).toBeInTheDocument();
      });
      expect(screen.getByText("completed")).toBeInTheDocument();
    });

    it("shows total count in heading", async () => {
      const runs = [
        makeListItem({ run_id: "r1", objective: "Task 1" }),
        makeListItem({ run_id: "r2", objective: "Task 2" }),
      ];
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse(runs, 42));
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ run_id: "r1" }),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText(/42 total/)).toBeInTheDocument();
      });
    });

    it("auto-selects the first run and shows its detail", async () => {
      const run = makeListItem({ objective: "First run task" });
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([run]));
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Q3 revenue was $42M.")).toBeInTheDocument();
      });
    });

    it("shows error state when list fetch fails", async () => {
      mockApi.listAgentRuns.mockRejectedValue(new Error("Network error"));
      renderPage();
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });
  });

  describe("run detail pane", () => {
    beforeEach(() => {
      mockApi.listAgentRuns.mockResolvedValue(
        makeListResponse([makeListItem()]),
      );
    });

    it("renders completed answer with citations", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Q3 revenue was $42M.")).toBeInTheDocument();
        expect(screen.getByText("Q3 Report")).toBeInTheDocument();
      });
    });

    it("renders step timeline", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("search_documents")).toBeInTheDocument();
      });
    });

    it("renders tool call row", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await screen.findByText("Q3 revenue was $42M.");
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /tool call log/i }));
      await waitFor(() => {
        expect(screen.getByText(/fetch_document/i)).toBeInTheDocument();
      });
    });

    it("renders effective policy in its own tab", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await screen.findByText("Q3 revenue was $42M.");
      const user = userEvent.setup();
      await user.click(
        screen.getByRole("button", { name: /effective policy/i }),
      );
      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: /effective policy/i }),
        ).toBeInTheDocument();
      });
    });

    it("shows failed run error message with trace ID", async () => {
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({
          status: "failed",
          error_message: "LLM provider timeout",
          trace_request_id: "trace-xyz-001",
          outcome: {},
        }),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("LLM provider timeout")).toBeInTheDocument();
        expect(screen.getByText(/trace-xyz-001/)).toBeInTheDocument();
      });
    });

    it("shows not_found state for completed run with no answer", async () => {
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({
          outcome: {
            not_found: true,
            answer: "",
            citations: [],
            confidence: {},
          },
        }),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("No answer found")).toBeInTheDocument();
      });
    });

    it("shows cost and trace ID in metrics bar", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      renderPage();
      await waitFor(() => {
        expect(screen.getByText(/trace-xyz/)).toBeInTheDocument();
      });
    });
  });

  describe("cancel run", () => {
    beforeEach(() => {
      mockApi.listAgentRuns.mockResolvedValue(
        makeListResponse([makeListItem({ status: "running" })]),
      );
    });

    it("shows cancel button for non-terminal runs", async () => {
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ status: "running" }),
      );
      renderPage();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /cancel run/i }),
        ).toBeInTheDocument();
      });
    });

    it("does not show cancel button for completed runs", async () => {
      mockApi.getAgentRun.mockResolvedValue(makeDetailResponse());
      mockApi.listAgentRuns.mockResolvedValue(
        makeListResponse([makeListItem({ status: "completed" })]),
      );
      renderPage();
      await waitFor(() => {
        expect(
          screen.queryByRole("button", { name: /cancel run/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("calls cancelAgentRun and refreshes on confirm", async () => {
      const user = userEvent.setup();
      const cancelledRun = makeDetailResponse({
        status: "cancelled",
        cancelled_at: NOW,
      });
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ status: "running" }),
      );
      mockApi.cancelAgentRun.mockResolvedValue(cancelledRun);
      mockApi.listAgentRuns.mockResolvedValue(
        makeListResponse([makeListItem({ status: "running" })]),
      );

      renderPage();
      const cancelBtn = await screen.findByRole("button", {
        name: /cancel run/i,
      });
      await user.click(cancelBtn);

      await waitFor(() => {
        expect(mockApi.cancelAgentRun).toHaveBeenCalledWith("run-abc-1");
      });
    });

    it("shows error message when cancel fails", async () => {
      const user = userEvent.setup();
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ status: "running" }),
      );
      mockApi.cancelAgentRun.mockRejectedValue(new Error("Conflict"));

      renderPage();
      const cancelBtn = await screen.findByRole("button", {
        name: /cancel run/i,
      });
      await user.click(cancelBtn);

      await waitFor(() => {
        expect(
          screen.getByText(/Conflict|Unable to cancel/i),
        ).toBeInTheDocument();
      });
    });
  });

  describe("new run form", () => {
    beforeEach(() => {
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([]));
    });

    it("renders objective input and mode buttons", async () => {
      renderPage();
      expect(
        screen.getByPlaceholderText(
          /describe what the workflow should accomplish/i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Audit evidence pack/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Preview plan/i }),
      ).toBeInTheDocument();
    });

    it("preview button is disabled when objective is empty", async () => {
      renderPage();
      const previewBtn = screen.getByRole("button", {
        name: /preview plan/i,
      });
      expect(previewBtn).toBeDisabled();
    });

    it("preview button is enabled when objective has ≥3 chars", async () => {
      const user = userEvent.setup();
      renderPage();
      const textarea = screen.getByPlaceholderText(
        /describe what the workflow should accomplish/i,
      );
      await user.type(textarea, "Summarise results");
      expect(
        screen.getByRole("button", { name: /preview plan/i }),
      ).not.toBeDisabled();
    });

    it("shows a preview before executing the workflow", async () => {
      const user = userEvent.setup();
      const newDetail = makeDetailResponse({ run_id: "run-new" });
      mockApi.createAgentRun.mockResolvedValue({
        run: { run_id: "run-new", status: "queued" },
      });
      mockApi.getAgentRun.mockResolvedValue(newDetail);
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([]));
      renderPage();
      await user.click(
        screen.getByRole("button", { name: /audit evidence pack/i }),
      );
      await user.click(
        screen.getByRole("button", { name: /policy comparison/i }),
      );
      const textarea = screen.getByPlaceholderText(
        /describe what the workflow should accomplish/i,
      );
      await user.clear(textarea);
      await user.type(textarea, "Check compliance docs");
      await user.click(screen.getByRole("button", { name: /preview plan/i }));

      await waitFor(() => {
        expect(mockApi.previewWorkflowPlan).toHaveBeenCalled();
      });
      expect(screen.getByText("Plan preview")).toBeInTheDocument();
      expect(screen.getByText("discover_documents")).toBeInTheDocument();

      await user.click(
        screen.getByRole("button", { name: /execute workflow/i }),
      );

      await waitFor(() => {
        expect(mockApi.createAgentRun).toHaveBeenCalledWith(
          expect.objectContaining({
            agentic_mode: true,
            request: expect.objectContaining({
              objective: "Check compliance docs",
              mode: "compare",
            }),
          }),
        );
      });
    });

    it("passes selected document scope through to the workflow request", async () => {
      const user = userEvent.setup();
      mockApi.createAgentRun.mockResolvedValue({
        run: { run_id: "run-scope-docs", status: "queued" },
      });
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ run_id: "run-scope-docs" }),
      );
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([]));

      renderPage();
      await user.type(
        screen.getByPlaceholderText(
          /describe what the workflow should accomplish/i,
        ),
        "Summarise selected docs",
      );
      await user.click(screen.getByRole("button", { name: /select scope/i }));
      await user.click(screen.getByRole("button", { name: /files/i }));
      await user.click(screen.getByRole("button", { name: /policy\.pdf/i }));
      await user.click(screen.getByRole("button", { name: /apply/i }));
      await user.click(screen.getByRole("button", { name: /preview plan/i }));
      await waitFor(() => {
        expect(mockApi.previewWorkflowPlan).toHaveBeenCalled();
      });
      await user.click(
        screen.getByRole("button", { name: /execute workflow/i }),
      );

      await waitFor(() => {
        expect(mockApi.createAgentRun).toHaveBeenCalledWith(
          expect.objectContaining({
            agentic_mode: true,
            request: expect.objectContaining({
              document_ids: ["doc-1"],
              source_scope: undefined,
            }),
          }),
        );
      });
    });

    it("passes selected connector scope through to the workflow request", async () => {
      const user = userEvent.setup();
      mockApi.createAgentRun.mockResolvedValue({
        run: { run_id: "run-scope-connectors", status: "queued" },
      });
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({ run_id: "run-scope-connectors" }),
      );
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([]));

      renderPage();
      await user.type(
        screen.getByPlaceholderText(
          /describe what the workflow should accomplish/i,
        ),
        "Summarise selected connectors",
      );
      await user.click(screen.getByRole("button", { name: /select scope/i }));
      await user.click(screen.getByRole("button", { name: /connectors/i }));
      await user.click(screen.getByRole("button", { name: /eng/i }));
      await user.click(screen.getByRole("button", { name: /apply/i }));
      await user.click(screen.getByRole("button", { name: /preview plan/i }));
      await waitFor(() => {
        expect(mockApi.previewWorkflowPlan).toHaveBeenCalled();
      });
      await user.click(
        screen.getByRole("button", { name: /execute workflow/i }),
      );

      await waitFor(() => {
        expect(mockApi.createAgentRun).toHaveBeenCalledWith(
          expect.objectContaining({
            agentic_mode: true,
            request: expect.objectContaining({
              source_scope: {
                mode: "connector_sources",
                connection_ids: ["connector-1"],
                provider_source_ids: ["ENG"],
              },
            }),
          }),
        );
      });
    });

    it("shows error when preview fails", async () => {
      const user = userEvent.setup();
      mockApi.previewWorkflowPlan.mockRejectedValue(new Error("Rate limited"));

      renderPage();
      await user.click(
        screen.getByRole("button", { name: /audit evidence pack/i }),
      );
      const textarea = screen.getByPlaceholderText(
        /describe what the workflow should accomplish/i,
      );
      await user.type(textarea, "Analyse the data");
      await user.click(screen.getByRole("button", { name: /preview plan/i }));

      await waitFor(() => {
        expect(screen.getByText(/Rate limited|Unable to/i)).toBeInTheDocument();
      });
    });
  });

  describe("pending approvals", () => {
    it("renders pending approval with approve and reject buttons", async () => {
      const run = makeListItem({ status: "running" });
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse([run]));
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({
          status: "running",
          approvals: [
            {
              approval_id: "appr-1",
              agent_run_id: "run-1",
              agent_step_id: "step-1",
              tool_call_id: "tc-1",
              requested_by_user_id: "user-1",
              decided_by_user_id: null,
              status: "pending",
              request_summary: "Permission needed to read external API",
              decision_reason: null,
              request_payload: {},
              decision_payload: {},
              expires_at: null,
              decided_at: null,
              created_at: NOW,
              updated_at: NOW,
            },
          ],
        }),
      );

      renderPage();
      await waitFor(() => {
        expect(
          screen.getByText("Permission needed to read external API"),
        ).toBeInTheDocument();
        expect(
          screen.getByRole("button", { name: /approve/i }),
        ).toBeInTheDocument();
        expect(
          screen.getByRole("button", { name: /reject/i }),
        ).toBeInTheDocument();
      });
    });

    it("calls decideAgentRunApproval with approved status on approve click", async () => {
      const user = userEvent.setup();
      mockApi.listAgentRuns.mockResolvedValue(
        makeListResponse([makeListItem({ status: "running" })]),
      );
      mockApi.getAgentRun.mockResolvedValue(
        makeDetailResponse({
          status: "running",
          approvals: [
            {
              approval_id: "appr-1",
              agent_run_id: "run-1",
              agent_step_id: null,
              tool_call_id: null,
              requested_by_user_id: null,
              decided_by_user_id: null,
              status: "pending",
              request_summary: "Confirm tool use",
              decision_reason: null,
              request_payload: {},
              decision_payload: {},
              expires_at: null,
              decided_at: null,
              created_at: NOW,
              updated_at: NOW,
            },
          ],
        }),
      );
      mockApi.decideAgentRunApproval.mockResolvedValue({
        approval_id: "appr-1",
        status: "approved",
      });

      renderPage();
      const approveBtn = await screen.findByRole("button", {
        name: /^Approve$/i,
      });
      await user.click(approveBtn);

      await waitFor(() => {
        expect(mockApi.decideAgentRunApproval).toHaveBeenCalledWith(
          "run-abc-1",
          "appr-1",
          expect.objectContaining({ status: "approved" }),
        );
      });
    });
  });

  describe("run selection", () => {
    it("clicking a different run in the list loads its detail", async () => {
      const user = userEvent.setup();
      const runs = [
        makeListItem({ run_id: "r1", objective: "Task Alpha" }),
        makeListItem({ run_id: "r2", objective: "Task Beta" }),
      ];
      mockApi.listAgentRuns.mockResolvedValue(makeListResponse(runs));
      mockApi.getAgentRun.mockImplementation((id: string) =>
        Promise.resolve(makeDetailResponse({ run_id: id })),
      );

      renderPage();
      await screen.findByText("Task Alpha");
      await user.click(screen.getByText("Task Beta"));

      await waitFor(() => {
        expect(mockApi.getAgentRun).toHaveBeenCalledWith("r2");
      });
    });
  });
});
