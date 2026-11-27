import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatSession } from "@/components/chat/hooks/useChatSession";
import {
  listChatSessionMessages,
  listChatSessions,
  type ChatSessionMessageResponse,
} from "@/lib/api/chat";

vi.mock("@/lib/api/chat", () => ({
  createChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  listChatSessionMessages: vi.fn(),
  listChatSessions: vi.fn(),
  updateChatSession: vi.fn(),
}));

vi.mock("@/lib/api/feedback", () => ({
  listSessionFeedback: vi.fn(async () => ({ items: [] })),
}));

function message(
  id: string,
  role: "user" | "assistant",
  minute: number,
): ChatSessionMessageResponse {
  return {
    message_id: id,
    role,
    content: `${role}-${id}`,
    confidence_score: role === "assistant" ? 0.9 : null,
    confidence_category: role === "assistant" ? "high" : null,
    citations: [],
    created_at: new Date(Date.UTC(2026, 4, 14, 10, minute)).toISOString(),
  } as ChatSessionMessageResponse;
}

// Conversation of four turns, minute 0..7; pages of three, newest first.
const asc = [0, 1, 2, 3].flatMap((turn) => [
  message(`u${turn}`, "user", turn * 2),
  message(`a${turn}`, "assistant", turn * 2 + 1),
]);
const desc = [...asc].reverse();

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function render() {
  return renderHook(
    () =>
      useChatSession({
        searchParams: new URLSearchParams("session_id=s-1"),
        chatFeedbackEnabled: false,
        setFeedbackByMessageId: vi.fn(),
        setQuestion: vi.fn(),
      }),
    { wrapper },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listChatSessions).mockResolvedValue({
    items: [],
    total: 0,
    limit: 10,
    offset: 0,
  });
});

describe("useChatSession newest-first history (R05-11)", () => {
  it("loads the newest page with order=desc, then older pages by cursor", async () => {
    vi.mocked(listChatSessionMessages)
      .mockResolvedValueOnce({
        items: desc.slice(0, 3),
        total: null,
        limit: 3,
        offset: 0,
        next_cursor: "c-1",
      })
      .mockResolvedValueOnce({
        items: desc.slice(3, 6),
        total: null,
        limit: 3,
        offset: 0,
        next_cursor: "c-2",
      })
      .mockResolvedValueOnce({
        items: desc.slice(6),
        total: null,
        limit: 3,
        offset: 0,
        next_cursor: null,
      });

    const { result } = render();
    await waitFor(() => expect(result.current.thread).toHaveLength(1));
    expect(vi.mocked(listChatSessionMessages).mock.calls[0]).toEqual([
      "s-1",
      { limit: 100, order: "desc" },
    ]);
    // a3, u3, a2: a2's question is on the older page, so only turn 3 shows.
    expect(result.current.thread[0].response.message_id).toBe("a3");
    expect(result.current.hasOlderMessages).toBe(true);

    await act(async () => {
      expect(await result.current.loadOlderMessages()).toBe(true);
    });
    expect(vi.mocked(listChatSessionMessages).mock.calls[1]).toEqual([
      "s-1",
      { limit: 100, order: "desc", cursor: "c-1" },
    ]);
    expect(result.current.thread.map((t) => t.response.message_id)).toEqual([
      "a1",
      "a2",
      "a3",
    ]);
    expect(result.current.thread[1].question).toBe("user-u2");

    await act(async () => {
      await result.current.loadOlderMessages();
    });
    expect(result.current.thread.map((t) => t.response.message_id)).toEqual([
      "a0",
      "a1",
      "a2",
      "a3",
    ]);
    expect(result.current.hasOlderMessages).toBe(false);
    await act(async () => {
      expect(await result.current.loadOlderMessages()).toBe(false);
    });
    expect(listChatSessionMessages).toHaveBeenCalledTimes(3);
  });

  it("keeps the thread and exposes the error when an older page fails", async () => {
    vi.mocked(listChatSessionMessages)
      .mockResolvedValueOnce({
        items: desc.slice(0, 2),
        total: null,
        limit: 2,
        offset: 0,
        next_cursor: "c-1",
      })
      .mockRejectedValueOnce(new Error("offline"));
    const { result } = render();
    await waitFor(() => expect(result.current.thread).toHaveLength(1));
    await act(async () => {
      expect(await result.current.loadOlderMessages()).toBe(false);
    });
    expect(result.current.olderMessagesError).toBeInstanceOf(Error);
    expect(result.current.isLoadingOlder).toBe(false);
    expect(result.current.thread).toHaveLength(1);
    expect(result.current.hasOlderMessages).toBe(true);
  });
});
