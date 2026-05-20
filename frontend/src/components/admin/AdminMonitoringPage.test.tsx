import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminMonitoringPage } from "@/components/admin/AdminMonitoringPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  listAuditLogs: vi.fn(),
  getUsageSummary: vi.fn(),
  getTopBarNotifications: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/documents")>(
    "@/lib/api/documents",
  );
  return {
    ...actual,
    listDocuments: (query?: unknown) => mockApi.listDocuments(query),
  };
});

vi.mock("@/lib/api/admin-usage", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/admin-usage")>(
    "@/lib/api/admin-usage",
  );
  return {
    ...actual,
    listAuditLogs: (query?: unknown) => mockApi.listAuditLogs(query),
    getUsageSummary: (query?: unknown) => mockApi.getUsageSummary(query),
  };
});

vi.mock("@/lib/api/notifications", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/notifications")
  >("@/lib/api/notifications");
  return {
    ...actual,
    getTopBarNotifications: (endpoint: string) =>
      mockApi.getTopBarNotifications(endpoint),
  };
});

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

describe("AdminMonitoringPage", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL = "/notifications";
    process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL =
      "https://monitoring.example.com/rudix";
    process.env.NEXT_PUBLIC_SENTRY_URL =
      "https://sentry.example.com/projects/rudix";

    mockApi.listDocuments.mockReset();
    mockApi.listAuditLogs.mockReset();
    mockApi.getUsageSummary.mockReset();
    mockApi.getTopBarNotifications.mockReset();

    mockApi.listDocuments.mockResolvedValue({
      items: [
        {
          document_id: "doc-1",
          filename: "Incident Report.pdf",
          file_type: "pdf",
          status: "failed",
          page_count: 12,
          chunk_count: 30,
          error_message: "Embedding provider timeout",
          error_details: null,
          created_at: "2026-05-20T09:00:00Z",
          updated_at: "2026-05-20T09:05:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      status: "failed",
      sort_by: "updated_at",
      sort_order: "desc",
    });

    mockApi.listAuditLogs.mockResolvedValue({
      items: [
        {
          audit_log_id: "audit-eval-fail",
          organization_id: "org-1",
          user_id: "user-1",
          action: "evaluations.run.failed",
          resource_type: "evaluation_run",
          resource_id: "run-123",
          request_id: "req-1",
          metadata: { status_code: 503 },
          created_at: "2026-05-20T08:10:00Z",
        },
        {
          audit_log_id: "audit-low-confidence",
          organization_id: "org-1",
          user_id: "user-2",
          action: "chat.query.completed",
          resource_type: "chat_session",
          resource_id: "session-1",
          request_id: "req-2",
          metadata: { confidence: 0.4 },
          created_at: "2026-05-20T08:15:00Z",
        },
        {
          audit_log_id: "audit-high-latency",
          organization_id: "org-1",
          user_id: "user-3",
          action: "chat.query.completed",
          resource_type: "chat_session",
          resource_id: "session-2",
          request_id: "req-3",
          metadata: { latency_ms: 3200 },
          created_at: "2026-05-20T08:17:00Z",
        },
      ],
      total: 3,
      limit: 60,
      offset: 0,
      range: { from: "2026-04-21", to: "2026-05-20" },
    });

    mockApi.getUsageSummary.mockResolvedValue({
      organization_id: "org-1",
      range: { from: "2026-04-21", to: "2026-05-20" },
      granularity: "day",
      totals: {
        input_tokens: 1000,
        output_tokens: 300,
        cost_usd: 3.55,
        event_count: 42,
        avg_confidence: 0.81,
        avg_latency_ms: 540,
      },
      series: [],
    });

    mockApi.getTopBarNotifications.mockResolvedValue({
      items: [
        {
          id: "notif-1",
          title: "Low confidence answers increased",
          message: "5 low-confidence answers in the last hour.",
          created_at: "2026-05-20T08:20:00Z",
          severity: "warning",
          kind: "low_confidence",
          href: "/chat",
        },
      ],
    });
  });

  it("renders forbidden state for non-admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-1",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    renderPage();

    expect(
      await screen.findByText("Admin monitoring restricted"),
    ).toBeInTheDocument();
    expect(mockApi.listDocuments).not.toHaveBeenCalled();
    expect(mockApi.listAuditLogs).not.toHaveBeenCalled();
    expect(mockApi.getUsageSummary).not.toHaveBeenCalled();
  });

  it("renders alert cards, severity badges, and observability links for admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "admin-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    renderPage();

    expect(await screen.findByText("Monitoring overview")).toBeInTheDocument();
    expect(await screen.findByText("Failed document jobs")).toBeInTheDocument();
    expect(
      await screen.findByText("Failed evaluation runs"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Low-confidence events"),
    ).toBeInTheDocument();
    expect(await screen.findByText("High-latency events")).toBeInTheDocument();
    expect((await screen.findAllByText("Critical")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("High")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Medium")).length).toBeGreaterThan(0);
    expect(
      await screen.findByRole("link", { name: "Monitoring dashboard" }),
    ).toHaveAttribute("href", "https://monitoring.example.com/rudix");
    expect(await screen.findByRole("link", { name: "Sentry" })).toHaveAttribute(
      "href",
      "https://sentry.example.com/projects/rudix",
    );
  });
});
