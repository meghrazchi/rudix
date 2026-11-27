import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatWSClient,
  type ChatWSClientOptions,
  type ChatWSEvent,
} from "@/lib/chat-websocket";

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

  emit(event: Partial<ChatWSEvent>): void {
    this.onmessage?.({ data: JSON.stringify(event) });
  }

  fail(code = 1006): void {
    this.readyState = 3;
    this.onerror?.();
    this.onclose?.({ code, reason: "" });
  }

  commands(): Array<{ command: string; payload?: Record<string, unknown> }> {
    return this.sent.map((raw) => JSON.parse(raw));
  }
}

const WS_URL = "ws://api.test/api/v1/chat/ws";

function last(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

function makeClient(extra: Partial<ChatWSClientOptions> = {}) {
  let n = 0;
  const getAuthParam = vi.fn(async () => ({
    name: "ticket" as const,
    value: `tkt-${++n}`,
  }));
  const events: ChatWSEvent[] = [];
  const states: string[] = [];
  const client = new ChatWSClient({
    url: WS_URL,
    getAuthParam,
    onEvent: (event) => events.push(event),
    onStateChange: (state) => states.push(state),
    random: () => 1,
    ...extra,
  });
  return { client, getAuthParam, events, states };
}

async function startRun(client: ChatWSClient): Promise<FakeWebSocket> {
  await client.connect();
  const ws = last();
  ws.open();
  client.send({ command: "chat.start", payload: { question: "q" } });
  return ws;
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ChatWSClient reconnect", () => {
  it("reconnects with a fresh ticket and resumes from the last stream sequence", async () => {
    const onReconnecting = vi.fn();
    const onReconnected = vi.fn();
    const onClose = vi.fn();
    const { client, getAuthParam, states } = makeClient({
      onReconnecting,
      onReconnected,
      onClose,
    });
    const ws = await startRun(client);
    ws.emit({
      event: "generation.started",
      message_id: "m-1",
      stream_sequence: 1,
    });
    ws.emit({
      event: "generation.delta",
      message_id: "m-1",
      stream_sequence: 2,
    });
    ws.emit({
      event: "generation.delta",
      message_id: "m-1",
      stream_sequence: 3,
    });
    ws.fail();

    expect(states).toContain("reconnecting");
    expect(onClose).toHaveBeenCalledWith(1006, "", true);
    // random() = 1, attempt 0: the full 500 ms window.
    expect(onReconnecting).toHaveBeenCalledWith(1, 500);
    await vi.advanceTimersByTimeAsync(499);
    expect(FakeWebSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);

    expect(getAuthParam).toHaveBeenCalledTimes(2);
    const next = last();
    expect(new URL(next.url).searchParams.get("ticket")).toBe("tkt-2");
    expect(new URL(next.url).searchParams.has("token")).toBe(false);
    next.open();
    expect(next.commands()).toEqual([
      {
        command: "chat.resume",
        payload: { message_id: "m-1", last_stream_sequence: 3 },
      },
    ]);
    expect(onReconnected).toHaveBeenCalledWith({
      resumed: true,
      flushed: false,
    });
    expect(client.state).toBe("connected");
  });

  it("does not reconnect when no run is in flight", async () => {
    const { client, states } = makeClient();
    await client.connect();
    last().open();
    last().fail();
    expect(states.at(-1)).toBe("error");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("stops after a terminal event ends the run", async () => {
    const { client } = makeClient();
    const ws = await startRun(client);
    ws.emit({ event: "chat.completed", message_id: "m-1", stream_sequence: 9 });
    expect(client.resumeCommand()).toBeNull();
    ws.fail(1001);
    expect(client.state).toBe("error");
  });

  it("backs off exponentially and gives up after the configured attempts", async () => {
    const onReconnecting = vi.fn();
    const onReconnectFailed = vi.fn();
    const { client } = makeClient({
      reconnect: { baseMs: 100, capMs: 300, maxAttempts: 3 },
      onReconnecting,
      onReconnectFailed,
    });
    const ws = await startRun(client);
    ws.emit({
      event: "generation.started",
      message_id: "m-1",
      stream_sequence: 1,
    });
    ws.fail();
    for (const delay of [100, 200, 300]) {
      await vi.advanceTimersByTimeAsync(delay);
      last().fail();
    }
    expect(onReconnecting.mock.calls).toEqual([
      [1, 100],
      [2, 200],
      [3, 300],
    ]);
    expect(onReconnectFailed).toHaveBeenCalledWith("attempts_exhausted");
    expect(client.state).toBe("error");
    expect(FakeWebSocket.instances).toHaveLength(4);
  });

  it("applies full jitter to the scheduled delay", async () => {
    const onReconnecting = vi.fn();
    const { client } = makeClient({ random: () => 0.25, onReconnecting });
    const ws = await startRun(client);
    ws.emit({ event: "generation.started", message_id: "m-1" });
    ws.fail();
    expect(onReconnecting).toHaveBeenCalledWith(1, 125);
  });

  it("does not retry a non-retryable close code", async () => {
    const onReconnectFailed = vi.fn();
    const { client } = makeClient({ onReconnectFailed });
    const ws = await startRun(client);
    ws.emit({ event: "generation.started", message_id: "m-1" });
    ws.onclose?.({ code: 4401, reason: "Unauthorized" });
    expect(client.state).toBe("disconnected");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(onReconnectFailed).not.toHaveBeenCalled();
  });

  it("reports a non-retryable close during a reconnect", async () => {
    const onReconnectFailed = vi.fn();
    const { client } = makeClient({ onReconnectFailed });
    const ws = await startRun(client);
    ws.emit({ event: "generation.started", message_id: "m-1" });
    ws.fail();
    await vi.advanceTimersByTimeAsync(500);
    last().onclose?.({ code: 4403, reason: "role" });
    expect(onReconnectFailed).toHaveBeenCalledWith("non_retryable");
  });

  it("sends an unsent chat.start instead of a resume after the socket failed to open", async () => {
    const onReconnected = vi.fn();
    const { client } = makeClient({ onReconnected });
    await client.connect();
    client.send({ command: "chat.start", payload: { question: "q" } });
    last().fail();
    await vi.advanceTimersByTimeAsync(500);
    last().open();
    expect(
      last()
        .commands()
        .map((c) => c.command),
    ).toEqual(["chat.start"]);
    expect(onReconnected).toHaveBeenCalledWith({
      resumed: false,
      flushed: true,
    });
  });

  it("resumes before sending a chat.cancel queued during the retry", async () => {
    const onReconnected = vi.fn();
    const { client } = makeClient({ onReconnected });
    const ws = await startRun(client);
    ws.emit({
      event: "generation.started",
      message_id: "m-1",
      stream_sequence: 1,
    });
    ws.fail();
    client.send({ command: "chat.cancel" });
    await vi.advanceTimersByTimeAsync(500);
    last().open();
    expect(last().commands()).toEqual([
      {
        command: "chat.resume",
        payload: { message_id: "m-1", last_stream_sequence: 1 },
      },
      { command: "chat.cancel" },
    ]);
    expect(onReconnected).toHaveBeenCalledWith({
      resumed: true,
      flushed: false,
    });
  });

  it("reports nothing to resume when only a chat.cancel was queued before a message id", async () => {
    const onReconnected = vi.fn();
    const { client } = makeClient({ onReconnected });
    const ws = await startRun(client);
    ws.fail();
    client.send({ command: "chat.cancel" });
    await vi.advanceTimersByTimeAsync(500);
    last().open();
    expect(onReconnected).toHaveBeenCalledWith({
      resumed: false,
      flushed: false,
    });
    expect(client.resumeCommand()).toBeNull();
  });

  it("reports nothing to resume when the drop came before a message id", async () => {
    const onReconnected = vi.fn();
    const { client } = makeClient({ onReconnected });
    const ws = await startRun(client);
    ws.emit({ event: "retrieval.started", message_id: null });
    ws.fail();
    await vi.advanceTimersByTimeAsync(500);
    last().open();
    expect(last().commands()).toEqual([]);
    expect(onReconnected).toHaveBeenCalledWith({
      resumed: false,
      flushed: false,
    });
  });

  it("retries when the ticket fetch fails during a reconnect", async () => {
    let calls = 0;
    const getAuthParam = vi.fn(async () => {
      calls += 1;
      if (calls === 2) throw new Error("503");
      return { name: "ticket" as const, value: `tkt-${calls}` };
    });
    const onAuthError = vi.fn();
    const { client } = makeClient({ getAuthParam, onAuthError });
    const ws = await startRun(client);
    ws.emit({
      event: "generation.started",
      message_id: "m-1",
      stream_sequence: 1,
    });
    ws.fail();
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(client.state).toBe("reconnecting");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(new URL(last().url).searchParams.get("ticket")).toBe("tkt-3");
    expect(onAuthError).not.toHaveBeenCalled();
  });

  it("gives up when the ticket keeps failing during reconnects", async () => {
    let calls = 0;
    const getAuthParam = vi.fn(async () => {
      calls += 1;
      if (calls > 1) throw new Error("503");
      return { name: "ticket" as const, value: "tkt-1" };
    });
    const onAuthError = vi.fn();
    const onReconnectFailed = vi.fn();
    const { client } = makeClient({
      getAuthParam,
      onAuthError,
      onReconnectFailed,
      reconnect: { maxAttempts: 2, baseMs: 10, capMs: 10 },
    });
    const ws = await startRun(client);
    ws.emit({ event: "generation.started", message_id: "m-1" });
    ws.fail();
    await vi.advanceTimersByTimeAsync(50);
    expect(onReconnectFailed).toHaveBeenCalledWith("attempts_exhausted");
    expect(onAuthError).toHaveBeenCalledTimes(1);
    expect(client.state).toBe("error");
  });

  it("queues commands while reconnecting and close() cancels the retry", async () => {
    const { client } = makeClient({ reconnect: false });
    const ws = await startRun(client);
    ws.emit({ event: "generation.started", message_id: "m-1" });
    ws.fail();
    expect(client.state).toBe("error");

    const second = makeClient();
    const ws2 = await startRun(second.client);
    ws2.emit({ event: "generation.started", message_id: "m-2" });
    ws2.fail();
    second.client.send({ command: "chat.cancel" });
    second.client.close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(second.client.state).toBe("idle");
  });

  it("restarts the sequence when a new message id appears", async () => {
    const { client } = makeClient();
    const ws = await startRun(client);
    ws.emit({
      event: "generation.started",
      message_id: "m-1",
      stream_sequence: 4,
    });
    ws.emit({
      event: "generation.started",
      message_id: "m-2",
      stream_sequence: 1,
    });
    expect(client.resumeCommand()).toEqual({
      command: "chat.resume",
      payload: { message_id: "m-2", last_stream_sequence: 1 },
    });
  });
});
