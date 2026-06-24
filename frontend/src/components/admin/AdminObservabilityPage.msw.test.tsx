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
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminObservabilityPage } from "@/components/admin/AdminObservabilityPage";
import type { SessionState } from "@/lib/auth-session";
import type { ObservabilitySnapshot } from "@/lib/api/observability";

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

function buildSnapshot(
  overrides?: Partial<ObservabilitySnapshot>,
): ObservabilitySnapshot {
  return {
    organization_id: "org-1",
    range: { from: "2026-05-06", to: "2026-06-05" },
    generated_at: "2026-06-05T10:00:00Z",
    api_metrics: {
      total_requests: 120,
      failed_requests: 6,
      error_rate: 0.05,
      avg_latency_ms: 320,
      p95_latency_ms: 870,
      telemetry_missing: false,
    },
    llm_metrics: {
      total_events: 80,
      failed_events: 4,
      error_rate: 0.05,
      avg_latency_ms: 1100,
      top_models: [
        { model_name: "gpt-4o", event_count: 60, error_count: 3 },
        { model_name: "gpt-3.5", event_count: 20, error_count: 1 },
      ],
      telemetry_missing: false,
    },
    indexing_metrics: {
      total_jobs: 50,
      succeeded_jobs: 48,
      failed_jobs: 2,
      in_progress_jobs: 0,
      success_rate: 0.96,
      telemetry_missing: false,
    },
    storage_metrics: {
      total_documents: 200,
      indexed_documents: 185,
      failed_documents: 10,
      pending_documents: 5,
      total_chunks: 3700,
    },
    ...overrides,
  };
}

let requestCount = 0;
let snapshotResponse: ObservabilitySnapshot = buildSnapshot();

const server = setupServer(
  http.get(`${apiBaseUrl}/admin/observability`, () => {
    requestCount += 1;
    return HttpResponse.json(snapshotResponse);
  }),
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
      <AdminObservabilityPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  requestCount = 0;
  snapshotResponse = buildSnapshot();
});
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "access-token",
    },
  };
});

describe("AdminObservabilityPage MSW", () => {
  it("renders page header and metric sections on load", async () => {
    renderPage();
    expect(
      await screen.findByRole("heading", { name: "Observability" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("API metrics")).toBeInTheDocument();
    expect(await screen.findByText("LLM metrics")).toBeInTheDocument();
    expect(await screen.findByText("Indexing pipeline")).toBeInTheDocument();
    expect(
      await screen.findByText("Storage and documents"),
    ).toBeInTheDocument();
  });

  it("renders api_metrics values from the snapshot", async () => {
    renderPage();
    expect(await screen.findByText("Total requests")).toBeInTheDocument();
    expect(await screen.findByText("120")).toBeInTheDocument();
    expect((await screen.findAllByText("5.0%")).length).toBeGreaterThan(0);
  });

  it("renders llm top_models list", async () => {
    renderPage();
    expect(await screen.findByText("gpt-4o")).toBeInTheDocument();
    expect(await screen.findByText("gpt-3.5")).toBeInTheDocument();
  });

  it("renders indexing success_rate", async () => {
    renderPage();
    expect(await screen.findByText("96.0%")).toBeInTheDocument();
  });

  it("renders storage total_documents", async () => {
    renderPage();
    expect(await screen.findByText("200")).toBeInTheDocument();
  });

  it("shows missing telemetry notice when api_metrics.telemetry_missing is true", async () => {
    snapshotResponse = buildSnapshot({
      api_metrics: { ...buildSnapshot().api_metrics, telemetry_missing: true },
    });
    renderPage();
    expect(
      await screen.findByText(
        /No API audit log telemetry in the selected time range/i,
      ),
    ).toBeInTheDocument();
  });

  it("shows missing telemetry notice when llm_metrics.telemetry_missing is true", async () => {
    snapshotResponse = buildSnapshot({
      llm_metrics: { ...buildSnapshot().llm_metrics, telemetry_missing: true },
    });
    renderPage();
    expect(
      await screen.findByText(
        /No LLM usage telemetry in the selected time range/i,
      ),
    ).toBeInTheDocument();
  });

  it("shows error state when the API returns 500", async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/observability`, () =>
        HttpResponse.json({ code: "internal_error" }, { status: 500 }),
      ),
    );
    renderPage();
    await waitFor(() => {
      expect(
        screen.queryByText("Loading observability snapshot..."),
      ).not.toBeInTheDocument();
    });
    expect(screen.queryByText("API metrics")).not.toBeInTheDocument();
  });

  it("shows forbidden state for non-admin users without fetching data", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "member-token",
      },
    };
    renderPage();
    expect(
      await screen.findByText("Admin observability restricted"),
    ).toBeInTheDocument();
    expect(requestCount).toBe(0);
  });

  it("re-fetches data on refresh button click", async () => {
    renderPage();
    expect(await screen.findByText("API metrics")).toBeInTheDocument();
    expect(requestCount).toBe(1);

    const refreshBtn = screen.getByRole("button", { name: "Refresh" });
    await userEvent.click(refreshBtn);

    await waitFor(() => {
      expect(requestCount).toBeGreaterThanOrEqual(2);
    });
  });

  it("shows snapshot timestamp from generated_at", async () => {
    renderPage();
    expect(
      await screen.findByText(/Snapshot generated at/),
    ).toBeInTheDocument();
  });

  it("renders related admin page links", async () => {
    renderPage();
    expect(await screen.findByText("System health")).toBeInTheDocument();
    expect(await screen.findByText("Audit logs")).toBeInTheDocument();
    expect(await screen.findByText("Usage analytics")).toBeInTheDocument();
  });

  it("renders failed document link when failed_documents > 0", async () => {
    renderPage();
    const links = await screen.findAllByText(/Review failed documents/i);
    expect(links.length).toBeGreaterThanOrEqual(1);
  });
});
