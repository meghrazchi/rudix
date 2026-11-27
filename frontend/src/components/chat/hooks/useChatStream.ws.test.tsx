import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { useChatStream } from "@/components/chat/hooks/useChatStream";
import { queryChat, type ChatQueryResponse } from "@/lib/api/chat";
import type { UseChatWebSocketResult } from "@/lib/use-chat-websocket";

vi.hoisted(() => {
  // CHAT_WEBSOCKET_ENABLED is a module-level constant frozen at import time.
  process.env.NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED = "true";
});

const ws = vi.hoisted(() => ({
  state: {
    phase: "idle",
    partialAnswer: "",
    finalResponse: null,
    error: null,
    isPending: false,
    timelineSteps: [],
  } as Pick<
    UseChatWebSocketResult,
    | "phase"
    | "partialAnswer"
    | "finalResponse"
    | "error"
    | "isPending"
    | "timelineSteps"
  >,
  sendQuery: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("@/lib/use-chat-websocket", () => ({
  useChatWebSocket: (): UseChatWebSocketResult => ({
    ...ws.state,
    sendQuery: ws.sendQuery,
    cancel: ws.cancel,
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

const finalResponse = {
  chat_session_id: "session-1",
  message_id: "message-1",
} as unknown as ChatQueryResponse;

describe("useChatStream (WebSocket transport)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ws.state = {
      phase: "idle",
      partialAnswer: "",
      finalResponse: null,
      error: null,
      isPending: false,
      timelineSteps: [],
    };
  });

  it("sends over the socket and reports completion with the request context", async () => {
    const onCompleted = vi.fn();
    const onAborted = vi.fn();
    const { result, rerender } = renderHook(
      () => useChatStream({ onCompleted, onFailed: vi.fn(), onAborted }),
      { wrapper },
    );

    act(() => {
      result.current.send({
        question: "When did it start?",
        rerank: true,
        chat_session_id: "session-1",
        _scopeLabel: "All documents",
      });
    });
    expect(ws.sendQuery).toHaveBeenCalledWith(
      expect.objectContaining({ question: "When did it start?" }),
    );
    expect(queryChat).not.toHaveBeenCalled();

    ws.state = { ...ws.state, phase: "generating", isPending: true };
    rerender();
    expect(result.current.isPending).toBe(true);
    expect(result.current.phaseLabel).toBe("Generating answer...");

    ws.state = {
      ...ws.state,
      phase: "completed",
      isPending: false,
      finalResponse,
    };
    rerender();

    await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
    expect(onCompleted).toHaveBeenCalledWith(finalResponse, {
      question: "When did it start?",
      sessionId: "session-1",
      scopeLabel: "All documents",
    });

    // A re-render with the same completed state does not report it twice.
    rerender();
    await Promise.resolve();
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(onAborted).not.toHaveBeenCalled();
  });

  it("ignores a completed frame when nothing was sent", async () => {
    const onCompleted = vi.fn();
    ws.state = { ...ws.state, phase: "completed", finalResponse };
    renderHook(
      () =>
        useChatStream({ onCompleted, onFailed: vi.fn(), onAborted: vi.fn() }),
      { wrapper },
    );
    await Promise.resolve();
    expect(onCompleted).not.toHaveBeenCalled();
  });

  it("reports an aborted run and exposes the socket error", async () => {
    const onAborted = vi.fn();
    const { result, rerender } = renderHook(
      () =>
        useChatStream({ onCompleted: vi.fn(), onFailed: vi.fn(), onAborted }),
      { wrapper },
    );

    ws.state = { ...ws.state, phase: "error", error: "rate_limited" };
    rerender();

    await waitFor(() => expect(onAborted).toHaveBeenCalledTimes(1));
    expect(result.current.wsError).toBe("rate_limited");
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("rate_limited");
    expect(result.current.httpPending).toBe(false);
  });

  it("maps each phase to its label and cancels through the socket", () => {
    const { result, rerender } = renderHook(
      () =>
        useChatStream({
          onCompleted: vi.fn(),
          onFailed: vi.fn(),
          onAborted: vi.fn(),
        }),
      { wrapper },
    );
    expect(result.current.phaseLabel).toBeNull();

    const cases: Array<[UseChatWebSocketResult["phase"], string]> = [
      ["retrieving", "Retrieving sources..."],
      ["reranking", "Ranking sources..."],
      ["validating_citations", "Validating citations..."],
    ];
    for (const [phase, label] of cases) {
      ws.state = { ...ws.state, phase, isPending: true };
      rerender();
      expect(result.current.phaseLabel).toBe(label);
    }

    ws.state = { ...ws.state, phase: "idle", isPending: true };
    rerender();
    expect(result.current.phaseLabel).toBe("Connecting...");

    result.current.cancel();
    expect(ws.cancel).toHaveBeenCalledTimes(1);
  });
});
