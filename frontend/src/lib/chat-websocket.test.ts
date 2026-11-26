import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChatWSClient,
  type ChatWSAuthParam,
  type ChatWSClientState,
  type ChatWSEvent,
} from "@/lib/chat-websocket";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  closeCalls: Array<[number | undefined, string | undefined]> = [];
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

  close(code?: number, reason?: string): void {
    this.closeCalls.push([code, reason]);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  drop(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" });
  }
}

const WS_URL = "ws://api.test/api/v1/chat/ws";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function makeClient(
  getAuthParam: () => Promise<ChatWSAuthParam>,
  extra: {
    onAuthError?: (error: unknown) => void;
    onEvent?: (event: ChatWSEvent) => void;
  } = {},
) {
  const states: ChatWSClientState[] = [];
  const client = new ChatWSClient({
    url: WS_URL,
    getAuthParam,
    onAuthError: extra.onAuthError,
    onEvent: extra.onEvent ?? (() => undefined),
    onStateChange: (state) => states.push(state),
  });
  return { client, states };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatWSClient auth", () => {
  it("connects with ?ticket= and never puts a token in the URL", async () => {
    const { client } = makeClient(async () => ({
      name: "ticket",
      value: "tkt-1",
    }));
    await client.connect();
    const url = new URL(FakeWebSocket.instances[0].url);
    expect(url.searchParams.get("ticket")).toBe("tkt-1");
    expect(url.searchParams.has("token")).toBe(false);
  });

  it("guards re-entry while a connect is in flight", async () => {
    const gate = deferred<ChatWSAuthParam>();
    const getAuthParam = vi.fn(() => gate.promise);
    const { client } = makeClient(getAuthParam);
    const first = client.connect();
    expect(client.connect()).toBe(first);
    gate.resolve({ name: "ticket", value: "t" });
    await first;
    await client.connect();
    expect(getAuthParam).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("fetches a fresh ticket on reconnect", async () => {
    let n = 0;
    const getAuthParam = vi.fn(async () => ({
      name: "ticket" as const,
      value: `tkt-${++n}`,
    }));
    const { client } = makeClient(getAuthParam);
    await client.connect();
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].drop();
    expect(client.state).toBe("disconnected");
    await client.connect();
    expect(getAuthParam).toHaveBeenCalledTimes(2);
    expect(
      new URL(FakeWebSocket.instances[1].url).searchParams.get("ticket"),
    ).toBe("tkt-2");
  });

  it("flushes a command sent during the ticket fetch once open", async () => {
    const gate = deferred<ChatWSAuthParam>();
    const { client } = makeClient(() => gate.promise);
    const pending = client.connect();
    expect(client.state).toBe("connecting");
    client.send({ command: "chat.start", payload: { question: "hi" } });
    gate.resolve({ name: "ticket", value: "t" });
    await pending;
    const ws = FakeWebSocket.instances[0];
    expect(ws.sent).toEqual([]);
    ws.open();
    expect(ws.sent.map((raw) => JSON.parse(raw).command)).toEqual([
      "chat.start",
    ]);
    expect(client.state).toBe("connected");
  });

  it("opens no socket when close() runs during the ticket fetch", async () => {
    const gate = deferred<ChatWSAuthParam>();
    const { client } = makeClient(() => gate.promise);
    const pending = client.connect();
    client.close();
    gate.resolve({ name: "ticket", value: "t" });
    await pending;
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(client.state).toBe("idle");
  });

  it("enters the error state and drops queued commands on auth failure", async () => {
    const failure = new Error("ticket unavailable");
    const onAuthError = vi.fn();
    const { client, states } = makeClient(() => Promise.reject(failure), {
      onAuthError,
    });
    const pending = client.connect();
    client.send({ command: "chat.start" });
    await pending;
    expect(client.state).toBe("error");
    expect(states).toEqual(["connecting", "error"]);
    expect(onAuthError).toHaveBeenCalledWith(failure);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("ignores an auth failure that lands after close()", async () => {
    const gate = deferred<ChatWSAuthParam>();
    const onAuthError = vi.fn();
    const { client } = makeClient(
      () => gate.promise.then(() => Promise.reject(new Error("x"))),
      { onAuthError },
    );
    const pending = client.connect();
    client.close();
    gate.resolve({ name: "ticket", value: "t" });
    await pending;
    expect(onAuthError).not.toHaveBeenCalled();
    expect(client.state).toBe("idle");
  });

  it("answers heartbeat pings and forwards events", async () => {
    const events: ChatWSEvent[] = [];
    const { client } = makeClient(
      async () => ({ name: "ticket", value: "t" }),
      { onEvent: (event) => events.push(event) },
    );
    await client.connect();
    const ws = FakeWebSocket.instances[0];
    ws.open();
    ws.onmessage?.({ data: JSON.stringify({ event: "heartbeat.ping" }) });
    ws.onmessage?.({ data: "not json" });
    expect(events.map((e) => e.event)).toEqual(["heartbeat.ping"]);
    expect(JSON.parse(ws.sent[0]).command).toBe("heartbeat.pong");
  });
});
