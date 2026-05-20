import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminUsagePage } from "@/components/admin/AdminUsagePage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getUsageSummary: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/admin-usage", () => ({
  getUsageSummary: (query?: unknown) => mockApi.getUsageSummary(query),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (options?: unknown) => mockApi.listDocuments(options),
}));

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
    mockApi.getUsageSummary.mockReset();
    mockApi.listDocuments.mockReset();

    mockApi.getUsageSummary.mockResolvedValue({
      organization_id: "org-1",
      range: { from: "2026-05-01", to: "2026-05-30" },
      granularity: "day",
      totals: {
        input_tokens: 1500,
        output_tokens: 300,
        cost_usd: 4.5,
        event_count: 8,
        avg_confidence: 0.81,
        avg_latency_ms: 321,
      },
      series: [
        {
          period_start: "2026-05-14",
          period_end: "2026-05-14",
          input_tokens: 100,
          output_tokens: 20,
          cost_usd: 0.3,
          event_count: 1,
          avg_confidence: 0.9,
          avg_latency_ms: 250,
        },
      ],
    });

    mockApi.listDocuments.mockResolvedValue({
      items: [],
      total: 42,
      limit: 1,
      offset: 0,
      status: null,
      sort_by: "updated_at",
      sort_order: "desc",
    });
  });

  it("renders formatted summary metrics for admin users", async () => {
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

    renderPage();

    expect(await screen.findByText("Usage analytics")).toBeInTheDocument();
    expect(await screen.findByText("8")).toBeInTheDocument();
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(await screen.findByText("1,800")).toBeInTheDocument();
    expect(await screen.findByText("$4.50")).toBeInTheDocument();
    expect(await screen.findByText("321 ms")).toBeInTheDocument();
    expect(await screen.findByText("81.0%")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export CSV (planned)" }),
    ).toBeDisabled();
  });

  it("shows forbidden state for non-admin users", async () => {
    mockState.authState = {
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

    renderPage();
    expect(
      await screen.findByText("Admin usage restricted"),
    ).toBeInTheDocument();
    expect(mockApi.getUsageSummary).not.toHaveBeenCalled();
    expect(mockApi.listDocuments).not.toHaveBeenCalled();
  });
});
