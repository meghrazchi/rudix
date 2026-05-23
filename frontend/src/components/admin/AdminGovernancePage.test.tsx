import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminGovernancePage } from "@/components/admin/AdminGovernancePage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getGovernancePolicy: vi.fn(),
  updateGovernancePolicy: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/admin-governance", () => ({
  getGovernancePolicy: () => mockApi.getGovernancePolicy(),
  updateGovernancePolicy: (payload: unknown) =>
    mockApi.updateGovernancePolicy(payload),
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
      <AdminGovernancePage />
    </QueryClientProvider>,
  );
}

describe("AdminGovernancePage", () => {
  beforeEach(() => {
    mockApi.getGovernancePolicy.mockReset();
    mockApi.updateGovernancePolicy.mockReset();
    mockApi.getGovernancePolicy.mockResolvedValue({
      organization_id: "org-1",
      policy: {
        agentic_mode_enabled: true,
        mcp_exposure_enabled: false,
        allow_side_effect_tools: false,
        allowed_tool_names: ["search_documents"],
        budgets: {
          max_steps: 12,
          max_tool_calls_per_run: 30,
          max_tool_timeout_ms: 8000,
          max_tool_input_bytes: 32768,
          max_tool_output_bytes: 65536,
          max_tool_retry_attempts: 1,
          max_total_tokens: null,
          max_total_cost_usd: null,
        },
        external_mcp_servers: [],
      },
      mcp_status: {
        feature_enable_mcp: true,
        mcp_transport: "streamable_http",
        mcp_http_path: "/mcp",
        mcp_http_host: "0.0.0.0",
        mcp_http_port: 8010,
        mcp_auth_required: true,
        mcp_rate_limit_enabled: true,
        feature_enable_external_mcp_connectors: false,
        configured_global_external_servers: 0,
      },
      tool_catalog: [
        {
          name: "search_documents",
          capability: "documents.read",
          effect_policy: "read_only",
          surfaces: ["api", "mcp"],
          required_roles: ["owner", "admin", "member", "viewer"],
          approval_required: false,
        },
        {
          name: "documents.delete",
          capability: "documents.delete",
          effect_policy: "side_effect",
          surfaces: ["api"],
          required_roles: ["owner", "admin"],
          approval_required: true,
        },
      ],
      warnings: [],
      policy_updated_at: "2026-05-23T08:00:00Z",
      policy_updated_by_user_id: "u-1",
    });
    mockApi.updateGovernancePolicy.mockResolvedValue({
      organization_id: "org-1",
      policy: {
        agentic_mode_enabled: true,
        mcp_exposure_enabled: false,
        allow_side_effect_tools: false,
        allowed_tool_names: ["search_documents"],
        budgets: {
          max_steps: 12,
          max_tool_calls_per_run: 30,
          max_tool_timeout_ms: 8000,
          max_tool_input_bytes: 32768,
          max_tool_output_bytes: 65536,
          max_tool_retry_attempts: 1,
          max_total_tokens: null,
          max_total_cost_usd: null,
        },
        external_mcp_servers: [],
      },
      warnings: [],
      updated_at: "2026-05-23T09:00:00Z",
      updated_by_user_id: "u-1",
      audit_recorded: true,
      changed_fields: ["allowed_tool_names"],
    });
  });

  it("renders policy controls and saves for admin users", async () => {
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

    expect(
      await screen.findByText("Agent and MCP governance"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Tool allowlist")).toBeInTheDocument();
    expect(await screen.findByText("search_documents")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Save governance policy" }),
    );

    await waitFor(() => {
      expect(mockApi.updateGovernancePolicy).toHaveBeenCalledTimes(1);
    });
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
      await screen.findByText("Admin governance restricted"),
    ).toBeInTheDocument();
    expect(mockApi.getGovernancePolicy).not.toHaveBeenCalled();
  });
});
