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
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminUsagePage } from "@/components/admin/AdminUsagePage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

let observedFrom: string | null = null;
let observedTo: string | null = null;
let observedGranularity: string | null = null;

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const server = setupServer(
  http.get(`${apiBaseUrl}/admin/usage`, ({ request }) => {
    const url = new URL(request.url);
    observedFrom = url.searchParams.get("from");
    observedTo = url.searchParams.get("to");
    observedGranularity = url.searchParams.get("granularity");

    return HttpResponse.json({
      organization_id: "org-1",
      range: { from: "2026-05-01", to: "2026-05-30" },
      granularity: "day",
      totals: {
        input_tokens: 1200,
        output_tokens: 300,
        cost_usd: 2.45,
        event_count: 7,
        avg_confidence: 0.77,
        avg_latency_ms: 280,
      },
      series: [],
    });
  }),
  http.get(`${apiBaseUrl}/documents`, () =>
    HttpResponse.json({
      items: [],
      total: 11,
      limit: 1,
      offset: 0,
      status: null,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
  ),
);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminUsagePage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  observedFrom = null;
  observedTo = null;
  observedGranularity = null;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "u-1",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("AdminUsagePage MSW", () => {
  it("loads usage summary and document totals", async () => {
    renderPage();

    expect(await screen.findByText("Usage analytics")).toBeInTheDocument();
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(await screen.findByText("11")).toBeInTheDocument();
    expect(await screen.findByText("1,500")).toBeInTheDocument();
    expect(await screen.findByText("$2.45")).toBeInTheDocument();
    expect(
      await screen.findByText("No usage events were recorded in this range."),
    ).toBeInTheDocument();
    expect(observedFrom).not.toBeNull();
    expect(observedTo).not.toBeNull();
    expect(observedGranularity).toBe("day");
  });
});
