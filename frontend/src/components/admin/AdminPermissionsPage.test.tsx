import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPermissionsPage } from "@/components/admin/AdminPermissionsPage";
import type { RoleMatrixResponse, ResourceAccessListResponse } from "@/lib/api/permissions";

// ── mocks ──────────────────────────────────────────────────────────────────────

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn((_p: string) => true),
  hasAnyPermission: vi.fn((..._ps: string[]) => true),
  hasAllPermissions: vi.fn((..._ps: string[]) => true),
  role: "admin" as string | null,
  permissions: new Set<string>(),
}));

const mockApi = vi.hoisted(() => ({
  getRoleMatrix: vi.fn(),
  updateRolePermissions: vi.fn(),
  listResourceGrants: vi.fn(),
  createResourceGrant: vi.fn(),
  revokeResourceGrant: vi.fn(),
  listResourceDenies: vi.fn(),
  createResourceDeny: vi.fn(),
  revokeResourceDeny: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/permissions", () => ({
  getRoleMatrix: (...args: unknown[]) => mockApi.getRoleMatrix(...args),
  updateRolePermissions: (...args: unknown[]) => mockApi.updateRolePermissions(...args),
  listResourceGrants: (...args: unknown[]) => mockApi.listResourceGrants(...args),
  createResourceGrant: (...args: unknown[]) => mockApi.createResourceGrant(...args),
  revokeResourceGrant: (...args: unknown[]) => mockApi.revokeResourceGrant(...args),
  listResourceDenies: (...args: unknown[]) => mockApi.listResourceDenies(...args),
  createResourceDeny: (...args: unknown[]) => mockApi.createResourceDeny(...args),
  revokeResourceDeny: (...args: unknown[]) => mockApi.revokeResourceDeny(...args),
}));

// ── fixtures ───────────────────────────────────────────────────────────────────

const MATRIX_RESPONSE: RoleMatrixResponse = {
  roles: [
    {
      role: "owner",
      label: "Owner",
      description: "Full access",
      is_builtin: true,
      permissions: ["roles:manage", "billing:manage"],
      overridden_permissions: [],
    },
    {
      role: "admin",
      label: "Admin",
      description: "Full access except billing",
      is_builtin: true,
      permissions: ["roles:manage", "team:manage"],
      overridden_permissions: [],
    },
    {
      role: "member",
      label: "Member",
      description: "Standard access",
      is_builtin: true,
      permissions: ["documents:view", "chat:use"],
      overridden_permissions: [],
    },
  ],
  all_permissions: [
    "billing:manage",
    "chat:use",
    "documents:view",
    "roles:manage",
    "team:manage",
  ],
};

const EMPTY_GRANTS: ResourceAccessListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
};

const EMPTY_DENIES: ResourceAccessListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
};

const GRANT_ITEM = {
  id: "grant-1",
  organization_id: "org-1",
  user_id: "user-1",
  role_name: null,
  principal_type: "user",
  principal_value: "user-abc",
  resource_type: "document",
  resource_id: "doc-1",
  action: "read_only",
  status: "active",
  expires_at: null,
  reason: "Testing",
  created_by_user_id: "admin-1",
  created_at: "2026-06-18T00:00:00Z",
  updated_at: "2026-06-18T00:00:00Z",
  kind: "grant" as const,
};

// ── helpers ────────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AdminPermissionsPage />
    </QueryClientProvider>,
  );
}

// ── tests ──────────────────────────────────────────────────────────────────────

