import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAccessDebuggerPage } from "@/components/admin/AdminAccessDebuggerPage";
import type {
  OrgMemberListResponse,
  SimulateAccessResponse,
} from "@/lib/api/access-debugger";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn((_p: string) => true),
  hasAnyPermission: vi.fn((..._ps: string[]) => true),
  hasAllPermissions: vi.fn((..._ps: string[]) => true),
  role: "admin" as string | null,
  permissions: new Set<string>(),
}));

const mockApi = vi.hoisted(() => ({
  searchOrgUsers: vi.fn(),
  simulateAccess: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/access-debugger", () => ({
  searchOrgUsers: (...args: unknown[]) => mockApi.searchOrgUsers(...args),
  simulateAccess: (...args: unknown[]) => mockApi.simulateAccess(...args),
}));

// ── fixtures ───────────────────────────────────────────────────────────────────

const USERS_RESPONSE: OrgMemberListResponse = {
  items: [
    {
      user_id: "00000000-0000-0000-0000-000000000001",
      display_name: "Alice Smith",
      email: "alice@example.com",
      role: "member",
    },
    {
      user_id: "00000000-0000-0000-0000-000000000002",
      display_name: "Bob Jones",
      email: "bob@example.com",
      role: "admin",
    },
  ],
  total: 2,
};

const ALLOW_RESULT: SimulateAccessResponse = {
  decision: "allow",
  extended_status: "allowed",
  matched_rule: "owner_admin_override",
  deny_reason: null,
  subject_user_id: "00000000-0000-0000-0000-000000000002",
  subject_display_name: "Bob Jones",
  subject_email: "bob@example.com",
  subject_role: "admin",
  resource_type: "document",
  resource_id: null,
  action: "view",
  trace: [
    { rule: "no_organization_context", outcome: "pass", detail: null },
    { rule: "owner_admin_override", outcome: "allow", detail: null },
  ],
  reason_chain: [
    { layer: "organization_membership", outcome: "pass", detail: null },
    { layer: "role", outcome: "allow", detail: null },
  ],
  effective_permissions: ["documents:view", "chat:use", "roles:manage"],
  remediation: [],
  troubleshooting_links: [
    { label: "View audit logs", href: "/admin/audit-logs" },
    { label: "View access management", href: "/admin/permissions" },
  ],
  request_id: "req-abc-123",
};

const DENY_RESULT: SimulateAccessResponse = {
  decision: "deny",
  extended_status: "denied",
  matched_rule: "role_permission",
  deny_reason: "insufficient_role",
  subject_user_id: "00000000-0000-0000-0000-000000000001",
  subject_display_name: "Alice Smith",
  subject_email: "alice@example.com",
  subject_role: "member",
  resource_type: "collection",
  resource_id: null,
  action: "manage",
  trace: [
    { rule: "no_organization_context", outcome: "pass", detail: null },
    { rule: "role_permission", outcome: "deny", detail: "insufficient_role" },
  ],
  reason_chain: [
    { layer: "organization_membership", outcome: "pass", detail: null },
    { layer: "role", outcome: "deny", detail: "insufficient_role" },
  ],
  effective_permissions: ["documents:view", "chat:use"],
  remediation: [
    "Grant the user a role with sufficient permissions for collection access.",
  ],
  troubleshooting_links: [
    { label: "View audit logs", href: "/admin/audit-logs" },
    { label: "View access management", href: "/admin/permissions" },
  ],
  request_id: "req-def-456",
};

// ── helpers ────────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminAccessDebuggerPage />
    </QueryClientProvider>,
  );
}

// ── tests ──────────────────────────────────────────────────────────────────────

