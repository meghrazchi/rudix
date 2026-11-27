import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const resolveChatWsAuthParam = vi.fn();

vi.mock("@/lib/chat-ws-auth", () => ({
  resolveChatWsAuthParam: () => resolveChatWsAuthParam(),
}));

import type { ChatWSEvent } from "@/lib/chat-websocket";
import { useChatWebSocket } from "@/lib/use-chat-websocket";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((evt: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((evt: { code: number; reason: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {}

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  drop(): void {
    this.readyState = 3;
    this.onclose?.({ code: 1006, reason: "" });
  }
}

function last(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

function emit(ws: FakeWebSocket, event: Partial<ChatWSEvent>) {
  act(() => {
    ws.onmessage?.({
      data: JSON.stringify({ message_id: "m-1", payload: null, ...event }),
    });
  });
}

const response = {
  chat_session_id: "s-1",
  message_id: "m-1",
  answer: "Final answer.",
};

async function startedRun() {
  const hook = renderHook(() => useChatWebSocket());
  act(() => hook.result.current.sendQuery({ question: "q", rerank: true }));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  act(() => last().open());
  return hook;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  resolveChatWsAuthParam.mockReset();
  let n = 0;
  resolveChatWsAuthParam.mockImplementation(async () => ({
    name: "ticket",
    value: `tkt-${++n}`,
  }));
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useChatWebSocket streaming and resume", () => {
  it("writes deltas into the text store and exposes partialAnswer live", async () => {
    const { result } = await startedRun();
    const store = result.current.textStore!;
    emit(last(), { event: "generation.started", stream_sequence: 1 });
    emit(last(), {
      event: "generation.delta",
      stream_sequence: 2,
      payload: { text: "Hello " },
    });
    emit(last(), {
      event: "generation.delta",
      stream_sequence: 3,
      payload: { text: "world" },
    });
    expect(result.current.partialAnswer).toBe("Hello world");
    expect(store.getText()).toBe("Hello world");
    expect(result.current.phase).toBe("generating");
  });

  it("replaces all streamed text and then sets the final text", async () => {
    const { result } = await startedRun();
    const store = result.current.textStore!;
    emit(last(), { event: "generation.delta", payload: { text: "Draft" } });
    emit(last(), {
      event: "generation.replace",
      payload: { text: "Verified", reason: "verification" },
    });
    expect(result.current.partialAnswer).toBe("Verified");
    emit(last(), { event: "generation.replace", payload: {} });
    expect(result.current.partialAnswer).toBe("Verified");
    emit(last(), {
      event: "generation.final",
      payload: { answer: "Final answer.", not_found: false, citations: [] },
    });
    expect(result.current.partialAnswer).toBe("Final answer.");
    await waitFor(() => expect(store.getSnapshot().final).toBe(true));

    emit(last(), {
      event: "chat.completed",
      payload: { response },
    });
    expect(result.current.phase).toBe("completed");
    expect(result.current.finalResponse).toEqual(response);
    expect(result.current.partialAnswer).toBe("");
  });

  it("treats a final without an answer string as empty text", async () => {
    const { result } = await startedRun();
    emit(last(), { event: "generation.delta", payload: { text: "x" } });
    emit(last(), { event: "generation.final", payload: { not_found: true } });
    expect(result.current.partialAnswer).toBe("");
  });

  it("resumes after a drop and discards replayed events it already applied", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = await startedRun();
    const first = last();
    emit(first, { event: "generation.started", stream_sequence: 1 });
    emit(first, {
      event: "generation.delta",
      stream_sequence: 2,
      payload: { text: "The answer " },
    });
    emit(first, {
      event: "generation.delta",
      stream_sequence: 3,
      payload: { text: "is " },
    });
    act(() => first.drop());
    expect(result.current.reconnecting).toBe(true);
    expect(result.current.phase).toBe("generating");
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    const second = last();
    act(() => second.open());
    expect(JSON.parse(second.sent[0])).toEqual({
      command: "chat.resume",
      payload: { message_id: "m-1", last_stream_sequence: 3 },
    });

    emit(second, { event: "chat.resumed", payload: { replayed: 2 } });
    expect(result.current.reconnecting).toBe(false);
    // Overlapping replay: sequence 3 was applied before the drop.
    emit(second, {
      event: "generation.delta",
      stream_sequence: 3,
      payload: { text: "is " },
    });
    emit(second, {
      event: "generation.delta",
      stream_sequence: 4,
      payload: { text: "42." },
    });
    expect(result.current.partialAnswer).toBe("The answer is 42.");

    emit(second, {
      event: "chat.completed",
      stream_sequence: 5,
      payload: { response },
    });
    const completed = result.current.finalResponse;
    expect(completed).toEqual(response);
    // A duplicate terminal frame (e.g. rebuilt from the stored message) is ignored.
    emit(second, {
      event: "chat.completed",
      payload: { response: { ...response, answer: "other" } },
    });
    expect(result.current.finalResponse).toBe(completed);
  });

  it("fails with resume_unavailable when the drop came before a message id", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = await startedRun();
    emit(last(), { event: "retrieval.started", message_id: null });
    act(() => last().drop());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    act(() => last().open());
    expect(result.current.phase).toBe("error");
    expect(result.current.error).toBe("resume_unavailable");
    expect(result.current.reconnecting).toBe(false);
  });

  it("surfaces server resume_unavailable and provider_busy codes", async () => {
    const { result } = await startedRun();
    emit(last(), {
      event: "chat.error",
      safe_error_code: "provider_busy",
    });
    expect(result.current.error).toBe("provider_busy");
    expect(result.current.phase).toBe("error");

    act(() => result.current.reset());
    expect(result.current.phase).toBe("idle");
    expect(result.current.partialAnswer).toBe("");
  });

  it("reports ws_ticket_unavailable when no ticket can be issued for a reconnect", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = await startedRun();
    emit(last(), { event: "generation.started", stream_sequence: 1 });
    resolveChatWsAuthParam.mockRejectedValue(new Error("down"));
    act(() => last().drop());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200_000);
    });
    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("ws_ticket_unavailable");
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reports connection_lost when every reconnect attempt drops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = await startedRun();
    emit(last(), { event: "generation.started", stream_sequence: 1 });
    act(() => last().drop());
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const before = FakeWebSocket.instances.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });
      await waitFor(() =>
        expect(FakeWebSocket.instances.length).toBe(before + 1),
      );
      act(() => last().drop());
    }
    expect(result.current.phase).toBe("error");
    expect(result.current.error).toBe("connection_lost");
    expect(result.current.reconnecting).toBe(false);
  });
});
