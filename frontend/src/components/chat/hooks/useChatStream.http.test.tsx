import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { useChatStream } from "@/components/chat/hooks/useChatStream";
import { queryChat, type ChatQueryResponse } from "@/lib/api/chat";
import type { UseChatWebSocketResult } from "@/lib/use-chat-websocket";

vi.hoisted(() => {
  // CHAT_WEBSOCKET_ENABLED is a module-level constant frozen at import time.
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED = "false";
});

const ws = vi.hoisted(() => ({ sendQuery: vi.fn() }));

vi.mock("@/lib/use-chat-websocket", () => ({
  useChatWebSocket: (): UseChatWebSocketResult => ({
    phase: "idle",
    partialAnswer: "",
    finalResponse: null,
    error: "ignored_when_http",
    isPending: true,
    timelineSteps: [],
    sendQuery: ws.sendQuery,
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("@/lib/api/chat", () => ({
  queryChat: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useChatStream (HTTP transport)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the question and reports completion with the request context", async () => {
    const response = {
      chat_session_id: null,
      message_id: "message-1",
    } as unknown as ChatQueryResponse;
    vi.mocked(queryChat).mockResolvedValue(response);
    const onCompleted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(
      () => useChatStream({ onCompleted, onFailed, onAborted: vi.fn() }),
      { wrapper },
    );

    // The socket state is ignored when the HTTP transport is active.
    expect(result.current.isPending).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.phaseLabel).toBeNull();

    act(() => {
      result.current.send({
        question: "When did it start?",
        rerank: true,
        chat_session_id: null,
        _scopeLabel: "All documents",
      });
    });

    await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
    expect(ws.sendQuery).not.toHaveBeenCalled();
    expect(vi.mocked(queryChat).mock.calls[0][0]).toMatchObject({
      question: "When did it start?",
    });
    expect(onCompleted).toHaveBeenCalledWith(response, {
      question: "When did it start?",
      sessionId: null,
      scopeLabel: "All documents",
    });
    expect(onFailed).not.toHaveBeenCalled();
  });

  it("reports a failed request to both the stream and the caller", async () => {
    const failure = new Error("boom");
    vi.mocked(queryChat).mockRejectedValue(failure);
    const onFailed = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(
      () =>
        useChatStream({ onCompleted: vi.fn(), onFailed, onAborted: vi.fn() }),
      { wrapper },
    );

    act(() => {
      result.current.send(
        { question: "Q", chat_session_id: "s", rerank: true },
        { onError },
      );
    });

    await waitFor(() => expect(onFailed).toHaveBeenCalledWith(failure));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toBe(failure);
    await waitFor(() => expect(result.current.error).toBe(failure));
    expect(result.current.httpPending).toBe(false);
  });
});
