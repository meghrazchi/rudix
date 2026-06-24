import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminUsagePage } from "@/components/admin/AdminUsagePage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getUsageDashboard: vi.fn(),
  exportUsageDashboard: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/admin-usage", () => ({
  getUsageDashboard: (query?: unknown) => mockApi.getUsageDashboard(query),
  exportUsageDashboard: (format: unknown, query?: unknown) =>
    mockApi.exportUsageDashboard(format, query),
}));

const ADMIN_SESSION: SessionState = {
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

const MEMBER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "u-2",
    email: "member@example.com",
    role: "member",
    organizationId: "org-1",
    organizationName: "Org One",
    accessToken: "token-2",
  },
};

const FULL_DASHBOARD = {
  organization_id: "org-1",
  range: { from: "2026-05-01", to: "2026-05-30" },
  granularity: "day",
  is_cost_estimate: true,
  totals: {
    questions_asked: 42,
    input_tokens: 1500,
    output_tokens: 300,
    estimated_cost_usd: 4.5,
    active_users: 7,
    documents: 120,
    indexed_documents: 110,
    total_chunks: 880,
    indexing_jobs: 15,
    failed_indexing_jobs: 2,
    evaluation_runs: 8,
    agent_runs: 5,
    api_calls: 30,
    avg_confidence: 0.81,
    avg_latency_ms: 321,
    latency_score: 73.25,
  },
  series: [
    {
      period_start: "2026-05-14",
      period_end: "2026-05-14",
      questions_asked: 10,
      input_tokens: 100,
      output_tokens: 20,
      estimated_cost_usd: 0.3,
      active_users: 3,
      agent_runs: 1,
      evaluation_runs: 2,
      avg_confidence: 0.9,
      avg_latency_ms: 250,
    },
  ],
  top_users: [
    {
      user_id: "00000000-0000-0000-0000-000000000001",
      questions: 20,
      input_tokens: 800,
      output_tokens: 150,
      estimated_cost_usd: 2.1,
    },
  ],
  top_models: [
    {
      model_name: "gpt-4o",
      event_count: 30,
      input_tokens: 1200,
      output_tokens: 250,
      estimated_cost_usd: 3.5,
    },
  ],
  feature_area_breakdown: { chat: 35, agent: 5, evaluation: 2 },
};

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

describe("AdminUsagePage", () => {
  beforeEach(() => {
    mockApi.getUsageDashboard.mockReset();
    mockApi.exportUsageDashboard.mockReset();
    mockApi.getUsageDashboard.mockResolvedValue(FULL_DASHBOARD);
  });

  it("shows forbidden state for non-admin users", async () => {
    mockState.authState = MEMBER_SESSION;
    renderPage();
    expect(
      await screen.findByText("Admin usage restricted"),
    ).toBeInTheDocument();
    expect(mockApi.getUsageDashboard).not.toHaveBeenCalled();
  });

  it("renders page heading and estimate disclaimer for admin", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(
      await screen.findByText("Usage & cost dashboard"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Cost figures are/).length).toBeGreaterThan(0);
  });

  it("renders summary metric cards with correct values", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("1,800")).toBeInTheDocument();
    expect(screen.getByText("$4.50")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("321 ms")).toBeInTheDocument();
    expect(screen.getByText("81.0%")).toBeInTheDocument();
  });

  it("marks estimated cost cards with 'estimate' badge", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    await screen.findByText("Usage & cost dashboard");
    const badges = screen.getAllByText("estimate");
    expect(badges.length).toBeGreaterThanOrEqual(1);
  });

  it("renders trend series table with period and metrics", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(await screen.findByText("2026-05-14")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("$0.30")).toBeInTheDocument();
  });

  it("renders feature area breakdown chips", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(await screen.findByText(/chat: 35/)).toBeInTheDocument();
    expect(screen.getByText(/agent: 5/)).toBeInTheDocument();
  });

  it("renders top users table with user_id and cost", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(
      await screen.findByText("00000000-0000-0000-0000-000000000001"),
    ).toBeInTheDocument();
    expect(screen.getByText("$2.10")).toBeInTheDocument();
  });

  it("renders top models table with model name and cost", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(await screen.findByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("$3.50")).toBeInTheDocument();
  });

  it("filters are applied when form is submitted", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    await screen.findByText("Usage & cost dashboard");

    const modelInput = screen.getByPlaceholderText("e.g. gpt-4o");
    fireEvent.change(modelInput, { target: { value: "claude-3-sonnet" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      const calls = mockApi.getUsageDashboard.mock.calls;
      const lastCall = calls[calls.length - 1][0] as Record<string, unknown>;
      expect(lastCall?.model).toBe("claude-3-sonnet");
    });
  });

  it("reset clears all filter inputs", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    await screen.findByText("Usage & cost dashboard");

    const modelInput = screen.getByPlaceholderText("e.g. gpt-4o");
    fireEvent.change(modelInput, { target: { value: "gpt-4o" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect((modelInput as HTMLInputElement).value).toBe("");
  });

  it("shows empty state in trends table when series is empty", async () => {
    mockState.authState = ADMIN_SESSION;
    mockApi.getUsageDashboard.mockResolvedValue({
      ...FULL_DASHBOARD,
      series: [],
    });
    renderPage();
    expect(
      await screen.findByText("No usage events were recorded in this range."),
    ).toBeInTheDocument();
  });

  it("shows error state when dashboard query fails", async () => {
    mockState.authState = ADMIN_SESSION;
    mockApi.getUsageDashboard.mockRejectedValue(new Error("Server error"));
    renderPage();
    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });
  });

  it("renders Export CSV and Export JSON buttons", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    expect(
      await screen.findByRole("button", { name: "Export CSV" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export JSON" }),
    ).toBeInTheDocument();
  });
});