describe("AdminAccessDebuggerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPermissions.hasPermission.mockImplementation((_p: string) => true);
    mockApi.searchOrgUsers.mockResolvedValue(USERS_RESPONSE);
    mockApi.simulateAccess.mockResolvedValue(ALLOW_RESULT);
  });

  describe("access control", () => {
    it("renders forbidden state when user lacks security_center:view", () => {
      mockPermissions.hasPermission.mockReturnValue(false);
      renderPage();
      expect(screen.getAllByText(/access debugger/i).length).toBeGreaterThan(0);
      expect(screen.queryByText(/simulation parameters/i)).toBeNull();
    });

    it("renders form when user has security_center:view", () => {
      renderPage();
      expect(screen.getByText(/simulation parameters/i)).toBeTruthy();
    });
  });

  describe("empty state", () => {
    it("shows empty state before any simulation", () => {
      renderPage();
      expect(screen.getByTestId("empty-state")).toBeTruthy();
    });

    it("shows prompt to select user and simulate", () => {
      renderPage();
      expect(screen.getByText(/select a user/i)).toBeTruthy();
    });
  });

  describe("user search", () => {
    it("renders user search input", () => {
      renderPage();
      expect(
        screen.getByPlaceholderText(/search by name or email/i),
      ).toBeTruthy();
    });

    it("fetches users on focus", async () => {
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => expect(mockApi.searchOrgUsers).toHaveBeenCalled());
    });

    it("displays user results in dropdown", async () => {
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => expect(screen.getByText("Alice Smith")).toBeTruthy());
      expect(screen.getByText("Bob Jones")).toBeTruthy();
    });

    it("selecting a user updates the input and shows user ID", async () => {
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Alice Smith"));
      await userEvent.click(screen.getByText("Alice Smith"));
      expect(
        screen.getByText(/00000000-0000-0000-0000-000000000001/),
      ).toBeTruthy();
    });

    it("shows empty message when search returns no results", async () => {
      mockApi.searchOrgUsers.mockResolvedValue({ items: [], total: 0 });
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() =>
        expect(screen.getByText(/no users found/i)).toBeTruthy(),
      );
    });
  });

  describe("form validation", () => {
    it("shows error when simulate clicked without user", async () => {
      renderPage();
      // Button is disabled when no user is selected — submit the form directly
      const form = document.querySelector("form")!;
      fireEvent.submit(form);
      expect(screen.getByText(/select a subject user/i)).toBeTruthy();
    });

    it("simulate button is disabled without user selection", () => {
      renderPage();
      const btn = screen.getByRole("button", { name: /simulate/i });
      expect(btn).toBeDisabled();
    });
  });

  describe("simulate — allow result", () => {
    async function runSimulation() {
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByText("Bob Jones"));
      const btn = screen.getByRole("button", { name: /simulate/i });
      await userEvent.click(btn);
      await waitFor(() => screen.getByTestId("result-panel"));
    }

    it("shows result panel after successful simulation", async () => {
      await runSimulation();
      expect(screen.getByTestId("result-panel")).toBeTruthy();
    });

    it("shows Allowed status for allow decision", async () => {
      await runSimulation();
      expect(screen.getByText(/allowed/i)).toBeTruthy();
    });

    it("shows subject name in result", async () => {
      await runSimulation();
      expect(screen.getByText("Bob Jones")).toBeTruthy();
    });

    it("shows matched rule", async () => {
      await runSimulation();
      expect(screen.getByText("owner_admin_override")).toBeTruthy();
    });

    it("shows troubleshooting links", async () => {
      await runSimulation();
      expect(screen.getByText(/view audit logs/i)).toBeTruthy();
      expect(screen.getByText(/view access management/i)).toBeTruthy();
    });

    it("shows reason chain section", async () => {
      await runSimulation();
      expect(screen.getByText(/reason chain/i)).toBeTruthy();
    });

    it("shows request ID", async () => {
      await runSimulation();
      expect(screen.getByText(/req-abc-123/)).toBeTruthy();
    });

    it("calls simulateAccess with correct params", async () => {
      await runSimulation();
      expect(mockApi.simulateAccess).toHaveBeenCalledWith(
        expect.objectContaining({
          subject_user_id: "00000000-0000-0000-0000-000000000002",
          resource_type: "document",
          action: "view",
        }),
      );
    });
  });

  describe("simulate — deny result", () => {
    beforeEach(() => {
      mockApi.simulateAccess.mockResolvedValue(DENY_RESULT);
    });

    async function runSimulation() {
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Alice Smith"));
      await userEvent.click(screen.getByText("Alice Smith"));
      const btn = screen.getByRole("button", { name: /simulate/i });
      await userEvent.click(btn);
      await waitFor(() => screen.getByTestId("result-panel"));
    }

    it("shows Denied status for deny decision", async () => {
      await runSimulation();
      expect(screen.getByText(/denied/i)).toBeTruthy();
    });

    it("shows deny reason", async () => {
      await runSimulation();
      expect(screen.getAllByText("insufficient_role").length).toBeGreaterThan(
        0,
      );
    });

    it("shows remediation when decision is deny", async () => {
      await runSimulation();
      expect(screen.getByText(/how to grant access/i)).toBeTruthy();
      expect(
        screen.getByText(/grant the user a role with sufficient permissions/i),
      ).toBeTruthy();
    });
  });

  describe("error handling", () => {
    it("shows error message when simulation fails", async () => {
      mockApi.simulateAccess.mockRejectedValue(
        new Error("Internal server error"),
      );
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Alice Smith"));
      await userEvent.click(screen.getByText("Alice Smith"));
      await userEvent.click(screen.getByRole("button", { name: /simulate/i }));
      await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    });

    it("clears previous result on new error", async () => {
      mockApi.simulateAccess.mockResolvedValueOnce(ALLOW_RESULT);
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByRole("button", { name: /simulate/i }));
      await waitFor(() => screen.getByTestId("result-panel"));

      mockApi.simulateAccess.mockRejectedValue(new Error("Server error"));
      await userEvent.click(screen.getByRole("button", { name: /simulate/i }));
      await waitFor(() =>
        expect(screen.queryByTestId("result-panel")).toBeNull(),
      );
    });
  });

  describe("security guard", () => {
    it("page header mentions audit logging", () => {
      renderPage();
      expect(screen.getAllByText(/audit-logged/i).length).toBeGreaterThan(0);
    });

    it("security note mentions tenant-scoped", () => {
      renderPage();
      expect(screen.getByText(/tenant-scoped/i)).toBeTruthy();
    });

    it("no resource content fields appear in result", async () => {
      mockApi.simulateAccess.mockResolvedValue(ALLOW_RESULT);
      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByRole("button", { name: /simulate/i }));
      await waitFor(() => screen.getByTestId("result-panel"));
      const body = document.body.textContent ?? "";
      expect(body).not.toMatch(/document body/i);
      expect(body).not.toMatch(/raw text/i);
    });
  });

  describe("resource-specific troubleshooting links", () => {
    it("document resource adds document detail link", async () => {
      const docId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
      mockApi.simulateAccess.mockResolvedValue({
        ...ALLOW_RESULT,
        resource_id: docId,
        troubleshooting_links: [
          { label: "View audit logs", href: "/admin/audit-logs" },
          { label: "View document details", href: `/documents/${docId}` },
          { label: "View access management", href: "/admin/permissions" },
        ],
      });

      renderPage();
      const input = screen.getByPlaceholderText(/search by name or email/i);
      await userEvent.click(input);
      await waitFor(() => screen.getByText("Bob Jones"));
      await userEvent.click(screen.getByText("Bob Jones"));
      const resourceInput = screen.getByPlaceholderText(
        /uuid of the specific resource/i,
      );
      await userEvent.type(resourceInput, docId);
      await userEvent.click(screen.getByRole("button", { name: /simulate/i }));
      await waitFor(() => screen.getByTestId("result-panel"));
      expect(screen.getByText(/view document details/i)).toBeTruthy();
    });
  });
});
