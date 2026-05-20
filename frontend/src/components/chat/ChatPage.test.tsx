import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatPage } from "@/components/chat/ChatPage";
import { createAgentRun, decideAgentRunApproval, getAgentRun } from "@/lib/api/agent";
import { createChatSession, listChatSessionMessages, listChatSessions, queryChat } from "@/lib/api/chat";
import { listDocuments } from "@/lib/api/documents";
import { ApiClientError } from "@/lib/api/errors";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/chat", () => ({
  createChatSession: vi.fn(),
  listChatSessionMessages: vi.fn(),
  listChatSessions: vi.fn(),
  queryChat: vi.fn(),
}));

vi.mock("@/lib/api/agent", () => ({
  createAgentRun: vi.fn(),
  decideAgentRunApproval: vi.fn(),
  getAgentRun: vi.fn(),
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
      <ChatPage />
    </QueryClientProvider>,
  );
}

describe("ChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockNavigation.searchParams = new URLSearchParams();
    vi.mocked(listChatSessionMessages).mockResolvedValue({
      items: [],
      total: 0,
      limit: 500,
      offset: 0,
    });
    vi.mocked(listChatSessions).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    vi.mocked(createChatSession).mockResolvedValue({
      session_id: "session-new",
      title: null,
      message_count: 0,
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-14T10:00:00Z",
    });
    vi.mocked(createAgentRun).mockResolvedValue({
      run: {
        run_id: "run-default",
        status: "completed",
        steps_executed: 1,
        tool_calls_executed: 1,
        total_tokens: 20,
        total_cost_usd: 0.0004,
        outcome: {
          answer: "Agent answer",
          citations: [],
          confidence: {
            score: 0.8,
            category: "high",
          },
          not_found: false,
          mode: "answer",
        },
        error: null,
      },
    });
    vi.mocked(decideAgentRunApproval).mockResolvedValue({
      approval_id: "approval-1",
      agent_step_id: null,
      tool_call_id: null,
      requested_by_user_id: "user-1",
      decided_by_user_id: "user-1",
      status: "approved",
      request_summary: "Approval request",
      decision_reason: "Approved",
      request_payload: {},
      decision_payload: {},
      expires_at: null,
      decided_at: "2026-05-14T10:10:00Z",
      created_at: "2026-05-14T10:09:00Z",
      updated_at: "2026-05-14T10:10:00Z",
    });
    vi.mocked(getAgentRun).mockResolvedValue({
      run_id: "run-default",
      organization_id: "org-1",
      user_id: "user-1",
      status: "completed",
      surface: "api",
      objective: "default objective",
      max_steps: 12,
      max_parallel_tool_calls: 4,
      budget: {
        max_steps: 12,
        max_tool_calls: 30,
      },
      costs: {},
      outcome: {},
      observations: {},
      total_cost_usd: 0.0004,
      trace_request_id: "req-1",
      error_message: null,
      error_details: {},
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      created_at: "2026-05-14T10:10:00Z",
      updated_at: "2026-05-14T10:10:10Z",
      steps: [],
      tool_calls: [],
      approvals: [],
    });
  });

  it("prevents empty submissions in composer", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    renderPage();

    const askButton = screen.getByRole("button", { name: "Ask" });
    expect(askButton).toBeDisabled();

    const textarea = screen.getByPlaceholderText("Ask a question about your selected documents...");
    await userEvent.type(textarea, "   ");
    expect(askButton).toBeDisabled();
    expect(vi.mocked(queryChat)).not.toHaveBeenCalled();
  });

  it("shows empty sessions state with new-chat guidance", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    renderPage();

    expect(await screen.findByText("No sessions yet. Ask your first question to start one.")).toBeInTheDocument();
    expect(screen.getByText("New chat draft. Start with a question to create a session.")).toBeInTheDocument();
    expect(screen.getByText("No indexed documents available. Upload and index documents first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to documents upload" })).toHaveAttribute("href", "/documents");
  });

  it("renders citations and low-confidence warning for an answer", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 3,
          chunk_count: 42,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-1",
      message_id: "msg-1",
      answer: "The policy is active as of May 2026.",
      confidence_score: 0.32,
      confidence_category: "low",
      confidence_explanation: {
        top_similarity: 0.44,
        average_similarity: 0.41,
        top_rerank_score: 0.39,
        citation_support_score: 0.2,
        citation_validation_score: 0.85,
        citation_coverage_score: 0.1,
        retrieval_agreement_score: 0.25,
        raw_score: 0.32,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [
        {
          document_id: "doc-indexed-1",
          chunk_id: "chunk-1",
          filename: "policy.pdf",
          page_number: 2,
          score: 0.7,
          similarity_score: 0.61,
          rerank_score: 0.58,
          rerank_rank: 1,
          text_snippet: "Policy became active in May 2026.",
        },
      ],
      debug: {
        latencies_ms: { total: 123 },
        retrieval_count: 5,
        selected_count: 3,
        rerank_applied: true,
        embedding_model: "model-a",
        llm_model: "model-b",
      },
      created_at: "2026-05-14T10:10:00Z",
    });

    renderPage();

    await screen.findByText("policy.pdf");

    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "When is the policy active?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(vi.mocked(createChatSession)).toHaveBeenCalledTimes(1);

    expect(await screen.findByText("The policy is active as of May 2026.")).toBeInTheDocument();
    expect(screen.getByText("Low confidence warning: validate this answer against the cited source text.")).toBeInTheDocument();
    expect(screen.getByText("Policy became active in May 2026.")).toBeInTheDocument();
    expect(screen.getByText("Rerank rank")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open document detail" })).toHaveAttribute(
      "href",
      "/documents/doc-indexed-1?chunk_id=chunk-1&back=%2Fchat",
    );
  });

  it("hides debug panel for normal users by default", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 3,
          chunk_count: 42,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-1",
      message_id: "msg-1",
      answer: "normal answer",
      confidence_score: 0.72,
      confidence_category: "medium",
      confidence_explanation: {
        top_similarity: 0.5,
        average_similarity: 0.45,
        top_rerank_score: 0.48,
        citation_support_score: 0.6,
        citation_validation_score: 0.9,
        citation_coverage_score: 0.7,
        retrieval_agreement_score: 0.65,
        raw_score: 0.72,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      debug: {
        latencies_ms: { total: 123 },
        retrieval_count: 5,
        selected_count: 3,
        rerank_applied: true,
        embedding_model: "model-a",
        llm_model: "model-b",
      },
      created_at: "2026-05-14T10:10:00Z",
    });

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "check debug visibility");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("normal answer")).toBeInTheDocument();
    expect(screen.queryByText("Retrieval debug")).not.toBeInTheDocument();
  });

  it("shows debug panel in developer mode", async () => {
    window.localStorage.setItem(
      "rudix.settings.preferences.v1",
      JSON.stringify({
        default_top_k: 5,
        rerank_enabled: true,
        developer_mode: true,
        notifications: {
          product_updates: true,
          security_alerts: true,
          document_processing: true,
        },
      }),
    );

    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "policy.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 3,
          chunk_count: 42,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-1",
      message_id: "msg-1",
      answer: "debug answer",
      confidence_score: 0.72,
      confidence_category: "medium",
      confidence_explanation: {
        top_similarity: 0.5,
        average_similarity: 0.45,
        top_rerank_score: 0.48,
        citation_support_score: 0.6,
        citation_validation_score: 0.9,
        citation_coverage_score: 0.7,
        retrieval_agreement_score: 0.65,
        raw_score: 0.72,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      debug: {
        latencies_ms: { total: 123, retrieve: 34 },
        retrieval_count: 5,
        selected_count: 3,
        rerank_applied: true,
        embedding_model: "model-a",
        llm_model: "model-b",
      },
      created_at: "2026-05-14T10:10:00Z",
    });

    renderPage();
    await screen.findByText("policy.pdf");
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "show debug");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Retrieval debug")).toBeInTheDocument();
    expect(screen.getByText("retrieval_count")).toBeInTheDocument();
    expect(screen.getByText("selected_count")).toBeInTheDocument();
    expect(screen.getByText("rerank_applied")).toBeInTheDocument();
    expect(screen.getByText("embedding_model")).toBeInTheDocument();
    expect(screen.getByText("llm_model")).toBeInTheDocument();
    expect(screen.getByText("latencies_ms")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View pipeline run" })).toHaveAttribute(
      "href",
      "/rag-pipeline?run_type=chat.answer&chat_message_id=msg-1",
    );
  });

  it("shows only indexed documents in the selector", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
        {
          document_id: "doc-failed-1",
          filename: "failed.pdf",
          file_type: "pdf",
          status: "failed",
          page_count: 1,
          chunk_count: 0,
          error_message: "boom",
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 2,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    renderPage();

    expect(await screen.findByText("indexed.pdf")).toBeInTheDocument();
    expect(screen.queryByText("failed.pdf")).not.toBeInTheDocument();
  });

  it("submits selected document_ids with top_k and rerank payload", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-a",
          filename: "policy-a.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
        {
          document_id: "doc-indexed-b",
          filename: "policy-b.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 3,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:06:00Z",
        },
      ],
      total: 2,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-new",
      message_id: "msg-1",
      answer: "ok",
      confidence_score: 0.8,
      confidence_category: "high",
      confidence_explanation: {
        top_similarity: 0.8,
        average_similarity: 0.7,
        top_rerank_score: 0.75,
        citation_support_score: 0.7,
        citation_validation_score: 0.9,
        citation_coverage_score: 0.85,
        retrieval_agreement_score: 0.8,
        raw_score: 0.81,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      debug: {
        latencies_ms: { total: 100 },
        retrieval_count: 3,
        selected_count: 2,
        rerank_applied: false,
        embedding_model: "embed-model",
        llm_model: "llm-model",
      },
      created_at: "2026-05-14T10:10:00Z",
    });

    renderPage();

    const firstDocRow = (await screen.findByText("policy-a.pdf")).closest("label");
    expect(firstDocRow).not.toBeNull();
    await userEvent.click(within(firstDocRow as HTMLLabelElement).getByRole("checkbox"));

    const topKInput = screen.getByRole("spinbutton", { name: /Top K/i });
    fireEvent.change(topKInput, { target: { value: "9" } });

    await userEvent.click(screen.getByRole("checkbox", { name: /Enable rerank/i }));
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "scope check");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => {
      expect(vi.mocked(queryChat)).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "scope check",
          document_ids: ["doc-indexed-a"],
          top_k: 9,
          rerank: false,
        }),
      );
    });
  });

  it("submits agentic runs when agentic mode is enabled and renders timeline", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-a",
          filename: "policy-a.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(createAgentRun).mockResolvedValue({
      run: {
        run_id: "run-agent-1",
        status: "completed",
        steps_executed: 3,
        tool_calls_executed: 2,
        total_tokens: 180,
        total_cost_usd: 0.0022,
        outcome: {
          answer: "Agent generated grounded answer.",
          citations: [
            {
              document_id: "doc-indexed-a",
              chunk_id: "chunk-a",
              filename: "policy-a.pdf",
              page_number: 2,
              score: 0.88,
              similarity_score: 0.82,
              rerank_score: 0.8,
              rerank_rank: 1,
              snippet: "Grounded policy snippet",
            },
          ],
          confidence: {
            score: 0.82,
            category: "high",
          },
          not_found: false,
          mode: "answer",
        },
        error: null,
      },
    });
    vi.mocked(getAgentRun).mockResolvedValue({
      run_id: "run-agent-1",
      organization_id: "org-1",
      user_id: "user-1",
      status: "completed",
      surface: "api",
      objective: "Agent objective",
      max_steps: 12,
      max_parallel_tool_calls: 4,
      budget: {
        max_steps: 12,
        max_tool_calls: 30,
      },
      costs: {},
      outcome: {},
      observations: {},
      total_cost_usd: 0.0022,
      trace_request_id: "trace-agent",
      error_message: null,
      error_details: {},
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      created_at: "2026-05-14T10:10:00Z",
      updated_at: "2026-05-14T10:10:10Z",
      steps: [
        {
          step_id: "step-1",
          sequence: 1,
          step_name: "discover_documents",
          status: "completed",
          inputs: {},
          outputs: {},
          metrics: {},
          observation: {},
          error_message: null,
          error_details: {},
          started_at: null,
          completed_at: null,
          duration_ms: 12,
          created_at: "2026-05-14T10:10:00Z",
          updated_at: "2026-05-14T10:10:00Z",
        },
      ],
      tool_calls: [],
      approvals: [],
    });

    renderPage();
    await screen.findByText("policy-a.pdf");

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic mode/i }));
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "agentic question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Agent generated grounded answer.")).toBeInTheDocument();
    await waitFor(() => {
      expect(vi.mocked(createAgentRun)).toHaveBeenCalledWith(
        expect.objectContaining({
          agentic_mode: true,
          request: expect.objectContaining({
            objective: "agentic question",
            question: "agentic question",
            top_k: 5,
            rerank: true,
          }),
        }),
      );
    });
    expect(vi.mocked(queryChat)).not.toHaveBeenCalled();
    expect(vi.mocked(createChatSession)).not.toHaveBeenCalled();
    expect(await screen.findByText("Agent timeline")).toBeInTheDocument();
    expect(await screen.findByText("1. discover_documents")).toBeInTheDocument();
  });

  it("shows safe agentic error state with trace id and no secret leakage", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-a",
          filename: "policy-a.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(createAgentRun).mockRejectedValue(
      new ApiClientError({
        status: 503,
        code: "service_unavailable",
        message: "token=top-secret",
        details: {
          token: "top-secret",
        },
        requestId: "trace-agent-err",
        userMessage: "The service is temporarily unavailable.",
        actionMessage: "Retry shortly.",
        retryable: true,
      }),
    );

    renderPage();
    await screen.findByText("policy-a.pdf");

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic mode/i }));
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "agentic failing question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Unable to complete the query.")).toBeInTheDocument();
    expect(screen.getByText("The service is temporarily unavailable. Retry shortly.")).toBeInTheDocument();
    expect(screen.getByText("trace-agent-err")).toBeInTheDocument();
    expect(screen.queryByText(/top-secret/i)).not.toBeInTheDocument();
  });

  it("renders pending approvals in timeline and allows admin decisions", async () => {
    window.localStorage.setItem(
      "rudix.session.v1",
      JSON.stringify({
        userId: "user-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org 1",
        accessToken: "token",
        refreshToken: "refresh",
      }),
    );
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-a",
          filename: "policy-a.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(createAgentRun).mockResolvedValue({
      run: {
        run_id: "run-agent-approval",
        status: "waiting_approval",
        steps_executed: 1,
        tool_calls_executed: 1,
        total_tokens: 20,
        total_cost_usd: 0.0002,
        outcome: null,
        error: {
          code: "approval_required",
          message: "Tool execution requires human approval.",
          retryable: false,
          request_id: "req-approval",
          details: {
            approval_id: "approval-1",
          },
        },
      },
    });
    vi.mocked(getAgentRun).mockResolvedValue({
      run_id: "run-agent-approval",
      organization_id: "org-1",
      user_id: "user-1",
      status: "waiting_approval",
      surface: "api",
      objective: "Approval objective",
      max_steps: 12,
      max_parallel_tool_calls: 4,
      budget: {
        max_steps: 12,
        max_tool_calls: 30,
      },
      costs: {},
      outcome: {},
      observations: {},
      total_cost_usd: 0.0002,
      trace_request_id: "trace-approval",
      error_message: "Tool execution requires human approval.",
      error_details: {},
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      created_at: "2026-05-14T10:10:00Z",
      updated_at: "2026-05-14T10:10:10Z",
      steps: [
        {
          step_id: "step-1",
          sequence: 1,
          step_name: "sensitive_mutation",
          status: "waiting_approval",
          inputs: {},
          outputs: {},
          metrics: {},
          observation: {},
          error_message: "Tool execution requires human approval.",
          error_details: {},
          started_at: null,
          completed_at: null,
          duration_ms: 10,
          created_at: "2026-05-14T10:10:00Z",
          updated_at: "2026-05-14T10:10:00Z",
        },
      ],
      tool_calls: [],
      approvals: [
        {
          approval_id: "approval-1",
          agent_step_id: "step-1",
          tool_call_id: null,
          requested_by_user_id: "user-1",
          decided_by_user_id: null,
          status: "pending",
          request_summary: "Approval required for documents.delete",
          decision_reason: null,
          request_payload: { tool_name: "documents.delete" },
          decision_payload: {},
          expires_at: null,
          decided_at: null,
          created_at: "2026-05-14T10:10:00Z",
          updated_at: "2026-05-14T10:10:00Z",
        },
      ],
    });

    renderPage();
    await screen.findByText("policy-a.pdf");

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic mode/i }));
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "approval question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Approvals")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(vi.mocked(decideAgentRunApproval)).toHaveBeenCalledWith(
        "run-agent-approval",
        "approval-1",
        { status: "approved" },
      );
    });
  });

  it("enforces top_k min and max bounds", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    renderPage();

    const topKInput = screen.getByRole("spinbutton", { name: /Top K/i });
    fireEvent.change(topKInput, { target: { value: "0" } });
    expect(topKInput).toHaveValue(1);

    fireEvent.change(topKInput, { target: { value: "999" } });
    expect(topKInput).toHaveValue(20);
  });

  it("shows actionable error state when chat query fails", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockRejectedValue(new Error("Service unavailable"));

    renderPage();

    await screen.findByText("indexed.pdf");
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "hello");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => {
      expect(screen.getByText("Unable to complete the query.")).toBeInTheDocument();
    });
    expect(screen.getByText("Service unavailable")).toBeInTheDocument();
    expect(screen.getByDisplayValue("hello")).toBeInTheDocument();
  });

  it("submits via Cmd/Ctrl+Enter and preserves failed draft for retry", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat)
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValueOnce({
        chat_session_id: "session-new",
        message_id: "msg-retry",
        answer: "Recovered answer",
        confidence_score: 0.72,
        confidence_category: "medium",
        confidence_explanation: {
          top_similarity: 0.5,
          average_similarity: 0.45,
          top_rerank_score: 0.48,
          citation_support_score: 0.6,
          citation_validation_score: 0.9,
          citation_coverage_score: 0.7,
          retrieval_agreement_score: 0.65,
          raw_score: 0.72,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 100 },
          retrieval_count: 3,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "embed-model",
          llm_model: "llm-model",
        },
        created_at: "2026-05-14T10:10:00Z",
      });

    renderPage();

    await screen.findByText("indexed.pdf");
    const textarea = screen.getByPlaceholderText("Ask a question about your selected documents...");
    await userEvent.type(textarea, "retry me");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => {
      expect(screen.getByText("Unable to complete the query.")).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("retry me")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Recovered answer")).toBeInTheDocument();
  });

  it("loads and renders messages from previous sessions", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(listChatSessions).mockResolvedValue({
      items: [
        {
          session_id: "session-previous",
          title: "Previous session",
          message_count: 2,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:10:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listChatSessionMessages).mockResolvedValue({
      items: [
        {
          message_id: "user-1",
          role: "user",
          content: "What is the policy date?",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T10:00:00Z",
        },
        {
          message_id: "assistant-1",
          role: "assistant",
          content: "The policy date is May 2026.",
          confidence_score: 0.82,
          confidence_category: "high",
          citations: [],
          created_at: "2026-05-14T10:00:03Z",
        },
      ],
      total: 2,
      limit: 500,
      offset: 0,
    });

    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: /Previous session/i }));

    expect((await screen.findAllByText("What is the policy date?")).length).toBeGreaterThan(0);
    expect(screen.getByText("The policy date is May 2026.")).toBeInTheDocument();
  });

  it("supports incremental loading of sessions", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(listChatSessions)
      .mockResolvedValueOnce({
        items: [
          {
            session_id: "session-1",
            title: "Session one",
            message_count: 1,
            created_at: "2026-05-14T10:00:00Z",
            updated_at: "2026-05-14T10:10:00Z",
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: [
          {
            session_id: "session-2",
            title: "Session two",
            message_count: 1,
            created_at: "2026-05-14T11:00:00Z",
            updated_at: "2026-05-14T11:10:00Z",
          },
        ],
        total: 2,
        limit: 50,
        offset: 1,
      });

    renderPage();

    expect(await screen.findByText("Session one")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Load more sessions/i }));

    expect(await screen.findByText("Session two")).toBeInTheDocument();
    expect(vi.mocked(listChatSessions)).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ limit: 50, offset: 0 }),
    );
    expect(vi.mocked(listChatSessions)).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ limit: 50, offset: 1 }),
    );
  });

  it("renders high, medium, and low confidence badges from session history", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(listChatSessions).mockResolvedValue({
      items: [
        {
          session_id: "session-confidence",
          title: "Confidence history",
          message_count: 6,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:10:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listChatSessionMessages).mockResolvedValue({
      items: [
        {
          message_id: "u-1",
          role: "user",
          content: "q1",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T10:00:00Z",
        },
        {
          message_id: "a-1",
          role: "assistant",
          content: "a1",
          confidence_score: 0.91,
          confidence_category: "high",
          citations: [],
          created_at: "2026-05-14T10:00:01Z",
        },
        {
          message_id: "u-2",
          role: "user",
          content: "q2",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T10:01:00Z",
        },
        {
          message_id: "a-2",
          role: "assistant",
          content: "a2",
          confidence_score: 0.55,
          confidence_category: "medium",
          citations: [],
          created_at: "2026-05-14T10:01:01Z",
        },
        {
          message_id: "u-3",
          role: "user",
          content: "q3",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T10:02:00Z",
        },
        {
          message_id: "a-3",
          role: "assistant",
          content: "a3",
          confidence_score: 0.22,
          confidence_category: "low",
          citations: [],
          created_at: "2026-05-14T10:02:01Z",
        },
      ],
      total: 6,
      limit: 500,
      offset: 0,
    });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Confidence history/i }));

    expect((await screen.findAllByText("Confidence 91.0%")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Confidence 55.0%")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Confidence 22.0%")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Low confidence warning: validate this answer against the cited source text.")).length).toBe(1);
  });

  it("renders safe not-found state and hides citations panel details", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-new",
      message_id: "msg-not-found",
      answer: "No matching source text.",
      confidence_score: 0.3,
      confidence_category: "low",
      confidence_explanation: {
        top_similarity: 0.2,
        average_similarity: 0.2,
        top_rerank_score: 0.2,
        citation_support_score: 0.1,
        citation_validation_score: 0.8,
        citation_coverage_score: 0.1,
        retrieval_agreement_score: 0.2,
        raw_score: 0.3,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: true,
        not_found_signal: true,
        weights: {},
        thresholds: {},
      },
      not_found: true,
      citations: [],
      debug: {
        latencies_ms: { total: 100 },
        retrieval_count: 0,
        selected_count: 0,
        rerank_applied: false,
        embedding_model: "embed-model",
        llm_model: "llm-model",
      },
      created_at: "2026-05-14T10:10:00Z",
    });

    renderPage();
    await screen.findByText("indexed.pdf");
    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "unknown question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("No grounded answer was found in the selected documents.")).toBeInTheDocument();
    expect(screen.getByText("No citations are shown because the assistant did not find grounded evidence for this response.")).toBeInTheDocument();
    expect(screen.queryByText("Low confidence warning: validate this answer against the cited source text.")).not.toBeInTheDocument();
  });

  it("keeps previous answers visible when a later query fails", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat)
      .mockResolvedValueOnce({
        chat_session_id: "session-new",
        message_id: "msg-ok",
        answer: "First answer stays visible",
        confidence_score: 0.8,
        confidence_category: "high",
        confidence_explanation: {
          top_similarity: 0.8,
          average_similarity: 0.7,
          top_rerank_score: 0.75,
          citation_support_score: 0.7,
          citation_validation_score: 0.9,
          citation_coverage_score: 0.85,
          retrieval_agreement_score: 0.8,
          raw_score: 0.81,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 100 },
          retrieval_count: 3,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "embed-model",
          llm_model: "llm-model",
        },
        created_at: "2026-05-14T10:10:00Z",
      })
      .mockRejectedValueOnce(new Error("Temporary failure"));

    renderPage();
    await screen.findByText("indexed.pdf");

    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "first");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("First answer stays visible")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "second");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Unable to complete the query.")).toBeInTheDocument();
    expect(screen.getByText("First answer stays visible")).toBeInTheDocument();
  });

  it("supports regenerating the latest answer", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-indexed-1",
          filename: "indexed.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 5,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T10:00:00Z",
          updated_at: "2026-05-14T10:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat)
      .mockResolvedValueOnce({
        chat_session_id: "session-new",
        message_id: "msg-1",
        answer: "Initial answer",
        confidence_score: 0.8,
        confidence_category: "high",
        confidence_explanation: {
          top_similarity: 0.8,
          average_similarity: 0.7,
          top_rerank_score: 0.75,
          citation_support_score: 0.7,
          citation_validation_score: 0.9,
          citation_coverage_score: 0.85,
          retrieval_agreement_score: 0.8,
          raw_score: 0.81,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 100 },
          retrieval_count: 3,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "embed-model",
          llm_model: "llm-model",
        },
        created_at: "2026-05-14T10:10:00Z",
      })
      .mockResolvedValueOnce({
        chat_session_id: "session-new",
        message_id: "msg-2",
        answer: "Regenerated answer",
        confidence_score: 0.78,
        confidence_category: "medium",
        confidence_explanation: {
          top_similarity: 0.75,
          average_similarity: 0.69,
          top_rerank_score: 0.73,
          citation_support_score: 0.65,
          citation_validation_score: 0.87,
          citation_coverage_score: 0.8,
          retrieval_agreement_score: 0.77,
          raw_score: 0.78,
          citation_validation_multiplier: 1,
          not_found_penalty_multiplier: 1,
          no_context: false,
          not_found_signal: false,
          weights: {},
          thresholds: {},
        },
        not_found: false,
        citations: [],
        debug: {
          latencies_ms: { total: 95 },
          retrieval_count: 3,
          selected_count: 2,
          rerank_applied: true,
          embedding_model: "embed-model",
          llm_model: "llm-model",
        },
        created_at: "2026-05-14T10:11:00Z",
      });

    renderPage();
    await screen.findByText("indexed.pdf");

    await userEvent.type(screen.getByPlaceholderText("Ask a question about your selected documents..."), "repeat me");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Initial answer")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Regenerate last answer" }));
    expect(await screen.findByText("Regenerated answer")).toBeInTheDocument();
    expect(vi.mocked(queryChat)).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ question: "repeat me" }),
    );
  });
});
