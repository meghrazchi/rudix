import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
import {
  deleteMessageFeedback,
  listSessionFeedback,
  submitMessageFeedback,
} from "@/lib/api/feedback";

const mockNavigation = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockNavigation.searchParams,
}));

vi.mock("@/lib/runtime-config", () => ({
  getFrontendRuntimeConfig: () => ({
    apiUrl: "http://localhost:8000/api/v1",
    appUrl: "http://localhost:3000",
    authProvider: "app",
    authProviderRaw: "app",
    features: {
      developerMode: false,
      feedback: true,
      exports: false,
      unavailableBackendEndpoints: false,
      collectionsEnabled: false,
    },
  }),
}));

vi.mock("@/lib/api/documents", () => ({ listDocuments: vi.fn() }));

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

vi.mock("@/lib/api/feedback", () => ({
  submitMessageFeedback: vi.fn(),
  deleteMessageFeedback: vi.fn(),
  listSessionFeedback: vi.fn(),
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

const INDEXED_DOCS_RESPONSE = {
  items: [
    {
      document_id: "doc-1",
      filename: "policy.pdf",
      file_type: "pdf" as const,
      status: "indexed" as const,
      page_count: 3,
      chunk_count: 10,
      error_message: null,
      error_details: null,
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:05:00Z",
    },
  ],
  total: 1,
  limit: 200,
  offset: 0,
  status: "indexed" as const,
  sort_by: "updated_at" as const,
  sort_order: "desc" as const,
};

const QUERY_RESPONSE = {
  chat_session_id: "session-1",
  message_id: "msg-1",
  answer: "The policy is active.",
  confidence_score: 0.85,
  confidence_category: "high" as const,
  confidence_explanation: {
    top_similarity: 0.9,
    average_similarity: 0.85,
    top_rerank_score: 0.82,
    citation_support_score: 0.8,
    citation_validation_score: 0.9,
    citation_coverage_score: 0.7,
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
    retrieval_count: 3,
    selected_count: 3,
    rerank_applied: false,
    embedding_model: "model-a",
    llm_model: "model-b",
  },
  created_at: "2026-06-01T10:10:00Z",
};

describe("ChatPage feedback", () => {
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
      session_id: "session-1",
      title: null,
      message_count: 0,
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:00:00Z",
    });
    vi.mocked(deleteChatSession).mockResolvedValue(undefined);
    vi.mocked(updateChatSession).mockResolvedValue({
      session_id: "session-1",
      title: "Renamed",
      message_count: 0,
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:01:00Z",
    });
    vi.mocked(createAgentRun).mockResolvedValue({
      run: {
        run_id: "run-1",
        status: "completed",
        steps_executed: 0,
        tool_calls_executed: 0,
        total_tokens: 0,
        total_cost_usd: 0,
        outcome: { answer: "", citations: [], confidence: { score: 0.8, category: "high" }, not_found: false, mode: "answer" },
        error: null,
      },
    });
    vi.mocked(decideAgentRunApproval).mockResolvedValue({
      approval_id: "a-1",
      agent_step_id: null,
      tool_call_id: null,
      requested_by_user_id: "u-1",
      decided_by_user_id: "u-1",
      status: "approved",
      request_summary: "",
      decision_reason: "",
      request_payload: {},
      decision_payload: {},
      expires_at: null,
      decided_at: "2026-06-01T10:00:00Z",
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:00:00Z",
    });
    vi.mocked(getAgentRun).mockResolvedValue({
      run_id: "run-1",
      organization_id: "org-1",
      user_id: "u-1",
      status: "completed",
      surface: "api",
      objective: "",
      max_steps: 12,
      max_parallel_tool_calls: 4,
      budget: { max_steps: 12, max_tool_calls: 30 },
      costs: {},
      outcome: {},
      observations: {},
      total_cost_usd: 0,
      trace_request_id: "req-1",
      error_message: null,
      error_details: {},
      started_at: null,
      completed_at: null,
      cancelled_at: null,
      created_at: "2026-06-01T10:00:00Z",
      updated_at: "2026-06-01T10:00:00Z",
      steps: [],
      tool_calls: [],
      approvals: [],
    });
    vi.mocked(submitMessageFeedback).mockResolvedValue({
      feedback_id: "fb-1",
      message_id: "msg-1",
      user_id: "u-1",
      rating: "up",
      reason: null,
      comment: null,
      created_at: "2026-06-01T10:10:00Z",
      updated_at: "2026-06-01T10:10:00Z",
    });
    vi.mocked(deleteMessageFeedback).mockResolvedValue(undefined);
    vi.mocked(listSessionFeedback).mockResolvedValue({ items: [], total: 0 });
  });

  async function submitQuestion() {
    vi.mocked(listDocuments).mockResolvedValue(INDEXED_DOCS_RESPONSE);
    vi.mocked(queryChat).mockResolvedValue(QUERY_RESPONSE);

    renderPage();

    await screen.findByRole("button", { name: /Context \([1-9]/i });
    await userEvent.type(
      screen.getByPlaceholderText("Type a message or use '/' for commands..."),
      "When is the policy active?",
    );
    await userEvent.click(screen.getByRole("button", { name: /Send message/i }));
    await screen.findByText("The policy is active.");
  }

  it("renders helpful and not-helpful buttons after an answer", async () => {
    await submitQuestion();

    expect(screen.getByRole("button", { name: /Mark answer helpful/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Report an issue/i })).toBeInTheDocument();
  });

  it("thumbs-up calls submitMessageFeedback with rating=up", async () => {
    await submitQuestion();

    await userEvent.click(screen.getByRole("button", { name: /Mark answer helpful/i }));

    await waitFor(() => {
      expect(vi.mocked(submitMessageFeedback)).toHaveBeenCalledWith(
        "msg-1",
        expect.objectContaining({ rating: "up" }),
      );
    });
  });

  it("thumbs-up again (already up) calls deleteMessageFeedback", async () => {
    vi.mocked(submitMessageFeedback).mockResolvedValue({
      feedback_id: "fb-1",
      message_id: "msg-1",
      user_id: "u-1",
      rating: "up",
      reason: null,
      comment: null,
      created_at: "2026-06-01T10:10:00Z",
      updated_at: "2026-06-01T10:10:00Z",
    });

    await submitQuestion();

    await userEvent.click(screen.getByRole("button", { name: /Mark answer helpful/i }));
    await waitFor(() => expect(vi.mocked(submitMessageFeedback)).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: /Mark answer helpful/i }));
    await waitFor(() => {
      expect(vi.mocked(deleteMessageFeedback)).toHaveBeenCalledWith("msg-1");
    });
  });

  it("thumbs-down opens FeedbackModal", async () => {
    await submitQuestion();

    await userEvent.click(screen.getByRole("button", { name: /Report an issue/i }));

    expect(screen.getByRole("dialog", { name: /Report an issue/i })).toBeInTheDocument();
    expect(screen.getByText(/What's wrong with this answer/i)).toBeInTheDocument();
  });

  it("FeedbackModal cancel closes without API call", async () => {
    await submitQuestion();

    await userEvent.click(screen.getByRole("button", { name: /Report an issue/i }));
    await userEvent.click(screen.getByRole("button", { name: /Cancel/i }));

    expect(screen.queryByRole("dialog", { name: /Report an issue/i })).not.toBeInTheDocument();
    expect(vi.mocked(submitMessageFeedback)).not.toHaveBeenCalled();
  });

  it("FeedbackModal submit calls submitMessageFeedback with rating=down and reason", async () => {
    vi.mocked(submitMessageFeedback).mockResolvedValue({
      feedback_id: "fb-2",
      message_id: "msg-1",
      user_id: "u-1",
      rating: "down",
      reason: "wrong_citation",
      comment: null,
      created_at: "2026-06-01T10:10:00Z",
      updated_at: "2026-06-01T10:10:00Z",
    });

    await submitQuestion();

    await userEvent.click(screen.getByRole("button", { name: /Report an issue/i }));
    await userEvent.click(screen.getByRole("radio", { name: /Wrong or missing citation/i }));
    await userEvent.click(screen.getByRole("button", { name: /Submit/i }));

    await waitFor(() => {
      expect(vi.mocked(submitMessageFeedback)).toHaveBeenCalledWith(
        "msg-1",
        expect.objectContaining({ rating: "down", reason: "wrong_citation" }),
      );
    });
    expect(screen.queryByRole("dialog", { name: /Report an issue/i })).not.toBeInTheDocument();
  });

  it("FeedbackModal remove-feedback calls deleteMessageFeedback", async () => {
    vi.mocked(submitMessageFeedback).mockResolvedValue({
      feedback_id: "fb-2",
      message_id: "msg-1",
      user_id: "u-1",
      rating: "down",
      reason: "hallucination",
      comment: null,
      created_at: "2026-06-01T10:10:00Z",
      updated_at: "2026-06-01T10:10:00Z",
    });

    await submitQuestion();

    // submit feedback first
    await userEvent.click(screen.getByRole("button", { name: /Report an issue/i }));
    await userEvent.click(screen.getByRole("button", { name: /Submit/i }));
    await waitFor(() => expect(vi.mocked(submitMessageFeedback)).toHaveBeenCalledTimes(1));

    // open modal again for editing
    await userEvent.click(screen.getByRole("button", { name: /Report an issue/i }));
    const dialog = screen.getByRole("dialog", { name: /Edit feedback/i });
    expect(dialog).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Remove feedback/i }));
    await waitFor(() => {
      expect(vi.mocked(deleteMessageFeedback)).toHaveBeenCalledWith("msg-1");
    });
  });

  it("loads existing feedback when opening a historical session", async () => {
    vi.mocked(listDocuments).mockResolvedValue({ ...INDEXED_DOCS_RESPONSE, items: [], total: 0 });
    vi.mocked(listChatSessions).mockResolvedValue({
      items: [{ session_id: "session-hist", title: "History", message_count: 2, created_at: "2026-06-01T09:00:00Z", updated_at: "2026-06-01T09:01:00Z" }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listChatSessionMessages).mockResolvedValue({
      items: [
        { message_id: "msg-hist-1", role: "user", content: "Q?", confidence_score: null, confidence_category: null, citations: [], created_at: "2026-06-01T09:00:00Z" },
        { message_id: "msg-hist-2", role: "assistant", content: "A!", confidence_score: 0.8, confidence_category: "high", citations: [], created_at: "2026-06-01T09:00:10Z" },
      ],
      total: 2,
      limit: 500,
      offset: 0,
    });
    vi.mocked(listSessionFeedback).mockResolvedValue({
      items: [
        {
          feedback_id: "fb-hist-1",
          message_id: "msg-hist-2",
          user_id: "u-1",
          rating: "down",
          reason: "outdated_source",
          comment: null,
          created_at: "2026-06-01T09:05:00Z",
          updated_at: "2026-06-01T09:05:00Z",
        },
      ],
      total: 1,
    });

    mockNavigation.searchParams = new URLSearchParams({ session_id: "session-hist" });

    renderPage();

    await screen.findByText("A!");
    await waitFor(() => {
      expect(vi.mocked(listSessionFeedback)).toHaveBeenCalledWith("session-hist");
    });
  });
});
