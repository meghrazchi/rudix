import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAuditLogsPage } from "@/components/admin/AdminAuditLogsPage";
import { ApiClientError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
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
      <AdminAuditLogsPage />
    </QueryClientProvider>,
  );
}

describe("AdminAuditLogsPage", () => {
  beforeEach(() => {
    mockApi.listAuditLogs.mockReset();
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
          metadata: { status_code: 200, authorization: "Bearer test-token" },
          created_at: "2026-05-14T12:00:00Z",
        },
        {
          audit_log_id: "audit-2",
          organization_id: "org-1",
          user_id: "user-2",
          action: "documents.reindex.failed",
          resource_type: "document",
          resource_id: "doc-2",
          request_id: "req-2",
          metadata: { status_code: 503, detail: "downstream timeout" },
          created_at: "2026-05-15T12:00:00Z",
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
      range: { from: "2026-05-01", to: "2026-05-30" },
    });
  });

  it("renders audit table and supports local status filtering", async () => {
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
    expect(await screen.findByText("Audit logs")).toBeInTheDocument();
    expect(await screen.findByText("chat.query.completed")).toBeInTheDocument();
    expect(
      await screen.findByText("documents.reindex.failed"),
    ).toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Status" }),
      "server_error",
    );

    expect(
      await screen.findByText("documents.reindex.failed"),
    ).toBeInTheDocument();
    expect(screen.queryByText("chat.query.completed")).not.toBeInTheDocument();
  });

  it("shows sanitized metadata in event detail drawer", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "owner@example.com",
        role: "owner",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();
    await screen.findByText("chat.query.completed");

    await userEvent.click(
      screen.getAllByRole("button", { name: "View details" })[0],
    );
    expect(await screen.findByText("Sanitized metadata")).toBeInTheDocument();
    expect(screen.getByText(/redacted/i)).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByText("Sanitized metadata")).not.toBeInTheDocument();
    });
  });

  it("renders forbidden state for non-admin role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-3",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-3",
      },
    };

    renderPage();
    expect(
      await screen.findByText("Admin audit logs restricted"),
    ).toBeInTheDocument();
    expect(mockApi.listAuditLogs).not.toHaveBeenCalled();
  });

  it("shows implementation-needed state when endpoint is unavailable", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-4",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-4",
      },
    };

    mockApi.listAuditLogs.mockRejectedValue(
      new ApiClientError({
        status: 404,
        code: "not_found",
        message: "Not found",
        details: { detail: "missing" },
        requestId: null,
        userMessage: "The requested resource was not found.",
        actionMessage: "Refresh and verify the selected resource.",
        retryable: false,
      }),
    );

    renderPage();

    expect(
      await screen.findByText(
        "Audit log endpoint is not configured for this deployment.",
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(mockApi.listAuditLogs).toHaveBeenCalled();
    });
  });
});
