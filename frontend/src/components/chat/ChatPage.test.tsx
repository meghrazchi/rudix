import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatPage } from "@/components/chat/ChatPage";
import {
  createAgentRun,
  decideAgentRunApproval,
  getAgentRun,
} from "@/lib/api/agent";
import {
  createChatSession,
  deleteChatSession,
  listChatSessionMessages,
  listChatSessions,
  queryChat,
  updateChatSession,
} from "@/lib/api/chat";
import { listCollections } from "@/lib/api/collections";
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

vi.mock("@/lib/api/collections", () => ({
  listCollections: vi.fn(),
  listCollectionDocuments: vi.fn(),
}));

vi.mock("@/lib/api/chat", () => ({
  createChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  listChatSessionMessages: vi.fn(),
  listChatSessions: vi.fn(),
  queryChat: vi.fn(),
  updateChatSession: vi.fn(),
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

async function openSessionMenu(sessionTitle: string) {
  const item = await screen.findByText(sessionTitle);
  const row = item.closest("li") as HTMLElement;
  await userEvent.click(
    within(row).getByRole("button", { name: /Session actions/i }),
  );
}

async function openContextSelector() {
  // Switch scope type to "Files" (documents mode), then open the file picker.
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: /Scope type/i }),
    "documents",
  );
  await userEvent.click(
    await screen.findByRole("button", { name: /Select Files/i }),
  );
  return screen.findByRole("dialog", { name: /Select context/i });
}

