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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { DocumentsPage } from "@/components/documents/DocumentsPage";
import type { SessionState } from "@/lib/auth-session";
import { RealtimeProvider, useRealtime } from "@/lib/realtime/RealtimeProvider";
import {
  createPagedListHandlers,
  makePagedDocuments,
} from "@/test/msw/handlers";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/request", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/request")>()),
  getSessionRequestContext: () => ({
    token: "token-1",
    organizationId: "11111111-1111-4111-8111-111111111111",
    userId: "u-1",
  }),
}));

const apiBaseUrl = "http://api.test";
const requests: URL[] = [];
const streamRequests: Request[] = [];
const encoder = new TextEncoder();
let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
let streamStatus = 200;

const documents = makePagedDocuments(30).map((doc, index) =>
  index < 3 ? { ...doc, status: "processing" as const } : doc,
);

const server = setupServer(
  ...createPagedListHandlers({ apiBaseUrl, requests, documents }),
  http.get(`${apiBaseUrl}/events/stream`, ({ request }) => {
    streamRequests.push(request);
    if (streamStatus !== 200) {
      return HttpResponse.json(
        { error: { code: "realtime_unavailable" } },
        { status: streamStatus },
      );
    }
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });
    return new HttpResponse(body, {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),
);

function tableListRequests(): URL[] {
  return requests.filter(
    (url) =>
      url.pathname === "/documents" &&
      url.searchParams.get("limit") === "20" &&
      !url.searchParams.get("status"),
  );
}

function summaryRequests(): URL[] {
  return requests.filter(
    (url) =>
      url.pathname === "/documents" && url.searchParams.get("limit") === "1",
  );
}

function pushEvent(id: number, type: string, payload: Record<string, string>) {
  const data = JSON.stringify({
    type,
    organization_id: "11111111-1111-4111-8111-111111111111",
    occurred_at: "2026-11-28T00:00:00Z",
    payload,
  });
  streamController?.enqueue(
    encoder.encode(`id: ${id}\nevent: ${type}\ndata: ${data}\n\n`),
  );
}

function StatusProbe() {
  const { status } = useRealtime();
  return <span data-testid="realtime-status">{status}</span>;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RealtimeProvider>
        <StatusProbe />
        <DocumentsPage />
      </RealtimeProvider>
    </QueryClientProvider>,
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeAll(async () => {
  // Warm the on-demand modules so the provider's dynamic import resolves under fake timers.
  await import("@/lib/realtime/invalidation");
  await import("@/lib/realtime/stream-client");
  server.listen({ onUnhandledRequest: "error" });
});
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
  streamStatus = 200;
  streamController = null;
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "u-1",
      email: "admin@example.com",
      role: "admin",
      organizationId: "11111111-1111-4111-8111-111111111111",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

afterEach(() => {
  server.resetHandlers();
  requests.length = 0;
  streamRequests.length = 0;
  setVisibility("visible");
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("RealtimeProvider with the documents page (MSW)", () => {
  it("stops polling while connected and refetches within 2 s of an event", async () => {
    const view = renderPage();
    await advance(100);
    await advance(100);
    expect(view.getByTestId("realtime-status").textContent).toBe("connected");
    expect(streamRequests).toHaveLength(1);
    expect(streamRequests[0].headers.get("authorization")).toBe(
      "Bearer token-1",
    );
    expect(streamRequests[0].url).not.toContain("token");
    expect(view.getByText("paged-1.pdf")).toBeInTheDocument();
    const listBefore = tableListRequests().length;
    const summaryBefore = summaryRequests().length;
    expect(listBefore).toBeGreaterThan(0);

    await advance(30_000);
    expect(tableListRequests()).toHaveLength(listBefore);
    expect(summaryRequests()).toHaveLength(summaryBefore);

    pushEvent(1, "document.status", {
      document_id: "paged-doc-1",
      status: "indexed",
    });
    pushEvent(2, "documents.changed", {});
    await advance(2_000);
    expect(tableListRequests()).toHaveLength(listBefore + 1);
    expect(summaryRequests().length).toBeGreaterThan(summaryBefore);
    view.unmount();
  });

  it("opens nothing when unmounted before the stream code loads", async () => {
    const view = renderPage();
    view.unmount();
    await advance(1_000);
    expect(streamRequests).toHaveLength(0);
  });

  it("polls at the fallback interval while the stream is unavailable", async () => {
    streamStatus = 503;
    const view = renderPage();
    await advance(200);
    expect(view.getByTestId("realtime-status").textContent).toBe("unavailable");
    const listBefore = tableListRequests().length;
    await advance(14_000);
    expect(tableListRequests()).toHaveLength(listBefore);
    await advance(16_000);
    expect(tableListRequests().length - listBefore).toBeGreaterThanOrEqual(1);
    expect(tableListRequests().length - listBefore).toBeLessThanOrEqual(2);
    view.unmount();
  });

  it("keeps today's 4 s polling with realtime off, and never polls a hidden tab", async () => {
    vi.stubEnv("NEXT_PUBLIC_REALTIME_ENABLED", "false");
    const view = renderPage();
    await advance(200);
    expect(view.getByTestId("realtime-status").textContent).toBe("disabled");
    expect(streamRequests).toHaveLength(0);
    const start = tableListRequests().length;
    await advance(12_500);
    expect(tableListRequests().length - start).toBeGreaterThanOrEqual(2);

    act(() => setVisibility("hidden"));
    const hiddenStart = tableListRequests().length;
    await advance(30_000);
    expect(tableListRequests()).toHaveLength(hiddenStart);
    view.unmount();
  });
});
