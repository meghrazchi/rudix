import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/components/admin/AdminPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getUsageSummary: vi.fn(),
  listAuditLogs: vi.fn(),
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
  listAuditLogs: (query?: unknown) => mockApi.listAuditLogs(query),
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
      <AdminPage />
    </QueryClientProvider>,
  );
}

describe("AdminPage", () => {
  beforeEach(() => {
    mockApi.getUsageSummary.mockReset();
    mockApi.listAuditLogs.mockReset();

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

    mockApi.listAuditLogs.mockResolvedValue({
      items: [
        {
          audit_log_id: "audit-1",
          organization_id: "org-1",
          user_id: "user-1",
          action: "chat.query.completed",
          resource_type: "chat_session",
          resource_id: "session-1",
          request_id: "req-1",
          metadata: { status_code: 200 },
          created_at: "2026-05-14T12:00:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
      range: { from: "2026-05-01", to: "2026-05-30" },
    });
  });

  it("renders usage and audit data for admin role", async () => {
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

    await screen.findByText("Usage and audit analytics");
    await waitFor(() => {
      expect(screen.getByText("8")).toBeInTheDocument();
      expect(screen.getByText("$4.50")).toBeInTheDocument();
      expect(screen.getByText("chat.query.completed")).toBeInTheDocument();
      expect(screen.getByText("Trace ID:")).toBeInTheDocument();
    });

    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: "Chats" })).toHaveAttribute("href", "/chat");
    expect(screen.getByRole("link", { name: "Evaluations" })).toHaveAttribute("href", "/evaluations");
    expect(screen.getByRole("link", { name: "Pipeline Explorer" })).toHaveAttribute("href", "/rag-pipeline");
  });

  it("renders forbidden state for non-admin role", async () => {
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
    expect(await screen.findByText("Admin usage restricted")).toBeInTheDocument();
    expect(mockApi.getUsageSummary).not.toHaveBeenCalled();
    expect(mockApi.listAuditLogs).not.toHaveBeenCalled();
  });

  it("shows empty state when audit feed has no rows", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-3",
        email: "owner@example.com",
        role: "owner",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-3",
      },
    };

    mockApi.listAuditLogs.mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
      range: { from: "2026-05-01", to: "2026-05-30" },
    });

    renderPage();
    expect(await screen.findByText("Recent audit activity")).toBeInTheDocument();
    expect(await screen.findByText("No audit events were found for the selected range and filters.")).toBeInTheDocument();
  });
});