describe("AdminPermissionsPage", () => {
  beforeEach(() => {
    mockPermissions.hasPermission.mockImplementation(() => true);
    mockApi.getRoleMatrix.mockReset();
    mockApi.updateRolePermissions.mockReset();
    mockApi.listResourceGrants.mockReset();
    mockApi.createResourceGrant.mockReset();
    mockApi.revokeResourceGrant.mockReset();
    mockApi.listResourceDenies.mockReset();
    mockApi.createResourceDeny.mockReset();
    mockApi.revokeResourceDeny.mockReset();

    mockApi.getRoleMatrix.mockResolvedValue(MATRIX_RESPONSE);
    mockApi.listResourceGrants.mockResolvedValue(EMPTY_GRANTS);
    mockApi.listResourceDenies.mockResolvedValue(EMPTY_DENIES);
  });

  describe("page header and tabs", () => {
    it("renders page heading", async () => {
      renderPage();
      await waitFor(() =>
        expect(screen.getByText("Access Management")).toBeInTheDocument(),
      );
    });

    it("shows all three tabs", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Role Matrix")).toBeInTheDocument();
        expect(screen.getByText("Resource Grants")).toBeInTheDocument();
        expect(screen.getByText("Resource Denies")).toBeInTheDocument();
      });
    });

    it("defaults to role matrix tab", async () => {
      renderPage();
      await waitFor(() =>
        expect(screen.getByText("Owner")).toBeInTheDocument(),
      );
    });

    it("shows security note banner", async () => {
      renderPage();
      await waitFor(() =>
        expect(screen.getByText(/Backend authorization is the source of truth/)).toBeInTheDocument(),
      );
    });
  });

  describe("role matrix tab", () => {
    it("renders all roles as column headers", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Owner")).toBeInTheDocument();
        expect(screen.getByText("Admin")).toBeInTheDocument();
        expect(screen.getByText("Member")).toBeInTheDocument();
      });
    });

    it("renders all permission rows", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("roles:manage")).toBeInTheDocument();
        expect(screen.getByText("billing:manage")).toBeInTheDocument();
        expect(screen.getByText("documents:view")).toBeInTheDocument();
      });
    });

    it("shows edit buttons for each role when canManage", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Edit Owner")).toBeInTheDocument();
        expect(screen.getByText("Edit Admin")).toBeInTheDocument();
      });
    });

    it("hides edit buttons when user cannot manage", async () => {
      mockPermissions.hasPermission.mockImplementation((p: string) => p === "roles:view");
      renderPage();
      await waitFor(() =>
        expect(screen.queryByText("Edit Owner")).not.toBeInTheDocument(),
      );
    });

    it("opens edit panel on edit button click", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Edit Member"));
      await user.click(screen.getByText("Edit Member"));
      expect(screen.getByText("Editing: Member")).toBeInTheDocument();
    });

    it("calls updateRolePermissions on save", async () => {
      const user = userEvent.setup();
      mockApi.updateRolePermissions.mockResolvedValue({
        role: "member",
        permissions: ["documents:view", "chat:use"],
        overridden_permissions: [],
      });

      renderPage();
      await waitFor(() => screen.getByText("Edit Member"));
      await user.click(screen.getByText("Edit Member"));
      await user.click(screen.getByText("Save changes"));
      await waitFor(() =>
        expect(mockApi.updateRolePermissions).toHaveBeenCalledWith(
          "member",
          expect.any(Array),
        ),
      );
    });

    it("shows confirmation dialog when editing owner role", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Edit Owner"));
      await user.click(screen.getByText("Edit Owner"));
      await user.click(screen.getByText("Save changes"));
      await waitFor(() =>
        expect(
          screen.getByText("Confirm owner role change"),
        ).toBeInTheDocument(),
      );
    });

    it("shows error when updateRolePermissions fails", async () => {
      const user = userEvent.setup();
      mockApi.updateRolePermissions.mockRejectedValue(
        new Error("Unsafe change: roles:manage required"),
      );

      renderPage();
      await waitFor(() => screen.getByText("Edit Member"));
      await user.click(screen.getByText("Edit Member"));
      await user.click(screen.getByText("Save changes"));
      await waitFor(() =>
        expect(
          screen.getByText(/Unsafe change/),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("forbidden state", () => {
    it("shows forbidden state when user lacks roles:view", async () => {
      mockPermissions.hasPermission.mockReturnValue(false);
      renderPage();
      await waitFor(() =>
        expect(
          screen.getByText(/roles:view permission/),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("resource grants tab", () => {
    it("switches to grants tab and shows empty state", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() =>
        expect(screen.getByText(/No grants match/)).toBeInTheDocument(),
      );
    });

    it("renders grants in table", async () => {
      mockApi.listResourceGrants.mockResolvedValue({
        items: [GRANT_ITEM],
        total: 1,
        page: 1,
        page_size: 50,
      });

      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() => {
        expect(screen.getByText("user-abc")).toBeInTheDocument();
        expect(screen.getByText("document")).toBeInTheDocument();
      });
    });

    it("shows Add Grant button when canManage", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() =>
        expect(screen.getByText("+ Add Grant")).toBeInTheDocument(),
      );
    });

    it("shows grant form when Add Grant is clicked", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() => screen.getByText("+ Add Grant"));
      await user.click(screen.getByText("+ Add Grant"));
      expect(screen.getByText("New resource grant")).toBeInTheDocument();
    });

    it("calls createResourceGrant on form submit", async () => {
      mockApi.createResourceGrant.mockResolvedValue(GRANT_ITEM);
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() => screen.getByText("+ Add Grant"));
      await user.click(screen.getByText("+ Add Grant"));

      const principalInput = screen.getByPlaceholderText(
        "e.g. user-uuid or team-name",
      );
      await user.type(principalInput, "user-xyz");

      const resourceTypeSelect = screen.getAllByRole("combobox")[1];
      await user.selectOptions(resourceTypeSelect, "document");

      await user.click(screen.getByText("Create grant"));
      await waitFor(() =>
        expect(mockApi.createResourceGrant).toHaveBeenCalled(),
      );
    });

    it("shows revoke button for active grants", async () => {
      mockApi.listResourceGrants.mockResolvedValue({
        items: [GRANT_ITEM],
        total: 1,
        page: 1,
        page_size: 50,
      });

      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() => screen.getByText("Revoke"));
    });

    it("opens revoke confirmation dialog", async () => {
      mockApi.listResourceGrants.mockResolvedValue({
        items: [GRANT_ITEM],
        total: 1,
        page: 1,
        page_size: 50,
      });

      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Grants"));
      await user.click(screen.getByText("Resource Grants"));
      await waitFor(() => screen.getByText("Revoke"));
      await user.click(screen.getByText("Revoke"));
      expect(screen.getByText("Revoke grant?")).toBeInTheDocument();
    });
  });

  describe("resource denies tab", () => {
    it("switches to denies tab and shows empty state", async () => {
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Denies"));
      await user.click(screen.getByText("Resource Denies"));
      await waitFor(() =>
        expect(screen.getByText(/No denies match/)).toBeInTheDocument(),
      );
    });

    it("calls createResourceDeny on form submit", async () => {
      const denyItem = { ...GRANT_ITEM, id: "deny-1", kind: "deny" as const };
      mockApi.createResourceDeny.mockResolvedValue(denyItem);

      const user = userEvent.setup();
      renderPage();
      await waitFor(() => screen.getByText("Resource Denies"));
      await user.click(screen.getByText("Resource Denies"));
      await waitFor(() => screen.getByText("+ Add Deny"));
      await user.click(screen.getByText("+ Add Deny"));

      const principalInput = screen.getByPlaceholderText(
        "e.g. user-uuid or team-name",
      );
      await user.type(principalInput, "user-blocked");

      const resourceTypeSelect = screen.getAllByRole("combobox")[1];
      await user.selectOptions(resourceTypeSelect, "connector");

      await user.click(screen.getByText("Create deny"));
      await waitFor(() =>
        expect(mockApi.createResourceDeny).toHaveBeenCalled(),
      );
    });
  });
});
