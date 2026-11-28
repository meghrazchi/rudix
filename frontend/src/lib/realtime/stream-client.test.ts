import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockContext = vi.hoisted(() => ({
  token: "token-1" as string | null,
}));

vi.mock("@/lib/api/request", () => ({
  getSessionRequestContext: () => ({
    token: mockContext.token,
    organizationId: "11111111-1111-4111-8111-111111111111",
    userId: "u-1",
  }),
  refreshAccessToken: vi.fn(async () => null),
}));

import {
  BACKOFF_CAP_MS,
  HIDDEN_CLOSE_MS,
  RealtimeStreamClient,
  UNAVAILABLE_RETRY_MS,
  backoffDelay,
} from "@/lib/realtime/stream-client";
import type { RealtimeEvent, RealtimeStatus } from "@/lib/realtime/types";
import { refreshAccessToken } from "@/lib/api/request";

type Opened = {
  url: string;
  headers: Headers;
  controller: ReadableStreamDefaultController<Uint8Array> | null;
  signal: AbortSignal | undefined;
};

function frame(id: number, documentId: string): string {
  const data = JSON.stringify({
    type: "document.status",
    organization_id: "o",
    occurred_at: "",
    payload: { document_id: documentId, status: "indexed" },
  });
  return `id: ${id}\nevent: document.status\ndata: ${data}\n\n`;
}

function streamingFetch(statuses: number[]) {
  const opened: Opened[] = [];
  const encoder = new TextEncoder();
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    const status = statuses.shift() ?? 200;
    const record: Opened = {
      url,
      headers: new Headers(init?.headers),
      controller: null,
      signal: init?.signal ?? undefined,
    };
    opened.push(record);
    if (status !== 200) {
      return new Response(null, { status });
    }
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        record.controller = controller;
        init?.signal?.addEventListener("abort", () => {
          try {
            controller.error(new DOMException("aborted", "AbortError"));
          } catch {
            // already closed
          }
        });
      },
    });
    return new Response(body, { status: 200 });
  });
  const push = (index: number, text: string) =>
    opened[index].controller?.enqueue(encoder.encode(text));
  const end = (index: number) => opened[index].controller?.close();
  return { fetchImpl, opened, push, end };
}

