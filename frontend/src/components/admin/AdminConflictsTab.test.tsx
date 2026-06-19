import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPermissionsPage } from "@/components/admin/AdminPermissionsPage";
import type { ConflictEntry, ConflictListResponse, ScanResult, ExplainDecisionResponse } from "@/lib/api/conflicts";
import type { RoleMatrixResponse, ResourceAccessListResponse } from "@/lib/api/permissions";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn((_p: string) => true),
  hasAnyPermission: vi.fn((..._ps: string[]) => true),
  hasAllPermissions: vi.fn((..._ps: string[]) => true),
  role: "admin" as string | null,
  permissions: new Set<string>(),
}));

const mockPermApi = vi.hoisted(() => ({
  getRoleMatrix: vi.fn(),
  updateRolePermissions: vi.fn(),
  listResourceGrants: vi.fn(),
  createResourceGrant: vi.fn(),
  revokeResourceGrant: vi.fn(),
  listResourceDenies: vi.fn(),
  createResourceDeny: vi.fn(),
  revokeResourceDeny: vi.fn(),
}));

const mockConflictsApi = vi.hoisted(() => ({
  listConflicts: vi.fn(),
  getConflict: vi.fn(),
  updateConflictStatus: vi.fn(),
  scanForConflicts: vi.fn(),
  explainDecision: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/permissions", () => ({
  getRoleMatrix: (...args: unknown[]) => mockPermApi.getRoleMatrix(...args),
  updateRolePermissions: (...args: unknown[]) => mockPermApi.updateRolePermissions(...args),
  listResourceGrants: (...args: unknown[]) => mockPermApi.listResourceGrants(...args),
  createResourceGrant: (...args: unknown[]) => mockPermApi.createResourceGrant(...args),
  revokeResourceGrant: (...args: unknown[]) => mockPermApi.revokeResourceGrant(...args),
  listResourceDenies: (...args: unknown[]) => mockPermApi.listResourceDenies(...args),
  createResourceDeny: (...args: unknown[]) => mockPermApi.createResourceDeny(...args),
  revokeResourceDeny: (...args: unknown[]) => mockPermApi.revokeResourceDeny(...args),
}));

vi.mock("@/lib/api/conflicts", () => ({
  listConflicts: (...args: unknown[]) => mockConflictsApi.listConflicts(...args),
  getConflict: (...args: unknown[]) => mockConflictsApi.getConflict(...args),
  updateConflictStatus: (...args: unknown[]) => mockConflictsApi.updateConflictStatus(...args),
  scanForConflicts: (...args: unknown[]) => mockConflictsApi.scanForConflicts(...args),
  explainDecision: (...args: unknown[]) => mockConflictsApi.explainDecision(...args),
}));

// ── fixtures ───────────────────────────────────────────────────────────────────

const EMPTY_MATRIX: RoleMatrixResponse = {
  roles: [],
  all_permissions: [],
};

const EMPTY_GRANTS: ResourceAccessListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
};

const CONFLICT_ITEM: ConflictEntry = {
  id: "conflict-abc-123",
  organization_id: "org-1",
  subject_type: "user",
  subject_value: "user-xyz",
  user_id: null,
  role_name: "member",
  resource_type: "document",
  resource_id: "doc-1",
  action: "read_only",
  conflict_type: "role_allow_resource_deny",
  severity: "blocking",
  status: "open",
  detected_at: "2026-06-18T10:00:00Z",
  resolved_at: null,
  conflict_summary: "Grant allows but deny blocks same principal.",
  grant_id: "grant-111",
  deny_id: "deny-222",
  remediation: [
    "Review the explicit deny entry and remove it if access should be granted.",
    "If the deny is intentional, revoke the conflicting grant.",
  ],
  context: { grant_id: "grant-111", deny_id: "deny-222" },
};

const CONFLICT_LIST: ConflictListResponse = {
  items: [CONFLICT_ITEM],
  total: 1,
  page: 1,
  page_size: 50,
};

const EMPTY_CONFLICTS: ConflictListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
};

const SCAN_RESULT: ScanResult = {
  conflicts_detected: 2,
  conflicts_created: 1,
  scan_duration_ms: 42,
  scanned_grants: 5,
  scanned_denies: 3,
  scanned_acl_mappings: 1,
};

const EXPLAIN_ALLOW: ExplainDecisionResponse = {
  decision: "allow",
  matched_rule: "owner_admin_override",
  deny_reason: null,
  subject_user_id: "user-abc",
  resource_type: "document",
  resource_id: null,
  action: "view",
  trace: [
    { rule: "no_organization_context", outcome: "pass", detail: null },
    { rule: "owner_admin_override", outcome: "allow", detail: null },
  ],
  remediation: [],
  request_id: "req-xxx",
};

