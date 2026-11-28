import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/DashboardPage";
import type { ListDocumentsOptions } from "@/lib/api/documents";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listDocuments: vi.fn(),
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
  listChatSessions: () =>
    Promise.resolve({ items: [], total: 0, limit: 20, offset: 0 }),
  getChatStats: () =>
    Promise.resolve({ questions_asked: 0, total_sessions: 0 }),
}));

vi.mock("@/lib/api/admin-usage", () => ({
  getUsageSummary: () => new Promise(() => {}),
  listAuditLogs: () => new Promise(() => {}),
}));

vi.mock("@/lib/api/billing", () => ({
  getBillingCapabilities: () => ({
    planEnabled: false,
    usageEnabled: false,
    quotasEnabled: false,
    invoicesEnabled: false,
    billingContactEnabled: false,
    updateBillingContactEnabled: false,
    portalSessionEnabled: false,
  }),
  getBillingPlanInfo: () => new Promise(() => {}),
}));

const TOTAL_DOCUMENTS = 5;

function documentRow(index: number) {
  return {
    document_id: `doc-${index}`,
    filename: `doc-${index}.pdf`,
    file_type: "pdf",
    status: "indexed",
    page_count: 1,
    chunk_count: 10,
    error_message: null,
    error_details: null,
    created_at: "2026-05-14T00:00:00Z",
    updated_at: "2026-05-14T00:00:00Z",
  };
}

describe("DashboardPage document summary cap (R07-06)", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_DASHBOARD_MAX_DOCUMENT_ROWS: "2",
    };
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
      },
    };
    mockApi.listDocuments.mockImplementation(
      (options: ListDocumentsOptions = {}) => {
        const limit = options.limit ?? 20;
        const offset = options.offset ?? 0;
        const rows = Array.from({ length: TOTAL_DOCUMENTS }, (_, i) =>
          documentRow(i + 1),
        ).slice(offset, offset + limit);
        return Promise.resolve({
          items: options.status === "indexed" ? rows.slice(0, 1) : rows,
          total: TOTAL_DOCUMENTS,
          limit,
          offset,
          status: options.status ?? null,
          sort_by: "updated_at",
          sort_order: "desc",
        });
      },
    );
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it("says the chunk total covers only the fetched documents", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <DashboardPage />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Based on the first 2 of 5 documents"),
    ).toBeInTheDocument();
    expect(screen.getByText("20+")).toBeInTheDocument();
  });
});