function makeClient(fetchImpl: typeof fetch, random = () => 1) {
  const events: RealtimeEvent[] = [];
  const statuses: RealtimeStatus[] = [];
  const onResync = vi.fn();
  const client = new RealtimeStreamClient({
    fetchImpl,
    random,
    onEvent: (event) => events.push(event),
    onStatus: (status) => statuses.push(status),
    onResync,
  });
  return { client, events, statuses, onResync };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://api.test");
  mockContext.token = "token-1";
  vi.mocked(refreshAccessToken).mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("backoffDelay", () => {
  it("uses full jitter with a 500 ms base and a 30 s cap", () => {
    expect(backoffDelay(0, () => 0.999)).toBe(499);
    expect(backoffDelay(3, () => 0.5)).toBe(2000);
    expect(backoffDelay(20, () => 1)).toBe(BACKOFF_CAP_MS);
    expect(backoffDelay(5, () => 0)).toBe(0);
  });
});

describe("RealtimeStreamClient", () => {
  it("connects with a bearer header, delivers events, and resumes from Last-Event-ID", async () => {
    const net = streamingFetch([200, 200]);
    const { client, events, statuses } = makeClient(
      net.fetchImpl as unknown as typeof fetch,
    );
    client.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(net.opened[0].url).toBe("http://api.test/events/stream");
    expect(net.opened[0].url).not.toContain("token");
    expect(net.opened[0].headers.get("Authorization")).toBe("Bearer token-1");
    expect(net.opened[0].headers.get("X-Organization-ID")).toBe(
      "11111111-1111-4111-8111-111111111111",
    );
    expect(net.opened[0].headers.get("Last-Event-ID")).toBeNull();
    expect(statuses).toEqual(["connected"]);

    net.push(0, ": keep-alive\n\n" + frame(4, "d1"));
    net.push(0, frame(5, "d2"));
    await vi.advanceTimersByTimeAsync(0);
    expect(events.map((event) => event.payload)).toEqual([
      { document_id: "d1", status: "indexed" },
      { document_id: "d2", status: "indexed" },
    ]);

    // A long-lived stream that the server ends reconnects at once.
    await vi.advanceTimersByTimeAsync(6_000);
    net.end(0);
    await vi.advanceTimersByTimeAsync(0);
    expect(net.opened).toHaveLength(2);
    expect(net.opened[1].headers.get("Last-Event-ID")).toBe("5");
    expect(client.currentStatus).toBe("connected");
    client.stop();
    expect(net.opened[1].signal?.aborted).toBe(true);
  });

  it("backs off with jitter after errors and short-lived streams", async () => {
    const net = streamingFetch([500, 500, 200]);
    const { client, statuses } = makeClient(
      net.fetchImpl as unknown as typeof fetch,
    );
    client.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(net.opened).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(499);
    expect(net.opened).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(net.opened).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(999);
    expect(net.opened).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(net.opened).toHaveLength(3);
    expect(statuses.at(-1)).toBe("connected");
    // Closed immediately: counted as a failure (attempt 2 -> up to 2 s).
    net.end(2);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(net.opened).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(net.opened).toHaveLength(4);
    client.stop();
  });

  it("refreshes the token once on 401, then backs off", async () => {
    const net = streamingFetch([401, 401, 401]);
    const { client } = makeClient(net.fetchImpl as unknown as typeof fetch);
    client.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(refreshAccessToken).toHaveBeenCalledWith({ trigger: "401" });
    expect(net.opened).toHaveLength(2);
    // The second 401 does not refresh again; it waits.
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(500);
    expect(net.opened).toHaveLength(3);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    client.stop();
  });

  it("backs off when the refresh itself fails", async () => {
    vi.mocked(refreshAccessToken).mockRejectedValueOnce(new Error("down"));
    const net = streamingFetch([401, 200]);
    const { client } = makeClient(net.fetchImpl as unknown as typeof fetch);
    client.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(net.opened).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(500);
    expect(net.opened).toHaveLength(2);
    client.stop();
  });

  it.each([404, 503])(
    "marks %s as unavailable and retries after five minutes",
    async (status) => {
      const net = streamingFetch([status, 200]);
      const { client, statuses } = makeClient(
        net.fetchImpl as unknown as typeof fetch,
      );
      client.start();
      await vi.advanceTimersByTimeAsync(0);
      expect(statuses).toEqual(["unavailable"]);
      await vi.advanceTimersByTimeAsync(UNAVAILABLE_RETRY_MS - 1);
      expect(net.opened).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(net.opened).toHaveLength(2);
      expect(statuses.at(-1)).toBe("connected");
      client.stop();
    },
  );

  it("backs off on 429 and on network errors", async () => {
    const net = streamingFetch([429]);
    const failing = vi.fn(async () => {
      throw new TypeError("network");
    });
    const first = makeClient(net.fetchImpl as unknown as typeof fetch);
    first.client.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(first.statuses).toEqual([]);
    expect(first.client.currentStatus).toBe("connecting");
    await vi.advanceTimersByTimeAsync(500);
    expect(net.opened).toHaveLength(2);
    first.client.stop();

    const second = makeClient(failing as unknown as typeof fetch);
    second.client.start();
    await vi.advanceTimersByTimeAsync(500);
    expect(failing).toHaveBeenCalledTimes(2);
    second.client.stop();
  });

  it("waits without a token instead of sending an anonymous request", async () => {
    mockContext.token = null;
    const net = streamingFetch([200]);
    const { client } = makeClient(net.fetchImpl as unknown as typeof fetch);
    client.start();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(net.opened).toHaveLength(0);
    mockContext.token = "token-1";
    await vi.advanceTimersByTimeAsync(4_000);
    expect(net.opened).toHaveLength(1);
    client.stop();
  });

  it("closes after a minute hidden and resyncs once when visible again", async () => {
    const net = streamingFetch([200, 200]);
    const { client, onResync } = makeClient(
      net.fetchImpl as unknown as typeof fetch,
    );
    client.start();
    client.start(); // idempotent
    await vi.advanceTimersByTimeAsync(0);
    client.setVisible(false);
    await vi.advanceTimersByTimeAsync(HIDDEN_CLOSE_MS - 1);
    expect(net.opened[0].signal?.aborted).toBe(false);
    client.setVisible(true); // back before the minute: nothing happens
    client.setVisible(false);
    await vi.advanceTimersByTimeAsync(HIDDEN_CLOSE_MS);
    expect(net.opened[0].signal?.aborted).toBe(true);
    expect(client.currentStatus).toBe("connecting");
    await vi.advanceTimersByTimeAsync(120_000);
    expect(net.opened).toHaveLength(1);
    client.setVisible(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(onResync).toHaveBeenCalledTimes(1);
    expect(net.opened).toHaveLength(2);
    client.stop();
    client.setVisible(false); // ignored once stopped
  });
});