const EXPLAIN_DENY: ExplainDecisionResponse = {
  decision: "deny",
  matched_rule: "role_permission",
  deny_reason: "insufficient_role",
  subject_user_id: "user-abc",
  resource_type: "document",
  resource_id: null,
  action: "view",
  trace: [
    { rule: "no_organization_context", outcome: "pass", detail: null },
    { rule: "role_permission", outcome: "deny", detail: "insufficient_role" },
  ],
  remediation: ["Grant the user a role with sufficient permissions for document access."],
  request_id: "req-yyy",
};

// ── setup ──────────────────────────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <AdminPermissionsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockPermApi.getRoleMatrix.mockResolvedValue(EMPTY_MATRIX);
  mockPermApi.listResourceGrants.mockResolvedValue(EMPTY_GRANTS);
  mockPermApi.listResourceDenies.mockResolvedValue(EMPTY_GRANTS);
  mockConflictsApi.listConflicts.mockResolvedValue(EMPTY_CONFLICTS);
  mockConflictsApi.getConflict.mockResolvedValue(CONFLICT_ITEM);
  mockConflictsApi.scanForConflicts.mockResolvedValue(SCAN_RESULT);
  mockConflictsApi.explainDecision.mockResolvedValue(EXPLAIN_ALLOW);
});

// ─── tab navigation ───────────────────────────────────────────────────────────

describe("Tab navigation", () => {
  it("renders the Conflicts tab button", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /conflicts/i })).toBeInTheDocument();
  });

  it("renders the Access Debugger tab button", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /access debugger/i })).toBeInTheDocument();
  });

  it("clicking Conflicts tab calls listConflicts", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /conflicts/i }));
    await waitFor(() => expect(mockConflictsApi.listConflicts).toHaveBeenCalled());
  });

  it("clicking Access Debugger tab shows subject user ID input", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /access debugger/i }));
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/uuid of the user/i)).toBeInTheDocument(),
    );
  });
});

// ─── conflicts tab ────────────────────────────────────────────────────────────

describe("ConflictsTab", () => {
  async function openConflictsTab() {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /conflicts/i }));
    return user;
  }

  it("shows empty state when no conflicts", async () => {
    await openConflictsTab();
    await waitFor(() =>
      expect(screen.getByText(/no conflicts match/i)).toBeInTheDocument(),
    );
  });

  it("renders conflict rows when data is present", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    await openConflictsTab();
    await waitFor(() =>
      expect(screen.getByText(/role allow resource deny/i)).toBeInTheDocument(),
    );
  });

  it("displays severity badge", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    await openConflictsTab();
    await waitFor(() => expect(screen.getByText(/blocking/i)).toBeInTheDocument());
  });

  it("displays status badge", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    await openConflictsTab();
    await waitFor(() => expect(screen.getAllByText(/open/i).length).toBeGreaterThan(0));
  });

  it("shows Run scan button for admins", async () => {
    await openConflictsTab();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /run scan/i })).toBeInTheDocument(),
    );
  });

  it("clicking Run scan calls scanForConflicts", async () => {
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /run scan/i }));
    await user.click(screen.getByRole("button", { name: /run scan/i }));
    await waitFor(() => expect(mockConflictsApi.scanForConflicts).toHaveBeenCalledOnce());
  });

  it("shows scan result summary after scan", async () => {
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /run scan/i }));
    await user.click(screen.getByRole("button", { name: /run scan/i }));
    await waitFor(() =>
      expect(screen.getByText(/2 conflicts detected/i)).toBeInTheDocument(),
    );
  });

  it("clicking View opens the conflict drawer", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /view/i }));
    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() => expect(mockConflictsApi.getConflict).toHaveBeenCalledWith("conflict-abc-123"));
  });

  it("conflict drawer shows summary and remediation", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /view/i }));
    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() =>
      expect(screen.getByText(/Grant allows but deny blocks/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Review the explicit deny/i)).toBeInTheDocument();
  });

  it("conflict drawer has status transition buttons", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /view/i }));
    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /mark resolved/i })).toBeInTheDocument(),
    );
  });

  it("resolving conflict calls updateConflictStatus", async () => {
    mockConflictsApi.listConflicts.mockResolvedValue(CONFLICT_LIST);
    mockConflictsApi.updateConflictStatus.mockResolvedValue({ ...CONFLICT_ITEM, status: "resolved" });
    const user = await openConflictsTab();
    await waitFor(() => screen.getByRole("button", { name: /view/i }));
    await user.click(screen.getByRole("button", { name: /view/i }));
    await waitFor(() => screen.getByRole("button", { name: /mark resolved/i }));
    await user.click(screen.getByRole("button", { name: /mark resolved/i }));
    await waitFor(() =>
      expect(mockConflictsApi.updateConflictStatus).toHaveBeenCalledWith("conflict-abc-123", {
        status: "resolved",
        resolution_note: null,
      }),
    );
  });

  it("applies severity filter via select", async () => {
    const user = await openConflictsTab();
    await waitFor(() => screen.getByDisplayValue(/all severities/i));
    await user.selectOptions(screen.getByDisplayValue(/all severities/i), "blocking");
    await waitFor(() =>
      expect(mockConflictsApi.listConflicts).toHaveBeenCalledWith(
        expect.objectContaining({ severity: "blocking" }),
      ),
    );
  });

  it("applies status filter via select", async () => {
    const user = await openConflictsTab();
    await waitFor(() => screen.getAllByDisplayValue(/all statuses/i));
    const selects = screen.getAllByDisplayValue(/all statuses/i);
    await user.selectOptions(selects[0], "open");
    await waitFor(() =>
      expect(mockConflictsApi.listConflicts).toHaveBeenCalledWith(
        expect.objectContaining({ status: "open" }),
      ),
    );
  });
});

