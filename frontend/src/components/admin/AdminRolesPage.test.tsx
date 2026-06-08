import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminRolesPage } from "@/components/admin/AdminRolesPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  BuiltinRole,
  CustomRole,
  PermissionCatalogResponse,
  RoleListResponse,
} from "@/lib/api/roles";

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn((_p: string) => true),
  hasAnyPermission: vi.fn((..._ps: string[]) => true),
  hasAllPermissions: vi.fn((..._ps: string[]) => true),
  role: "admin" as string | null,
  permissions: new Set<string>(),
}));

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Acme",
    },
  } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listRoles: vi.fn(),
  listPermissions: vi.fn(),
  createCustomRole: vi.fn(),
  updateCustomRole: vi.fn(),
  deleteCustomRole: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/roles", () => ({
  listRoles: (...args: unknown[]) => mockApi.listRoles(...args),
  listPermissions: (...args: unknown[]) => mockApi.listPermissions(...args),
  createCustomRole: (...args: unknown[]) => mockApi.createCustomRole(...args),
  updateCustomRole: (...args: unknown[]) => mockApi.updateCustomRole(...args),
  deleteCustomRole: (...args: unknown[]) => mockApi.deleteCustomRole(...args),
}));

const BUILTIN_OWNER: BuiltinRole = {
  role: "owner",
  label: "Owner",
  description: "Full access including billing",
  permissions: ["billing:manage", "roles:manage"],
  is_builtin: true,
};

const BUILTIN_ADMIN: BuiltinRole = {
  role: "admin",
  label: "Admin",
  description: "Full access except billing",
  permissions: ["roles:manage", "team:manage"],
  is_builtin: true,
};

const EMPTY_ROLES: RoleListResponse = {
  builtin_roles: [BUILTIN_OWNER, BUILTIN_ADMIN],
  custom_roles: [],
};

const CUSTOM_ROLE: CustomRole = {
  id: "custom-1",
  organization_id: "org-1",
  name: "Read-only Analyst",
  description: "Can view and chat",
  base_role: "viewer",
  permissions: ["documents:view", "chat:use"],
  created_by_id: "user-1",
  created_at: "2026-06-08T10:00:00Z",
  updated_at: "2026-06-08T10:00:00Z",
  is_builtin: false,
};

const PERMISSIONS_CATALOG: PermissionCatalogResponse = {
  items: [
    {
      permission: "documents:view",
      category: "documents",
      description: "View documents",
    },
    {
      permission: "chat:use",
      category: "chat",
      description: "Use chat",
    },
    {
      permission: "billing:view",
      category: "billing",
      description: "View billing",
    },
  ],
  total: 3,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminRolesPage />
    </QueryClientProvider>,
  );
}

describe("AdminRolesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPermissions.hasPermission.mockReturnValue(true);
    mockApi.listRoles.mockResolvedValue(EMPTY_ROLES);
    mockApi.listPermissions.mockResolvedValue(PERMISSIONS_CATALOG);
  });

  it("renders loading state initially", () => {
    mockApi.listRoles.mockImplementation(() => new Promise(() => {}));
    mockApi.listPermissions.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders forbidden state when user lacks roles:view", async () => {
    mockPermissions.hasPermission.mockImplementation(
      (p: string) => p !== "roles:view",
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Roles & Permissions/i)).toBeInTheDocument();
      expect(
        screen.getByText(/roles:view permission/i),
      ).toBeInTheDocument();
    });
  });

  it("renders builtin roles", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Owner")).toBeInTheDocument();
      expect(screen.getByText("Admin")).toBeInTheDocument();
    });
  });

  it("shows empty state when no custom roles exist", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/No custom roles yet/i),
      ).toBeInTheDocument();
    });
  });

  it("renders custom roles when they exist", async () => {
    mockApi.listRoles.mockResolvedValue({
      ...EMPTY_ROLES,
      custom_roles: [CUSTOM_ROLE],
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Read-only Analyst")).toBeInTheDocument();
    });
  });

  it("opens create panel when '+ Create role' is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Owner"));
    await user.click(screen.getByRole("button", { name: /Create role/i }));
    expect(screen.getByText("Create Custom Role")).toBeInTheDocument();
  });

  it("calls createCustomRole on form submit", async () => {
    mockApi.createCustomRole.mockResolvedValue({
      ...CUSTOM_ROLE,
      name: "New Role",
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Owner"));

    await user.click(screen.getByRole("button", { name: /Create role/i }));
    await user.type(
      screen.getByPlaceholderText(/e.g. Read-only analyst/i),
      "New Role",
    );
    await user.click(screen.getByRole("button", { name: /Create role/i, hidden: false }));
    await waitFor(() => {
      expect(mockApi.createCustomRole).toHaveBeenCalledWith(
        expect.objectContaining({ name: "New Role" }),
      );
    });
  });

  it("shows delete confirmation dialog", async () => {
    mockApi.listRoles.mockResolvedValue({
      ...EMPTY_ROLES,
      custom_roles: [CUSTOM_ROLE],
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Read-only Analyst"));

    await user.click(screen.getByRole("button", { name: /Delete/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/Delete.*Read-only Analyst/i),
      ).toBeInTheDocument();
    });
  });

  it("calls deleteCustomRole when confirmed", async () => {
    mockApi.deleteCustomRole.mockResolvedValue(undefined);
    mockApi.listRoles
      .mockResolvedValueOnce({ ...EMPTY_ROLES, custom_roles: [CUSTOM_ROLE] })
      .mockResolvedValue(EMPTY_ROLES);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Read-only Analyst"));

    await user.click(screen.getByRole("button", { name: /Delete/i }));
    await waitFor(() => screen.getByRole("dialog"));
    await user.click(screen.getByRole("button", { name: /Delete role/i }));
    await waitFor(() => {
      expect(mockApi.deleteCustomRole).toHaveBeenCalledWith("custom-1");
    });
  });

  it("hides manage buttons when user lacks roles:manage", async () => {
    mockPermissions.hasPermission.mockImplementation(
      (p: string) => p === "roles:view",
    );
    mockApi.listRoles.mockResolvedValue({
      ...EMPTY_ROLES,
      custom_roles: [CUSTOM_ROLE],
    });
    renderPage();
    await waitFor(() => screen.getByText("Read-only Analyst"));
    expect(
      screen.queryByRole("button", { name: /Create role/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit/i }),
    ).not.toBeInTheDocument();
  });

  it("opens builtin role detail view on 'View permissions'", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Owner"));
    const viewButtons = screen.getAllByRole("button", {
      name: /View permissions/i,
    });
    await user.click(viewButtons[0]);
    expect(screen.getByText(/billing:manage/i)).toBeInTheDocument();
  });
});
