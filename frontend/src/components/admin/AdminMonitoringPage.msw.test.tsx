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

import { AdminMonitoringPage } from "@/components/admin/AdminMonitoringPage";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

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

const server = setupServer(
  http.get(`${apiBaseUrl}/documents`, () =>
    HttpResponse.json({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
      status: "failed",
      sort_by: "updated_at",
      sort_order: "desc",
    }),
  ),
  http.get(`${apiBaseUrl}/admin/audit-logs`, () =>
    HttpResponse.json({
      items: [],
      total: 0,
      limit: 60,
      offset: 0,
      range: { from: "2026-04-21", to: "2026-05-20" },
    }),
  ),
  http.get(`${apiBaseUrl}/admin/usage`, () =>
    HttpResponse.json({
      organization_id: "org-1",
      range: { from: "2026-04-21", to: "2026-05-20" },
      granularity: "day",
      totals: {
        input_tokens: 0,
        output_tokens: 0,
        cost_usd: 0,
        event_count: 0,
        avg_confidence: null,
        avg_latency_ms: null,
      },
      series: [],
    }),
  ),
  http.get(`${apiBaseUrl}/notifications`, () =>
    HttpResponse.json(
      {
        code: "not_found",
        message: "Not found",
      },
      { status: 404 },
    ),
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
      <AdminMonitoringPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL = "";
  process.env.NEXT_PUBLIC_SENTRY_URL = "";
  process.env.NEXT_PUBLIC_LOGS_URL = "";
  process.env.NEXT_PUBLIC_METRICS_URL = "";
  process.env.NEXT_PUBLIC_TRACING_URL = "";
  process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = "";
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
});

describe("AdminMonitoringPage MSW", () => {
  it("shows feature-flagged feed state when notifications endpoint is not configured", async () => {
    process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = "";
    renderPage();

    expect(await screen.findByText("Monitoring overview")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Aggregation feed is not configured for this deployment.",
      ),
    ).toBeInTheDocument();
  });

  it("shows endpoint-unavailable state when notifications feed returns 404", async () => {
    process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = "/notifications";
    renderPage();

    expect(await screen.findByText("Monitoring overview")).toBeInTheDocument();
    expect(
      await screen.findByText("Monitoring feed endpoint is unavailable."),
    ).toBeInTheDocument();
  });
});
