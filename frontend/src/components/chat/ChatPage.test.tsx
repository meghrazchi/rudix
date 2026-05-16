import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatPage } from "@/components/chat/ChatPage";
import { listChatSessionMessages, listChatSessions, queryChat } from "@/lib/api/chat";
import { listDocuments } from "@/lib/api/documents";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/chat", () => ({
  listChatSessionMessages: vi.fn(),
  listChatSessions: vi.fn(),
  queryChat: vi.fn(),
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

    expect(await screen.findByText("The policy is active as of May 2026.")).toBeInTheDocument();
    expect(screen.getByText("Low confidence warning: validate this answer against the cited source text.")).toBeInTheDocument();
    expect(screen.getByText("Policy became active in May 2026.")).toBeInTheDocument();
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

    expect(await screen.findByText("What is the policy date?")).toBeInTheDocument();
    expect(screen.getByText("The policy date is May 2026.")).toBeInTheDocument();
  });
});
