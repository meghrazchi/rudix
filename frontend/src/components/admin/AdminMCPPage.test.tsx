import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminMCPPage } from "@/components/admin/AdminMCPPage";
import { ApiClientError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";
import type {
  MCPAuditEventListResponse,
  MCPStatusResponse,
  MCPToolListResponse,
  OrgMCPPolicy,
} from "@/lib/api/mcp";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getMCPPolicy: vi.fn(),
  updateMCPPolicy: vi.fn(),
  getMCPStatus: vi.fn(),
  listMCPTools: vi.fn(),
  listMCPAuditEvents: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/mcp", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/mcp")>();
  return {
    ...original,
    getMCPPolicy: () => mockApi.getMCPPolicy(),
    updateMCPPolicy: (req: unknown) => mockApi.updateMCPPolicy(req),
    getMCPStatus: () => mockApi.getMCPStatus(),
    listMCPTools: () => mockApi.listMCPTools(),
    listMCPAuditEvents: (params: unknown) => mockApi.listMCPAuditEvents(params),
  };
});

function makeAdminSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      organizationId: "org-1",
      organizationName: "Test Org",
      role: "admin",
    },
  };
}

function makePolicy(overrides: Partial<OrgMCPPolicy> = {}): OrgMCPPolicy {
  return {
    organization_id: "org-1",
    enabled: false,
    read_only: true,
    allowed_tools: null,
    capabilities_owner: null,
    capabilities_admin: null,
    capabilities_member: null,
    capabilities_viewer: null,
    rate_limit_enabled: true,
    rate_limit_requests: 30,
    rate_limit_window_seconds: 60,
    allowed_resources: null,
    allowed_prompts: null,
    allowed_collections: null,
    allowed_roles: null,
    redact_document_text: true,
    max_chunk_chars: null,
    max_request_bytes: null,
    max_response_bytes: null,
    updated_by_user_id: null,
    updated_at: "2026-06-20T10:00:00Z",
    ...overrides,
  };
}

function makeStatus(
  overrides: Partial<MCPStatusResponse> = {},
): MCPStatusResponse {
  return {
    feature_enabled: false,
    auth_required: true,
    transport: "streamable_http",
    server_name: "Rudix MCP Server",
    rate_limit_enabled: true,
    rate_limit_requests: 30,
    rate_limit_window_seconds: 60,
    http_host: "0.0.0.0",
    http_port: 8010,
    http_path: "/mcp",
    dependencies: {
      feature_flag: { ok: false, detail: "feature_enable_mcp_false" },
      mcp_sdk: { ok: true, detail: null },
      auth_required: { ok: true, detail: null },
    },
    failed_dependencies: ["feature_flag"],
    ...overrides,
  };
}

const emptyTools: MCPToolListResponse = { items: [], total: 0 };
const emptyAuditEvents: MCPAuditEventListResponse = { items: [], total: 0 };

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <AdminMCPPage />
    </QueryClientProvider>,
  );
  return qc;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
  mockApi.getMCPPolicy.mockResolvedValue(makePolicy());
  mockApi.getMCPStatus.mockResolvedValue(makeStatus());
  mockApi.listMCPTools.mockResolvedValue(emptyTools);
  mockApi.listMCPAuditEvents.mockResolvedValue(emptyAuditEvents);
});

