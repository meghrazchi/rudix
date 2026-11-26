import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { ChatPage } from "@/components/chat/ChatPage";
import { listChatSessionMessages, listChatSessions } from "@/lib/api/chat";
import {
  listCollectionDocuments,
  listCollections,
} from "@/lib/api/collections";
import { listAvailableConnectorConnections } from "@/lib/api/connectors";
import { listDocuments } from "@/lib/api/documents";
import type { UseChatWebSocketResult } from "@/lib/use-chat-websocket";

vi.hoisted(() => {
  // Module-level constants in ChatPage are frozen at import time.
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED = "true";
  process.env.NEXT_PUBLIC_CHAT_STREAMING_ENABLED = "false";
});

const mockWs = vi.hoisted(() => ({ error: null as string | null }));

vi.mock("@/lib/use-chat-websocket", () => ({
  useChatWebSocket: (): UseChatWebSocketResult => ({
    phase: mockWs.error ? "error" : "idle",
    partialAnswer: "",
    finalResponse: null,
    error: mockWs.error,
    isPending: false,
    timelineSteps: [],
    sendQuery: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: { status: "unauthenticated", session: null },
    boundaryEvent: null,
    boundaryMessageKey: null,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
    clearBoundaryEvent: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  downloadDocumentFile: vi.fn(),
  getDocumentChunks: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/api/collections", () => ({
  listCollections: vi.fn(),
  listCollectionDocuments: vi.fn(),
}));

vi.mock("@/lib/api/connectors", () => ({
  listAvailableConnectorConnections: vi.fn(),
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
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

describe("ChatPage WebSocket error messages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
    vi.mocked(listDocuments).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
      status: "indexed",
      sort_by: "updated_at",
      sort_order: "desc",
    });
    vi.mocked(listCollections).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(listCollectionDocuments).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(listAvailableConnectorConnections).mockResolvedValue({
      items: [],
      total: 0,
    });
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

  it("shows a translated message for plan_limit_exceeded", async () => {
    mockWs.error = "plan_limit_exceeded";

    renderPage();

    expect(
      await screen.findByText(
        "Your plan's question limit has been reached. Upgrade your plan or try again after the limit resets.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("plan_limit_exceeded")).not.toBeInTheDocument();
  });

  it("falls back to the generic message for unmapped codes", async () => {
    mockWs.error = "retrieval_failed";

    renderPage();

    expect(
      await screen.findByText("Unable to complete the query."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/question limit has been reached/),
    ).not.toBeInTheDocument();
  });
});