describe("ChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockNavigation.searchParams = new URLSearchParams();
    vi.mocked(listCollections).mockResolvedValue({ items: [], total: 0 });
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
    vi.mocked(deleteChatSession).mockResolvedValue(undefined);
    vi.mocked(updateChatSession).mockResolvedValue({
      session_id: "session-new",
      title: "Renamed Session",
      message_count: 0,
      created_at: "2026-05-14T10:00:00Z",
      updated_at: "2026-05-14T10:01:00Z",
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

    const askButton = screen.getByRole("button", { name: /Send message/i });
    expect(askButton).toBeDisabled();

    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
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

    expect(
      await screen.findByText(
        "No sessions yet. Ask your first question to start one.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "New chat draft. Start with a question to create a session.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Chat is disabled until at least one document is indexed.",
      ),
    ).toBeInTheDocument();
    const contextDialog = await openContextSelector();
    expect(
      within(contextDialog).getByText(
        "No indexed documents available. Upload and index documents first.",
      ),
    ).toBeInTheDocument();
    expect(
      within(contextDialog).getByRole("link", {
        name: "Go to documents upload",
      }),
    ).toHaveAttribute("href", "/documents");
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

    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "When is the policy active?",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(vi.mocked(createChatSession)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(createChatSession)).toHaveBeenCalledWith({
      title: "When is the policy active?",
    });

    expect(
      await screen.findByText("The policy is active as of May 2026."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Low confidence warning: validate this answer against the cited source text.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Policy became active in May 2026.").length,
    ).toBeGreaterThan(0);
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "check debug visibility",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

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
    await screen.findByRole("button", { name: /Context \([1-9]/i });
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "show debug",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(await screen.findByText("Retrieval debug")).toBeInTheDocument();
    expect(screen.getByText("retrieval_count")).toBeInTheDocument();
    expect(screen.getByText("selected_count")).toBeInTheDocument();
    expect(screen.getByText("rerank_applied")).toBeInTheDocument();
    expect(screen.getByText("embedding_model")).toBeInTheDocument();
    expect(screen.getByText("llm_model")).toBeInTheDocument();
  });

  it("shows only indexed documents in the selector", async () => {
    const allDocs = [
      {
        document_id: "doc-indexed-1",
        filename: "indexed.pdf",
        file_type: "pdf" as const,
        status: "indexed" as const,
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
        file_type: "pdf" as const,
        status: "failed" as const,
        page_count: 1,
        chunk_count: 0,
        error_message: "boom",
        error_details: null,
        created_at: "2026-05-14T10:00:00Z",
        updated_at: "2026-05-14T10:05:00Z",
      },
    ];
    vi.mocked(listDocuments).mockImplementation(async (params) => {
      const filtered = params?.status
        ? allDocs.filter((d) => d.status === params.status)
        : allDocs;
      const limit = params?.limit ?? 200;
      const offset = params?.offset ?? 0;
      const items = filtered.slice(offset, offset + limit);
      return {
        items,
        total: filtered.length,
        limit,
        offset,
        status: (params?.status as "indexed" | null) ?? null,
        sort_by: "updated_at" as const,
        sort_order: "desc" as const,
      };
    });

    renderPage();

    const contextDialog = await openContextSelector();
    expect(
      await within(contextDialog).findByText("indexed.pdf"),
    ).toBeInTheDocument();
    expect(
      within(contextDialog).queryByText("failed.pdf"),
    ).not.toBeInTheDocument();
  });

  it("paginates the context selector modal", async () => {
    const docs = Array.from({ length: 10 }, (_, index) => ({
      document_id: `doc-indexed-${index + 1}`,
      filename: `policy-${index + 1}.pdf`,
      file_type: "pdf" as const,
      status: "indexed" as const,
      page_count: 1,
      chunk_count: index + 1,
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T10:00:00Z",
      updated_at: `2026-05-14T10:${String(index).padStart(2, "0")}:00Z`,
    }));
    vi.mocked(listDocuments).mockImplementation(async (params) => {
      const limit = params?.limit ?? 200;
      const offset = params?.offset ?? 0;
      const items = docs.slice(offset, offset + limit);
      return {
        items,
        total: docs.length,
        limit,
        offset,
        status: "indexed" as const,
        sort_by: "updated_at" as const,
        sort_order: "desc" as const,
      };
    });

    renderPage();

    const contextDialog = await openContextSelector();
    expect(
      await within(contextDialog).findByText("policy-1.pdf"),
    ).toBeInTheDocument();
    expect(
      within(contextDialog).queryByText("policy-9.pdf"),
    ).not.toBeInTheDocument();

    await userEvent.click(
      within(contextDialog).getByRole("button", { name: "Next" }),
    );

    expect(
      await within(contextDialog).findByText("policy-9.pdf"),
    ).toBeInTheDocument();
    expect(
      within(contextDialog).queryByText("policy-1.pdf"),
    ).not.toBeInTheDocument();
    expect(
      within(contextDialog).getByText("Showing 9-10 of 10"),
    ).toBeInTheDocument();
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

    const contextDialog = await openContextSelector();
    const firstDocRow = (
      await within(contextDialog).findByText("policy-a.pdf")
    ).closest("label");
    expect(firstDocRow).not.toBeNull();
    await userEvent.click(
      within(firstDocRow as HTMLLabelElement).getByRole("checkbox"),
    );
    await userEvent.click(
      within(contextDialog).getByRole("button", { name: "Done" }),
    );

    const topKInput = screen.getByRole("spinbutton", { name: /Top K/i });
    fireEvent.change(topKInput, { target: { value: "9" } });

    await userEvent.click(screen.getByRole("checkbox", { name: /Rerank/i }));
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "scope check",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

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
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic/i }));
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "agentic question",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText("Agent generated grounded answer."),
    ).toBeInTheDocument();
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
    expect(
      await screen.findByText("1. discover_documents"),
    ).toBeInTheDocument();
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic/i }));
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "agentic failing question",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText("Unable to complete the query."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The service is temporarily unavailable. Retry shortly.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("trace-agent-err")).toBeInTheDocument();
    expect(screen.queryByText(/top-secret/i)).not.toBeInTheDocument();
  });

  it("falls back to standard chat when agentic backend feature is unavailable", async () => {
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
        status: 404,
        code: "feature_not_available",
        message: "Agentic mode is not enabled for this deployment.",
        details: { code: "feature_not_available" },
        requestId: "trace-agent-disabled",
        userMessage: "This feature is not enabled on the backend.",
        actionMessage:
          "Disable agentic mode or enable FEATURE_ENABLE_AGENTS and restart the API.",
        retryable: false,
      }),
    );
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-new",
      message_id: "msg-fallback",
      answer: "Fallback chat answer",
      confidence_score: 0.61,
      confidence_category: "medium",
      confidence_explanation: {
        top_similarity: 0.7,
        average_similarity: 0.66,
        top_rerank_score: 0.61,
        citation_support_score: 0.6,
        citation_validation_score: 0.55,
        citation_coverage_score: 0.5,
        retrieval_agreement_score: 0.54,
        raw_score: 0.61,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      created_at: "2026-05-14T10:20:00Z",
      debug: {
        latencies_ms: {},
        retrieval_count: 0,
        selected_count: 0,
        rerank_applied: false,
        embedding_model: null,
        llm_model: null,
      },
    });

    renderPage();
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic/i }));
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "fallback question",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(await screen.findByText("Fallback chat answer")).toBeInTheDocument();
    expect(vi.mocked(createAgentRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(queryChat)).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("checkbox", { name: /Agentic/i }),
    ).not.toBeChecked();
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.click(screen.getByRole("checkbox", { name: /Agentic/i }));
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "approval question",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

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

    await screen.findByRole("button", { name: /Context \([1-9]/i });
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "hello",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Unable to complete the query."),
      ).toBeInTheDocument();
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

    await screen.findByRole("button", { name: /Context \([1-9]/i });
    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
    await userEvent.type(textarea, "retry me");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => {
      expect(
        screen.getByText("Unable to complete the query."),
      ).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("retry me")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );
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

    await userEvent.click(
      await screen.findByRole("button", { name: /Previous session/i }),
    );

    expect(
      (await screen.findAllByText("What is the policy date?")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText("The policy date is May 2026."),
    ).toBeInTheDocument();
  });

  it("uses the first question as session label when title is missing", async () => {
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
          session_id: "session-untitled",
          title: null,
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
          message_id: "user-untitled-1",
          role: "user",
          content: "How many days of leave are allowed?",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T10:00:00Z",
        },
        {
          message_id: "assistant-untitled-1",
          role: "assistant",
          content: "Up to 10 days are allowed.",
          confidence_score: 0.8,
          confidence_category: "high",
          citations: [],
          created_at: "2026-05-14T10:00:02Z",
        },
      ],
      total: 2,
      limit: 500,
      offset: 0,
    });

    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /Untitled session/i }),
    );

    expect(
      await screen.findByText("Up to 10 days are allowed."),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: /How many days of leave are allowed\?/i,
        }),
      ).toBeInTheDocument();
    });
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
    await userEvent.click(
      screen.getByRole("button", { name: /Load more sessions/i }),
    );

    expect(await screen.findByText("Session two")).toBeInTheDocument();
    expect(vi.mocked(listChatSessions)).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ limit: 10, offset: 0 }),
    );
    expect(vi.mocked(listChatSessions)).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ limit: 10, offset: 1 }),
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
    await userEvent.click(
      await screen.findByRole("button", { name: /Confidence history/i }),
    );

    expect(
      (await screen.findAllByText("Confidence 91.0%")).length,
    ).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("Confidence 55.0%")).length,
    ).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("Confidence 22.0%")).length,
    ).toBeGreaterThan(0);
    expect(
      (
        await screen.findAllByText(
          "Low confidence warning: validate this answer against the cited source text.",
        )
      ).length,
    ).toBe(1);
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "unknown question",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText(
        "No grounded answer was found in the selected documents.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No citations are shown because the assistant did not find grounded evidence for this response.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Low confidence warning: validate this answer against the cited source text.",
      ),
    ).not.toBeInTheDocument();
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "first",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );
    expect(
      await screen.findByText("First answer stays visible"),
    ).toBeInTheDocument();

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "second",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText("Unable to complete the query."),
    ).toBeInTheDocument();
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
    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "repeat me",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );
    expect(await screen.findByText("Initial answer")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(await screen.findByText("Regenerated answer")).toBeInTheDocument();
    expect(vi.mocked(queryChat)).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ question: "repeat me" }),
    );
  });

  it("filters session list when search query is typed", async () => {
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
            session_id: "s1",
            title: "Policy Review",
            message_count: 2,
            created_at: "2026-05-14T09:00:00Z",
            updated_at: "2026-05-14T09:05:00Z",
          },
          {
            session_id: "s2",
            title: "Budget Planning",
            message_count: 1,
            created_at: "2026-05-14T08:00:00Z",
            updated_at: "2026-05-14T08:05:00Z",
          },
        ],
        total: 2,
        limit: 10,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: [
          {
            session_id: "s1",
            title: "Policy Review",
            message_count: 2,
            created_at: "2026-05-14T09:00:00Z",
            updated_at: "2026-05-14T09:05:00Z",
          },
        ],
        total: 1,
        limit: 10,
        offset: 0,
      });

    renderPage();
    expect(await screen.findByText("Policy Review")).toBeInTheDocument();
    expect(screen.getByText("Budget Planning")).toBeInTheDocument();

    const searchInput = screen.getByRole("textbox", {
      name: /Search sessions/i,
    });
    await userEvent.type(searchInput, "policy");

    await waitFor(() => {
      expect(vi.mocked(listChatSessions)).toHaveBeenCalledWith(
        expect.objectContaining({ search: "policy" }),
      );
    });
  });

  it("shows contextual empty state when search returns no results", async () => {
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
      items: [],
      total: 0,
      limit: 10,
      offset: 0,
    });

    renderPage();
    await screen.findByRole("textbox", { name: /Search sessions/i });

    const searchInput = screen.getByRole("textbox", {
      name: /Search sessions/i,
    });
    await userEvent.type(searchInput, "xyz");

    await waitFor(() => {
      expect(screen.getByText(/No sessions match "xyz"/)).toBeInTheDocument();
    });
  });

  it("shows rename inline form when rename button is clicked", async () => {
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
          session_id: "s1",
          title: "My Session",
          message_count: 1,
          created_at: "2026-05-14T09:00:00Z",
          updated_at: "2026-05-14T09:05:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("My Session")).toBeInTheDocument();

    await openSessionMenu("My Session");
    await userEvent.click(screen.getByRole("menuitem", { name: /Rename/i }));

    expect(
      screen.getByRole("textbox", { name: /Session title/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("calls updateChatSession when rename is saved", async () => {
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
          session_id: "s1",
          title: "Old Title",
          message_count: 1,
          created_at: "2026-05-14T09:00:00Z",
          updated_at: "2026-05-14T09:05:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });
    vi.mocked(updateChatSession).mockResolvedValue({
      session_id: "s1",
      title: "New Title",
      message_count: 1,
      created_at: "2026-05-14T09:00:00Z",
      updated_at: "2026-05-14T09:06:00Z",
    });

    renderPage();
    expect(await screen.findByText("Old Title")).toBeInTheDocument();

    await openSessionMenu("Old Title");
    await userEvent.click(screen.getByRole("menuitem", { name: /Rename/i }));
    const input = screen.getByRole("textbox", { name: /Session title/i });
    await userEvent.clear(input);
    await userEvent.type(input, "New Title");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(vi.mocked(updateChatSession)).toHaveBeenCalledWith("s1", {
        title: "New Title",
      });
    });
  });

  it("shows delete confirmation and calls deleteChatSession on confirm", async () => {
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
          session_id: "s1",
          title: "Session To Delete",
          message_count: 3,
          created_at: "2026-05-14T09:00:00Z",
          updated_at: "2026-05-14T09:05:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("Session To Delete")).toBeInTheDocument();

    await openSessionMenu("Session To Delete");
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/i }));

    expect(screen.getByText("Delete this session?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(vi.mocked(deleteChatSession)).toHaveBeenCalledWith("s1");
    });
  });

  it("dismisses delete confirmation without deleting when cancel is clicked", async () => {
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
          session_id: "s1",
          title: "Keep Me",
          message_count: 1,
          created_at: "2026-05-14T09:00:00Z",
          updated_at: "2026-05-14T09:05:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("Keep Me")).toBeInTheDocument();

    await openSessionMenu("Keep Me");
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/i }));
    expect(screen.getByText("Delete this session?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText("Delete this session?")).not.toBeInTheDocument();
    expect(vi.mocked(deleteChatSession)).not.toHaveBeenCalled();
  });

  it("loads historical messages when switching to a session with messages", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "report.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 5,
          chunk_count: 20,
          error_message: null,
          error_details: null,
          created_at: "2026-05-14T08:00:00Z",
          updated_at: "2026-05-14T08:05:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(listChatSessions).mockResolvedValue({
      items: [
        {
          session_id: "s-history",
          title: "Historical Chat",
          message_count: 2,
          created_at: "2026-05-14T09:00:00Z",
          updated_at: "2026-05-14T09:05:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });
    vi.mocked(listChatSessionMessages).mockResolvedValue({
      items: [
        {
          message_id: "m-user",
          role: "user",
          content: "What does the report say?",
          confidence_score: null,
          confidence_category: null,
          citations: [],
          created_at: "2026-05-14T09:01:00Z",
        },
        {
          message_id: "m-assistant",
          role: "assistant",
          content: "The report says revenue grew 12%.",
          confidence_score: 0.88,
          confidence_category: "high",
          citations: [],
          created_at: "2026-05-14T09:01:05Z",
        },
      ],
      total: 2,
      limit: 500,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("Historical Chat")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Historical Chat"));

    expect(
      await screen.findByText("The report says revenue grew 12%."),
    ).toBeInTheDocument();
    expect(screen.getByText("What does the report say?")).toBeInTheDocument();
  });

  // ── F136 scope controls ──────────────────────────────────────────────────

  it("renders all four scope mode buttons in the composer toolbar", async () => {
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

    const scopeSelect = screen.getByRole("combobox", { name: /Scope type/i });
    expect(scopeSelect).toBeInTheDocument();
    expect(
      within(scopeSelect as HTMLSelectElement).getByRole("option", {
        name: /All files/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(scopeSelect as HTMLSelectElement).getByRole("option", {
        name: /^Collection$/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(scopeSelect as HTMLSelectElement).getByRole("option", {
        name: /^Files$/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(scopeSelect as HTMLSelectElement).getByRole("option", {
        name: /No RAG/i,
      }),
    ).toBeInTheDocument();
  });

  it("shows warning when documents scope selected with no files chosen", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "policy.pdf",
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

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /Scope type/i }),
      "documents",
    );

    expect(
      await screen.findByText(
        "Select at least one document to use document scope.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Send message/i }),
    ).toBeDisabled();
  });

  it("shows warning when collection scope selected with no collection chosen", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "policy.pdf",
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

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /Scope type/i }),
      "collection",
    );

    expect(
      await screen.findByText("Select a collection to scope retrieval."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Send message/i }),
    ).toBeDisabled();
  });

  it("enables submit in No RAG mode even when no documents are indexed", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-none",
      message_id: "msg-none",
      answer: "The capital of France is Paris.",
      confidence_score: 0.0,
      confidence_category: "low",
      confidence_explanation: {
        top_similarity: 0.0,
        average_similarity: 0.0,
        top_rerank_score: 0.0,
        citation_support_score: 0.0,
        citation_validation_score: 1.0,
        citation_coverage_score: 0.0,
        retrieval_agreement_score: 0.0,
        raw_score: 0.0,
        citation_validation_multiplier: 1,
        not_found_penalty_multiplier: 1,
        no_context: true,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      debug: {
        latencies_ms: { total: 40 },
        retrieval_count: 0,
        selected_count: 0,
        rerank_applied: false,
        embedding_model: null,
        llm_model: "llm-model",
      },
      created_at: "2026-06-01T10:00:00Z",
    });

    renderPage();

    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: /Scope type/i }),
      "none",
    );

    const textarea = screen.getByPlaceholderText(
      "Type a message or use '/' for commands...",
    );
    expect(textarea).not.toBeDisabled();

    await userEvent.type(textarea, "What is the capital of France?");

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Send message/i }),
      ).not.toBeDisabled();
    });

    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    expect(
      await screen.findByText("The capital of France is Paris."),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(vi.mocked(queryChat)).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "What is the capital of France?",
          scope_mode: "none",
        }),
      );
    });
  });

  it("shows scope label chip in answer header", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "policy.pdf",
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
      chat_session_id: "session-scope",
      message_id: "msg-scope",
      answer: "Policy answer.",
      confidence_score: 0.85,
      confidence_category: "high",
      confidence_explanation: {
        top_similarity: 0.85,
        average_similarity: 0.8,
        top_rerank_score: 0.82,
        citation_support_score: 0.7,
        citation_validation_score: 0.9,
        citation_coverage_score: 0.8,
        retrieval_agreement_score: 0.75,
        raw_score: 0.85,
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
        latencies_ms: { total: 80 },
        retrieval_count: 1,
        selected_count: 1,
        rerank_applied: false,
        embedding_model: "embed-model",
        llm_model: "llm-model",
      },
      created_at: "2026-06-01T10:00:00Z",
    });

    renderPage();

    await screen.findByRole("button", { name: /Context \([1-9]/i });

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "What is the policy?",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    // The scope label chip in the answer header should show "All files (N)".
    // The Context button in the toolbar also shows "Context (N)", so findAllByText on the
    // chip-specific pattern should find exactly the answer header chip.
    expect(await screen.findByText(/All files \(\d+\)/i)).toBeInTheDocument();
  });

  it("passes scope_mode=documents and selected document_ids when in documents scope", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      items: [
        {
          document_id: "doc-scoped",
          filename: "scoped.pdf",
          file_type: "pdf",
          status: "indexed",
          page_count: 1,
          chunk_count: 3,
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
      chat_session_id: "session-doc-scope",
      message_id: "msg-doc-scope",
      answer: "Scoped answer.",
      confidence_score: 0.9,
      confidence_category: "high",
      confidence_explanation: {
        top_similarity: 0.9,
        average_similarity: 0.85,
        top_rerank_score: 0.88,
        citation_support_score: 0.8,
        citation_validation_score: 0.95,
        citation_coverage_score: 0.9,
        retrieval_agreement_score: 0.85,
        raw_score: 0.9,
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
        latencies_ms: { total: 60 },
        retrieval_count: 1,
        selected_count: 1,
        rerank_applied: false,
        embedding_model: "embed-model",
        llm_model: "llm-model",
      },
      created_at: "2026-06-01T10:00:00Z",
    });

    renderPage();

    const contextDialog = await openContextSelector();
    const docLabel = (
      await within(contextDialog).findByText("scoped.pdf")
    ).closest("label");
    await userEvent.click(
      within(docLabel as HTMLLabelElement).getByRole("checkbox"),
    );
    await userEvent.click(
      within(contextDialog).getByRole("button", { name: "Done" }),
    );

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "Scoped query",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    await waitFor(() => {
      expect(vi.mocked(queryChat)).toHaveBeenCalledWith(
        expect.objectContaining({
          question: "Scoped query",
          document_ids: ["doc-scoped"],
          scope_mode: "documents",
        }),
      );
    });
  });

  it("renders the answer language selector in the composer toolbar", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /Chat Session/i });

    const selector = screen.getByRole("combobox", { name: "Answer language" });
    expect(selector).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Auto" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "German" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "French" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Spanish" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
  });

  it("passes answer_language=de to queryChat when German is selected", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /Chat Session/i });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Answer language" }),
      "de",
    );

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "How many leave days?",
    );

    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-lang",
      message_id: "msg-lang",
      answer: "Der Urlaub beträgt 30 Tage.",
      confidence_score: 0.85,
      confidence_category: "high",
      confidence_explanation: {
        top_similarity: 0.85,
        average_similarity: 0.75,
        top_rerank_score: 0.0,
        citation_support_score: 0.7,
        citation_validation_score: 1.0,
        citation_coverage_score: 0.5,
        retrieval_agreement_score: 0.8,
        raw_score: 0.75,
        citation_validation_multiplier: 1.0,
        not_found_penalty_multiplier: 1.0,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      citation_validation_failed: false,
      debug: {
        latencies_ms: { total: 300 },
        retrieval_count: 0,
        selected_count: 0,
        rerank_applied: false,
        detected_language: "en",
        answer_language_used: "de",
      },
      created_at: "2026-06-04T00:00:00Z",
    });

    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    await waitFor(() => {
      expect(vi.mocked(queryChat)).toHaveBeenCalledWith(
        expect.objectContaining({
          answer_language: "de",
        }),
      );
    });
  });

  it("omits answer_language from payload when auto is selected", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /Chat Session/i });

    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "Test question",
    );

    vi.mocked(queryChat).mockResolvedValue({
      chat_session_id: "session-auto",
      message_id: "msg-auto",
      answer: "Answer.",
      confidence_score: 0.5,
      confidence_category: "medium",
      confidence_explanation: {
        top_similarity: 0.5,
        average_similarity: 0.4,
        top_rerank_score: 0.0,
        citation_support_score: 0.5,
        citation_validation_score: 1.0,
        citation_coverage_score: 0.5,
        retrieval_agreement_score: 0.5,
        raw_score: 0.5,
        citation_validation_multiplier: 1.0,
        not_found_penalty_multiplier: 1.0,
        no_context: false,
        not_found_signal: false,
        weights: {},
        thresholds: {},
      },
      not_found: false,
      citations: [],
      citation_validation_failed: false,
      debug: {
        latencies_ms: { total: 100 },
        retrieval_count: 0,
        selected_count: 0,
        rerank_applied: false,
      },
      created_at: "2026-06-04T00:00:00Z",
    });

    await userEvent.click(
      screen.getByRole("button", { name: /Send message/i }),
    );

    await waitFor(() => {
      expect(vi.mocked(queryChat)).toHaveBeenCalledWith(
        expect.objectContaining({ question: "Test question" }),
      );
    });

    const call = vi.mocked(queryChat).mock.calls.at(-1)?.[0];
    expect(call?.answer_language).toBeUndefined();
  });
});