// ─── access debugger tab ──────────────────────────────────────────────────────

describe("AccessDebuggerTab", () => {
  async function openDebuggerTab() {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /access debugger/i }));
    await waitFor(() => screen.getByPlaceholderText(/uuid of the user/i));
    return user;
  }

  it("shows description text", async () => {
    await openDebuggerTab();
    expect(screen.getByText(/simulate the policy engine/i)).toBeInTheDocument();
  });

  it("submitting without user ID shows validation error", async () => {
    const user = await openDebuggerTab();
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() =>
      expect(screen.getByText(/subject user id is required/i)).toBeInTheDocument(),
    );
    expect(mockConflictsApi.explainDecision).not.toHaveBeenCalled();
  });

  it("submitting with user ID calls explainDecision", async () => {
    const user = await openDebuggerTab();
    await user.type(
      screen.getByPlaceholderText(/uuid of the user/i),
      "user-uuid-123",
    );
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() =>
      expect(mockConflictsApi.explainDecision).toHaveBeenCalledWith(
        expect.objectContaining({ subject_user_id: "user-uuid-123" }),
      ),
    );
  });

  it("shows ALLOW result with green badge", async () => {
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() => expect(screen.getByText(/allow/i)).toBeInTheDocument());
  });

  it("shows DENY result with deny reason", async () => {
    mockConflictsApi.explainDecision.mockResolvedValue(EXPLAIN_DENY);
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() => expect(screen.getByText(/insufficient_role/i)).toBeInTheDocument());
  });

  it("shows policy trace steps", async () => {
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() =>
      expect(screen.getByText(/no_organization_context/i)).toBeInTheDocument(),
    );
  });

  it("shows remediation suggestions for deny", async () => {
    mockConflictsApi.explainDecision.mockResolvedValue(EXPLAIN_DENY);
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() =>
      expect(screen.getByText(/grant the user a role/i)).toBeInTheDocument(),
    );
  });

  it("shows request ID in result", async () => {
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() => expect(screen.getByText(/req-xxx/i)).toBeInTheDocument());
  });

  it("no remediation shown for allow result", async () => {
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "user-abc");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() => screen.getByText(/allow/i));
    expect(screen.queryByText(/how to grant access/i)).not.toBeInTheDocument();
  });

  it("api error is shown in form", async () => {
    mockConflictsApi.explainDecision.mockRejectedValue(new Error("User not found"));
    const user = await openDebuggerTab();
    await user.type(screen.getByPlaceholderText(/uuid of the user/i), "bad-uuid");
    await user.click(screen.getByRole("button", { name: /check access/i }));
    await waitFor(() =>
      expect(screen.getByText(/user not found/i)).toBeInTheDocument(),
    );
  });
});

// ─── permission-aware rendering ───────────────────────────────────────────────

describe("Permission-aware rendering", () => {
  it("non-admin sees forbidden state for whole page", async () => {
    mockPermissions.hasPermission.mockReturnValue(false);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/you need the roles:view permission/i)).toBeInTheDocument(),
    );
  });

  it("read-only admin sees conflicts tab but no scan button", async () => {
    mockPermissions.hasPermission.mockImplementation((p: string) =>
      p === "roles:view" || p === "security_center:view",
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /conflicts/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /run scan/i })).not.toBeInTheDocument(),
    );
  });
});
