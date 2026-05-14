import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/DashboardPage";
import type { UsageSummaryResponse } from "@/lib/api/admin-usage";
import type { ListDocumentsOptions } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  listChatSessions: vi.fn(),
  getUsageSummary: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: (options?: ListDocumentsOptions) => mockApi.listDocuments(options),
}));

vi.mock("@/lib/api/chat", () => ({
  listChatSessions: (options?: { limit?: number; offset?: number }) => mockApi.listChatSessions(options),
}));

vi.mock("@/lib/api/admin-usage", () => ({
  getUsageSummary: (options?: { from?: string; to?: string; granularity?: "day" | "week" | "month" }) =>
    mockApi.getUsageSummary(options),
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
    process.env = { ...originalEnv, NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE: "true" };

    mockApi.listDocuments.mockReset();
    mockApi.listChatSessions.mockReset();
    mockApi.getUsageSummary.mockReset();

    mockApi.listDocuments.mockImplementation((options?: ListDocumentsOptions) => {
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
    });

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

    const usage: UsageSummaryResponse = {
      organization_id: "org-1",
      range: { from: "2026-05-01", to: "2026-05-14" },
      totals: {
        input_tokens: 1500,
        output_tokens: 300,
        cost_usd: 4.5,
        event_count: 8,
        avg_confidence: 0.81,
        avg_latency_ms: 321,
      } as UsageSummaryResponse["totals"],
      series: [],
    };
    mockApi.getUsageSummary.mockResolvedValue(usage);
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
    await waitFor(() => expectKpiValue("Average confidence", "81.0%"));
    await waitFor(() => expectKpiValue("Average latency", "321 ms"));
    await waitFor(() => expectKpiValue("Estimated cost", "$4.50"));
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
      expect(screen.getByText("Indexing success")).toBeInTheDocument();
    });

    expect(screen.queryByText("Estimated cost")).not.toBeInTheDocument();
    expect(mockApi.getUsageSummary).not.toHaveBeenCalled();
  });
});