describe("AdminMCPPage", () => {
  it("shows loading state initially", () => {
    mockApi.getMCPPolicy.mockReturnValue(new Promise(() => {}));
    mockApi.getMCPStatus.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("renders the page heading after load", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("MCP server")).toBeTruthy();
    });
  });

  it("shows feature-disabled warning when MCP is off", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/FEATURE_ENABLE_MCP/)).toBeTruthy();
    });
  });

  it("shows server status card with transport", async () => {
    mockApi.getMCPStatus.mockResolvedValue(
      makeStatus({ feature_enabled: true, failed_dependencies: [] }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("streamable_http")).toBeTruthy();
    });
  });

  it("shows degraded badge when dependencies fail", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Degraded")).toBeTruthy();
    });
  });

  it("shows healthy badge when all dependencies pass", async () => {
    mockApi.getMCPStatus.mockResolvedValue(
      makeStatus({
        feature_enabled: true,
        failed_dependencies: [],
        dependencies: {
          feature_flag: { ok: true, detail: null },
          mcp_sdk: { ok: true, detail: null },
          auth_required: { ok: true, detail: null },
        },
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Healthy")).toBeTruthy();
    });
  });

  it("shows no-auth warning when bearer auth is disabled", async () => {
    mockApi.getMCPStatus.mockResolvedValue(
      makeStatus({ auth_required: false }),
    );
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/Bearer authentication is disabled/),
      ).toBeTruthy();
    });
  });

  it("renders MCP enabled toggle in correct initial state", async () => {
    renderPage();
    await waitFor(() => {
      const toggle = screen.getByRole("switch", { name: /MCP enabled/i });
      expect(toggle.getAttribute("aria-checked")).toBe("false");
    });
  });

  it("renders read-only toggle checked by default", async () => {
    renderPage();
    await waitFor(() => {
      const toggle = screen.getByRole("switch", { name: /Read-only mode/i });
      expect(toggle.getAttribute("aria-checked")).toBe("true");
    });
  });

  it("shows write-enabled warning after disabling read-only with MCP on", async () => {
    mockApi.getMCPPolicy.mockResolvedValue(
      makePolicy({ enabled: true, read_only: false }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Write operations are enabled/)).toBeTruthy();
    });
  });

  it("calls updateMCPPolicy on form submit", async () => {
    mockApi.updateMCPPolicy.mockResolvedValue(makePolicy({ enabled: true }));
    renderPage();
    await waitFor(() => screen.getByText("Save policy"));

    const user = userEvent.setup();
    await user.click(screen.getByText("Save policy"));

    await waitFor(() => {
      expect(mockApi.updateMCPPolicy).toHaveBeenCalled();
    });
  });

  it("shows success banner after save", async () => {
    mockApi.updateMCPPolicy.mockResolvedValue(makePolicy({ enabled: true }));
    renderPage();
    await waitFor(() => screen.getByText("Save policy"));

    const user = userEvent.setup();
    await user.click(screen.getByText("Save policy"));

    await waitFor(() => {
      expect(screen.getByText("Policy saved.")).toBeTruthy();
    });
  });

  it("shows error message on save failure", async () => {
    mockApi.updateMCPPolicy.mockRejectedValue(
      new ApiClientError({
        status: 500,
        code: "unknown_error",
        message: "Server error",
        details: null,
        requestId: null,
        userMessage: "Server error",
        actionMessage: null,
        retryable: false,
      }),
    );
    renderPage();
    await waitFor(() => screen.getByText("Save policy"));

    const user = userEvent.setup();
    await user.click(screen.getByText("Save policy"));

    await waitFor(() => {
      expect(screen.getByText(/Server error/)).toBeTruthy();
    });
  });

  it("shows empty tools message when MCP is disabled", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/MCP is disabled or no tools are registered/),
      ).toBeTruthy();
    });
  });

  it("renders available tools when present", async () => {
    mockApi.listMCPTools.mockResolvedValue({
      items: [
        {
          name: "search_documents",
          public_name: "search_documents",
          description: "Search documents",
          capability: "documents.read",
          deprecated_alias: false,
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("search_documents")).toBeTruthy();
    });
  });

  it("shows empty audit events message", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("No MCP events recorded yet.")).toBeTruthy();
    });
  });

  it("renders audit events when present", async () => {
    mockApi.listMCPAuditEvents.mockResolvedValue({
      items: [
        {
          id: "evt-1",
          action: "mcp.policy.updated",
          user_id: "user-1",
          resource_type: "mcp_policy",
          resource_id: null,
          metadata: { enabled: true },
          created_at: "2026-06-20T10:00:00Z",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("mcp.policy.updated")).toBeTruthy();
    });
  });

  it("shows forbidden state for non-admin", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        organizationId: "org-1",
        organizationName: "Test Org",
        role: "member",
      },
    };
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("MCP Management")).toBeTruthy();
    });
  });

  it("shows setup instructions section", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Setup instructions")).toBeTruthy();
    });
  });

  it("renders setup instructions with correct port", async () => {
    mockApi.getMCPStatus.mockResolvedValue(makeStatus({ http_port: 9999 }));
    renderPage();
    await waitFor(() => {
      expect(screen.getAllByText(/9999/).length).toBeGreaterThan(0);
    });
  });
});
