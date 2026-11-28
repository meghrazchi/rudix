import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type { ChatTurn } from "@/components/chat/chat-types";
import { useAgentRunTimeline } from "@/components/chat/hooks/useAgentRunTimeline";

vi.mock("@/lib/api/request", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/request")>()),
  getSessionRequestContext: () => ({
    token: "token-1",
    organizationId: "11111111-1111-4111-8111-111111111111",
    userId: "u-1",
  }),
}));

const apiBaseUrl = "http://api.test";
const encoder = new TextEncoder();
const detailRequests: string[] = [];
const streamRequests: Request[] = [];
let runStatus = "running";
let streamStatus = 200;
let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;

const server = setupServer(
  http.get(`${apiBaseUrl}/agent/runs/:runId/stream`, ({ request }) => {
    streamRequests.push(request);
    if (streamStatus !== 200) {
      return HttpResponse.json({}, { status: streamStatus });
    }
    return new HttpResponse(
      new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
        },
      }),
      { headers: { "Content-Type": "text/event-stream" } },
    );
  }),
  http.get(`${apiBaseUrl}/agent/runs/:runId`, ({ params }) => {
    detailRequests.push(String(params.runId));
    return HttpResponse.json({ run_id: params.runId, status: runStatus });
  }),
);

function push(id: number, event: string) {
  streamController?.enqueue(
    encoder.encode(`id: ${id}\nevent: ${event}\ndata: {"id":${id}}\n\n`),
  );
}

const turn = { response: { agent_run_id: "run-1" } } as unknown as ChatTurn;

function renderTimeline() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAgentRunTimeline({ selectedCitationTurn: turn }), {
    wrapper,
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
    ],
  });
  vi.stubEnv("NEXT_PUBLIC_API_URL", apiBaseUrl);
  vi.stubEnv("NEXT_PUBLIC_REALTIME_ENABLED", "true");
  runStatus = "running";
  streamStatus = 200;
  streamController = null;
});

afterEach(() => {
  server.resetHandlers();
  detailRequests.length = 0;
  streamRequests.length = 0;
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("useAgentRunTimeline over SSE", () => {
  it("follows the run stream instead of polling and closes on a terminal event", async () => {
    const view = renderTimeline();
    await advance(50);
    await advance(50);
    expect(detailRequests).toHaveLength(1);
    expect(streamRequests).toHaveLength(1);
    expect(new URL(streamRequests[0].url).pathname).toBe(
      "/agent/runs/run-1/stream",
    );
    expect(streamRequests[0].headers.get("authorization")).toBe(
      "Bearer token-1",
    );

    await advance(10_000);
    expect(detailRequests).toHaveLength(1); // no polling while streaming

    push(1, "agent.step.started");
    push(2, "agent.step.completed");
    await advance(300);
    expect(detailRequests).toHaveLength(2); // one merged refetch

    runStatus = "completed";
    push(3, "agent.run.completed");
    await advance(300);
    expect(detailRequests).toHaveLength(3);
    expect(view.result.current.selectedAgentRunQuery.data?.status).toBe(
      "completed",
    );
    expect(streamRequests[0].signal.aborted).toBe(true);
    await advance(10_000);
    expect(detailRequests).toHaveLength(3);
    expect(streamRequests).toHaveLength(1);
    view.unmount();
  });

  it("falls back to polling when the stream is unavailable", async () => {
    streamStatus = 503;
    const view = renderTimeline();
    await advance(100);
    expect(streamRequests).toHaveLength(1);
    await advance(6_100);
    expect(detailRequests.length).toBeGreaterThanOrEqual(3);
    view.unmount();
  });

  it("falls back to polling when the stream ends early", async () => {
    const view = renderTimeline();
    await advance(100);
    streamController?.close();
    await advance(100);
    await advance(3_100);
    expect(detailRequests.length).toBeGreaterThanOrEqual(2);
    view.unmount();
  });

  it("keeps polling without opening a stream while realtime is off", async () => {
    vi.stubEnv("NEXT_PUBLIC_REALTIME_ENABLED", "false");
    const view = renderTimeline();
    await advance(6_100);
    expect(streamRequests).toHaveLength(0);
    expect(detailRequests.length).toBeGreaterThanOrEqual(3);
    view.unmount();
  });
});
