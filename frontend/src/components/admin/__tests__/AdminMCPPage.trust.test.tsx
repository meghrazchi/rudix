/**
 * Frontend tests for F176: MCP trust and exposure controls
 *
 * Covers MCPTrustControlsSection rendering, interaction, and the full
 * PolicyForm save mutation with new trust fields included.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminMCPPage } from "@/components/admin/AdminMCPPage";
import type {
  OrgMCPPolicy,
  MCPStatusResponse,
  MCPToolListResponse,
  MCPAuditEventListResponse,
} from "@/lib/api/mcp";

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  getMCPPolicy: vi.fn(),
  getMCPStatus: vi.fn(),
  listMCPTools: vi.fn(),
  listMCPAuditEvents: vi.fn(),
  updateMCPPolicy: vi.fn(),
}));

vi.mock("@/lib/api/mcp", () => ({
  getMCPPolicy: (...args: unknown[]) => mockApi.getMCPPolicy(...args),
  getMCPStatus: (...args: unknown[]) => mockApi.getMCPStatus(...args),
  listMCPTools: (...args: unknown[]) => mockApi.listMCPTools(...args),
  listMCPAuditEvents: (...args: unknown[]) =>
    mockApi.listMCPAuditEvents(...args),
  updateMCPPolicy: (...args: unknown[]) => mockApi.updateMCPPolicy(...args),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
  getSupportAction: () => null,
  sanitizeRequestId: () => null,
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const BASE_POLICY: OrgMCPPolicy = {
  organization_id: "org-1",
  enabled: true,
  read_only: false,
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
  updated_at: "2026-06-21T00:00:00Z",
};

const BASE_STATUS: MCPStatusResponse = {
  feature_enabled: true,
  auth_required: true,
  transport: "http",
  server_name: "rudix-mcp",
  rate_limit_enabled: true,
  rate_limit_requests: 30,
  rate_limit_window_seconds: 60,
  http_host: "localhost",
  http_port: 8010,
  http_path: "/mcp",
  dependencies: {},
  failed_dependencies: [],
};

const EMPTY_TOOLS: MCPToolListResponse = { items: [], total: 0 };
const EMPTY_AUDIT: MCPAuditEventListResponse = { items: [], total: 0 };

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(client = makeClient()) {
  return render(
    <QueryClientProvider client={client}>
      <AdminMCPPage />
    </QueryClientProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("MCPTrustControlsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getMCPPolicy.mockResolvedValue(BASE_POLICY);
    mockApi.getMCPStatus.mockResolvedValue(BASE_STATUS);
    mockApi.listMCPTools.mockResolvedValue(EMPTY_TOOLS);
    mockApi.listMCPAuditEvents.mockResolvedValue(EMPTY_AUDIT);
    mockApi.updateMCPPolicy.mockResolvedValue(BASE_POLICY);
  });

  it("renders the trust controls section heading", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText("Trust and exposure controls"),
      ).toBeInTheDocument();
    });
  });

  it("shows redact document text toggle in ON state by default", async () => {
    renderPage();
    await waitFor(() => {
      const toggle = screen.getByRole("switch", {
        name: /redact document text/i,
      });
      expect(toggle).toBeInTheDocument();
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
  });

  it("shows redact OFF warning when redact toggle is disabled", async () => {
    mockApi.getMCPPolicy.mockResolvedValue({
      ...BASE_POLICY,
      redact_document_text: false,
    });
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/raw document text may be returned/i),
      ).toBeInTheDocument();
    });
  });

  it("does NOT show redact warning when redact is enabled", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.queryByText(/raw document text may be returned/i),
      ).not.toBeInTheDocument();
    });
  });

  it("renders allowed roles section", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Allowed roles")).toBeInTheDocument();
    });
  });

  it("shows 'allow all roles' checkbox checked when allowed_roles is null", async () => {
    renderPage();
    await waitFor(() => {
      const allowAll = screen.getByRole("checkbox", {
        name: /allow all roles/i,
      });
      expect(allowAll).toBeChecked();
    });
  });

  it("shows role checkboxes when allowed_roles list is set", async () => {
    mockApi.getMCPPolicy.mockResolvedValue({
      ...BASE_POLICY,
      allowed_roles: ["admin", "owner"],
    });
    renderPage();
    await waitFor(() => {
      const adminBox = screen.getByRole("checkbox", { name: /admin/i });
      const memberBox = screen.getByRole("checkbox", { name: /member/i });
      expect(adminBox).toBeChecked();
      expect(memberBox).not.toBeChecked();
    });
  });

  it("renders allowed resources tag editor with 'allow all' when null", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Allowed resources")).toBeInTheDocument();
      const checkboxes = screen.getAllByRole("checkbox", {
        name: /allow all \(no restriction\)/i,
      });
      expect(checkboxes.length).toBeGreaterThan(0);
    });
  });

  it("renders allowed prompts and collections sections", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Allowed prompts")).toBeInTheDocument();
      expect(screen.getByText("Allowed collections")).toBeInTheDocument();
    });
  });

  it("renders max chunk chars field with 'no limit' when null", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Max chunk chars")).toBeInTheDocument();
      const noLimitChecks = screen.getAllByRole("checkbox", {
        name: /no limit/i,
      });
      expect(noLimitChecks.length).toBeGreaterThan(0);
    });
  });

  it("renders max request and response byte fields", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Max request bytes")).toBeInTheDocument();
      expect(screen.getByText("Max response bytes")).toBeInTheDocument();
    });
  });

  it("shows numeric input when max_chunk_chars has a value", async () => {
    mockApi.getMCPPolicy.mockResolvedValue({
      ...BASE_POLICY,
      max_chunk_chars: 500,
    });
    renderPage();
    await waitFor(() => {
      const input = screen.getByDisplayValue("500");
      expect(input).toBeInTheDocument();
    });
  });

  it("toggling redact off in the form then saving sends redact_document_text=false", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      screen.getByRole("switch", { name: /redact document text/i }),
    );

    const toggle = screen.getByRole("switch", {
      name: /redact document text/i,
    });
    await user.click(toggle);

    const saveBtn = screen.getByRole("button", { name: /save policy/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.updateMCPPolicy).toHaveBeenCalledWith(
        expect.objectContaining({ redact_document_text: false }),
      );
    });
  });

  it("save includes null trust allowlists when 'allow all' is checked", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => screen.getByRole("button", { name: /save policy/i }));

    const saveBtn = screen.getByRole("button", { name: /save policy/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.updateMCPPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          allowed_resources: null,
          allowed_prompts: null,
          allowed_collections: null,
          allowed_roles: null,
        }),
      );
    });
  });

  it("save button is disabled while mutation is pending", async () => {
    mockApi.updateMCPPolicy.mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => screen.getByRole("button", { name: /save policy/i }));
    const saveBtn = screen.getByRole("button", { name: /save policy/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
    });
  });

  it("shows error message when updateMCPPolicy rejects", async () => {
    mockApi.updateMCPPolicy.mockRejectedValue(new Error("Server error"));
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => screen.getByRole("button", { name: /save policy/i }));
    await user.click(screen.getByRole("button", { name: /save policy/i }));

    await waitFor(() => {
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
  });
});
