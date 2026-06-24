import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/DashboardPage";
import type { UsageSummaryResponse } from "@/lib/api/admin-usage";
import type { BillingCapabilities, BillingPlanInfo } from "@/lib/api/billing";
import type { ListDocumentsOptions } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  listChatSessions: vi.fn(),
  getChatStats: vi.fn(),
  getUsageSummary: vi.fn(),
  listAuditLogs: vi.fn(),
  getBillingCapabilities: vi.fn(),
  getBillingPlanInfo: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (options?: ListDocumentsOptions) =>
    mockApi.listDocuments(options),
}));

vi.mock("@/lib/api/chat", () => ({
  listChatSessions: (options?: { limit?: number; offset?: number }) =>
    mockApi.listChatSessions(options),
  getChatStats: () => mockApi.getChatStats(),
}));

vi.mock("@/lib/api/admin-usage", () => ({
  getUsageSummary: (options?: {
    from?: string;
    to?: string;
    granularity?: "day" | "week" | "month";
  }) => mockApi.getUsageSummary(options),
  listAuditLogs: (options?: {
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  }) => mockApi.listAuditLogs(options),
}));

vi.mock("@/lib/api/billing", () => ({
  getBillingCapabilities: () => mockApi.getBillingCapabilities(),
  getBillingPlanInfo: (...args: unknown[]) =>
    mockApi.getBillingPlanInfo(...args),
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
      <DashboardPage />
    </QueryClientProvider>,
  );
}

function expectKpiValue(title: string, value: string) {
  const cardTitle = screen.getByText(title);
  const card = cardTitle.closest("article");
  if (!card) {
    throw new Error(`KPI card for "${title}" was not found`);
  }
  expect(within(card).getByText(value)).toBeInTheDocument();
}

describe("DashboardPage", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE: "true",
    };

    mockApi.listDocuments.mockReset();
    mockApi.listChatSessions.mockReset();
    mockApi.getChatStats.mockReset();
    mockApi.getUsageSummary.mockReset();
    mockApi.listAuditLogs.mockReset();
    mockApi.getBillingCapabilities.mockReset();
    mockApi.getBillingPlanInfo.mockReset();

    mockApi.listDocuments.mockImplementation(
      (options?: ListDocumentsOptions) => {
        if (options?.status === "indexed") {
          return Promise.resolve({
            items: [],
            total: 1,
            limit: 1,
            offset: 0,
            status: "indexed",
            sort_by: "created_at",
            sort_order: "desc",
          });
        }
        return Promise.resolve({
          items: [
            {
              document_id: "doc-1",
              filename: "a.pdf",
              file_type: "pdf",
              status: "indexed",
              page_count: 4,
              chunk_count: 12,
              error_message: null,
              error_details: null,
              created_at: "2026-05-14T00:00:00Z",
              updated_at: "2026-05-14T00:00:00Z",
            },
            {
              document_id: "doc-2",
              filename: "b.pdf",
              file_type: "pdf",
              status: "processing",
              page_count: 2,
              chunk_count: 8,
              error_message: null,
              error_details: null,
              created_at: "2026-05-14T00:00:00Z",
              updated_at: "2026-05-14T00:00:00Z",
            },
          ],
          total: 2,
          limit: options?.limit ?? 200,
          offset: options?.offset ?? 0,
          status: options?.status ?? null,
          sort_by: options?.sort_by ?? "updated_at",
          sort_order: options?.sort_order ?? "desc",
        });
      },
    );

    mockApi.listChatSessions.mockResolvedValue({
      items: [
        {
          session_id: "s-1",
          title: "A",
          message_count: 4,
          created_at: "2026-05-14T00:00:00Z",
          updated_at: "2026-05-14T00:00:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    });

    mockApi.getChatStats.mockResolvedValue({
      questions_asked: 8,
      total_sessions: 1,
    });

    const usage: UsageSummaryResponse = {
      organization_id: "org-1",
      range: { from: "2026-05-01", to: "2026-05-14" },
      totals: {
        input_tokens: 1500,
        output_tokens: 300,
        cost_usd: 4.5,
        event_count: 8,
        questions_asked: 6,
        avg_confidence: 0.81,
        avg_latency_ms: 321,
      } as UsageSummaryResponse["totals"],
      series: [],
    };
    mockApi.getUsageSummary.mockResolvedValue(usage);
    mockApi.listAuditLogs.mockResolvedValue({
      items: [
        {
          audit_log_id: "audit-1",
          organization_id: "org-1",
          user_id: "u-1",
          action: "evaluation.run.completed",
          resource_type: "evaluation_run",
          resource_id: "run-1",
          request_id: "req-1",
          metadata: {},
          created_at: "2026-05-14T00:00:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
      range: { from: "2026-05-01", to: "2026-05-14" },
    });

    mockApi.getBillingCapabilities.mockReturnValue({
      planEnabled: true,
      usageEnabled: false,
      quotasEnabled: false,
      invoicesEnabled: false,
      billingContactEnabled: false,
      updateBillingContactEnabled: false,
      portalSessionEnabled: false,
    } satisfies BillingCapabilities);

    mockApi.getBillingPlanInfo.mockResolvedValue({
      plan_name: "Enterprise Pro",
      status: "past_due",
      billing_cycle: "monthly",
      renewal_date: "2026-06-01T00:00:00Z",
      trial_end_date: null,
      seats_used: 24,
      seats_included: 50,
      storage_used_gb: 842,
      storage_included_gb: 2048,
      monthly_questions_used: 458291,
      monthly_questions_included: 1000000,
      token_allowance_used: 1200000000,
      token_allowance_included: 2500000000,
      evaluation_allowance_used: null,
      evaluation_allowance_included: null,
      agent_allowance_used: null,
      agent_allowance_included: null,
      connector_allowance_used: null,
      connector_allowance_included: null,
      can_manage_subscription: true,
      can_cancel_plan: true,
    } satisfies BillingPlanInfo);
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it("renders formatted KPI values for admin role", async () => {
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

    await screen.findByText("Indexing success");
    await waitFor(() => expectKpiValue("Total chunks", "20"));
    await waitFor(() => expectKpiValue("Questions asked", "8"));
    await waitFor(() => {
      expect(screen.getByText("81.0%")).toBeInTheDocument();
      expect(screen.getByText("321 ms")).toBeInTheDocument();
      expect(screen.getByText("$4.50")).toBeInTheDocument();
    });
    await screen.findByText("Recent activity");
  });

  it("shows the billing warning banner for billing admins when a plan is past due", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "billing@example.com",
        role: "billing_admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };

    renderPage();

    expect(
      await screen.findByText("Payment attention required"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open billing" })).toHaveAttribute(
      "href",
      "/settings?tab=billing",
    );
  });

  it("renders latest documents and recent activity links with quick actions", async () => {
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

    await screen.findByText("Latest documents");
    expect(
      screen.getByRole("link", { name: "Upload document" }),
    ).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute(
      "href",
      "/chat",
    );
    expect(
      screen.getByRole("link", { name: "Evaluation run" }),
    ).toHaveAttribute("href", "/evaluations");
    expect(
      screen.getByRole("link", { name: "Pipeline explorer" }),
    ).toHaveAttribute("href", "/rag-pipeline");

    const latestDocumentsSection = screen
      .getByText("Latest documents")
      .closest("article");
    if (!latestDocumentsSection) {
      throw new Error("Latest documents section is missing");
    }
    await waitFor(() => {
      expect(
        within(latestDocumentsSection).getByText("a.pdf"),
      ).toBeInTheDocument();
      expect(
        within(latestDocumentsSection).getByText("b.pdf"),
      ).toBeInTheDocument();
    });
    expect(within(latestDocumentsSection).getByText("indexed")).toHaveClass(
      "bg-emerald-100",
    );
    expect(within(latestDocumentsSection).getByText("processing")).toHaveClass(
      "bg-blue-100",
    );

    const detailLinks = within(latestDocumentsSection).getAllByRole("link", {
      name: "View document",
    });
    expect(detailLinks[0]).toHaveAttribute(
      "href",
      "/documents?document_id=doc-1",
    );

    const recentActivitySection = screen
      .getByText("Recent activity")
      .closest("article");
    if (!recentActivitySection) {
      throw new Error("Recent activity section is missing");
    }
    expect(
      within(recentActivitySection).getByText("Chat questions"),
    ).toBeInTheDocument();
    const activityLinks = within(recentActivitySection).getAllByRole("link", {
      name: "Open",
    });
    const activityHrefs = activityLinks.map((link) =>
      link.getAttribute("href"),
    );
    expect(activityHrefs).toContain("/chat?session_id=s-1");
  });

  it("paginates latest documents and keeps view action on one line", async () => {
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

    const allDocuments = Array.from({ length: 6 }, (_, index) => ({
      document_id: `doc-${index + 1}`,
      filename: `file-${index + 1}.pdf`,
      file_type: "pdf",
      status: "indexed" as const,
      page_count: 1,
      chunk_count: 1,
      error_message: null,
      error_details: null,
      created_at: "2026-05-14T00:00:00Z",
      updated_at: "2026-05-14T00:00:00Z",
    }));

    mockApi.listDocuments.mockImplementation(
      (options?: ListDocumentsOptions) => {
        if (options?.status === "indexed") {
          return Promise.resolve({
            items: [],
            total: allDocuments.length,
            limit: 1,
            offset: 0,
            status: "indexed",
            sort_by: "created_at",
            sort_order: "desc",
          });
        }

        const limit = options?.limit ?? 5;
        const offset = options?.offset ?? 0;
        const items = allDocuments.slice(offset, offset + limit);

        return Promise.resolve({
          items,
          total: allDocuments.length,
          limit,
          offset,
          status: options?.status ?? null,
          sort_by: options?.sort_by ?? "updated_at",
          sort_order: options?.sort_order ?? "desc",
        });
      },
    );

    renderPage();

    const latestDocumentsSection = screen
      .getByText("Latest documents")
      .closest("article");
    if (!latestDocumentsSection) {
      throw new Error("Latest documents section is missing");
    }

    await waitFor(() => {
      expect(
        within(latestDocumentsSection).getByText("file-1.pdf"),
      ).toBeInTheDocument();
    });

    const viewButton = within(latestDocumentsSection).getAllByRole("link", {
      name: "View document",
    })[0];
    expect(viewButton).toHaveClass("whitespace-nowrap");
    expect(
      within(latestDocumentsSection).getByRole("button", { name: "Next" }),
    ).toBeEnabled();

    await userEvent.click(
      within(latestDocumentsSection).getByRole("button", { name: "Next" }),
    );

    await waitFor(() => {
      expect(
        within(latestDocumentsSection).getByText("file-6.pdf"),
      ).toBeInTheDocument();
    });
    expect(
      within(latestDocumentsSection).getByText("Showing 6-6 of 6 documents."),
    ).toBeInTheDocument();
  });

  it("hides admin-only estimated cost field for non-admin roles", async () => {
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

    await waitFor(() => {
      expect(screen.getAllByText("Indexing success").length).toBeGreaterThan(0);
    });

    expect(screen.queryByText("Estimated cost")).not.toBeInTheDocument();
    expect(mockApi.getUsageSummary).not.toHaveBeenCalled();
  });
});
