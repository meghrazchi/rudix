import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPermissionsAccessPage } from "@/components/admin/AdminPermissionsAccessPage";
import type {
  PermissionsAccessCharts,
  PermissionsAccessRowList,
  PermissionsAccessSummary,
} from "@/lib/schemas/permissions-access";

const mockPermissions = vi.hoisted(() => ({
  hasPermission: vi.fn((_p: string) => true),
}));

const mockApi = vi.hoisted(() => ({
  getPermissionsAccessSummary: vi.fn(),
  getPermissionsAccessCharts: vi.fn(),
  listPermissionsAccessRows: vi.fn(),
  exportPermissionsAccessReport: vi.fn(),
}));

const mockPermissionsApi = vi.hoisted(() => ({
  revokeResourceGrant: vi.fn(),
}));

const mockConflictsApi = vi.hoisted(() => ({
  updateConflictStatus: vi.fn(),
}));

vi.mock("@/lib/use-permissions", () => ({
  usePermissions: () => mockPermissions,
}));

vi.mock("@/lib/api/permissions-access", () => ({
  getPermissionsAccessSummary: (...args: unknown[]) =>
    mockApi.getPermissionsAccessSummary(...args),
  getPermissionsAccessCharts: (...args: unknown[]) =>
    mockApi.getPermissionsAccessCharts(...args),
  listPermissionsAccessRows: (...args: unknown[]) =>
    mockApi.listPermissionsAccessRows(...args),
  exportPermissionsAccessReport: (...args: unknown[]) =>
    mockApi.exportPermissionsAccessReport(...args),
}));

vi.mock("@/lib/api/permissions", () => ({
  revokeResourceGrant: (...args: unknown[]) =>
    mockPermissionsApi.revokeResourceGrant(...args),
}));

vi.mock("@/lib/api/conflicts", () => ({
  updateConflictStatus: (...args: unknown[]) =>
    mockConflictsApi.updateConflictStatus(...args),
}));

const SUMMARY: PermissionsAccessSummary = {
  total_users: 42,
  admin_users: 3,
  external_users: 5,
  external_users_is_heuristic: false,
  broad_access_users: 2,
  permission_conflicts_open: 4,
  orphaned_grants: 1,
  expired_active_grants: 6,
  connector_acl_mismatches: 2,
  resources_without_owner: 7,
  unauthorized_access_attempts: 9,
  generated_at: "2026-08-30T00:00:00Z",
};

const CHARTS: PermissionsAccessCharts = {
  users_by_role: [{ role: "member", count: 30 }],
  access_distribution: [{ access_source: "explicit_grant", count: 12 }],
  conflicts_by_resource_type: [{ resource_type: "document", count: 4 }],
  broad_access_users: [
    {
      user_id: "00000000-0000-0000-0000-000000000001",
      name: "Ada Lovelace",
      email: "ada@example.com",
      role: "member",
      reason: "Holds a grant scoped to an entire resource type",
    },
  ],
  failed_access_attempts: [{ date: "2026-08-29", count: 3 }],
  generated_at: "2026-08-30T00:00:00Z",
};

function makeRow(
  overrides: Partial<PermissionsAccessRowList["items"][number]> = {},
) {
  return {
    id: "row-1",
    user_id: "00000000-0000-0000-0000-000000000001",
    user_name: "Grace Hopper",
    user_email: "grace@example.com",
    role: "member",
    team: null,
    resource_id: "11111111-0000-0000-0000-000000000001",
    resource_type: "document",
    resource_label: "policy.pdf",
    access_level: "read_only",
    access_source: "explicit_grant",
    conflict_status: null,
    last_access: null,
    grant_id: "grant-1",
    conflict_id: null,
    ...overrides,
  };
}

function listResponse(
  items: PermissionsAccessRowList["items"],
): PermissionsAccessRowList {
  return { items, total: items.length, page: 1, page_size: 25 };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminPermissionsAccessPage />
    </QueryClientProvider>,
  );
}

describe("AdminPermissionsAccessPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPermissions.hasPermission.mockImplementation(() => true);
    mockApi.getPermissionsAccessSummary.mockResolvedValue(SUMMARY);
    mockApi.getPermissionsAccessCharts.mockResolvedValue(CHARTS);
    mockApi.listPermissionsAccessRows.mockResolvedValue(
      listResponse([makeRow()]),
    );
  });

  it("shows a forbidden state and makes no requests without security_center:view", () => {
    mockPermissions.hasPermission.mockReturnValue(false);
    renderPage();
    expect(screen.getByText(/admin access restricted/i)).toBeInTheDocument();
    expect(mockApi.getPermissionsAccessSummary).not.toHaveBeenCalled();
  });

  it("renders summary metric cards with values from the API", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Total users")).toBeInTheDocument();
    });
    function cardValue(label: string): string | null {
      const labelEl = screen.getAllByText(label)[0];
      return (
        labelEl.closest("div")?.querySelector("p:last-child")?.textContent ??
        null
      );
    }
    expect(cardValue("Total users")).toBe("42");
    expect(cardValue("Permission conflicts")).toBe("4");
    expect(cardValue("Unauthorized access attempts")).toBe("9");
  });

  it("renders chart titles and the broad access users list", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Users by role" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", { name: "Broad access users" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(
      screen.getByText("Holds a grant scoped to an entire resource type"),
    ).toBeInTheDocument();
  });

  it("shows the access row with resource label and access source", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("policy.pdf")).toBeInTheDocument();
    expect(within(table).getByText("Explicit grant")).toBeInTheDocument();
  });

  it("hides the export button when the user lacks security_center:configure", async () => {
    mockPermissions.hasPermission.mockImplementation(
      (p: string) => p === "security_center:view",
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Total users")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Export" }),
    ).not.toBeInTheDocument();
  });

  it("shows the export button and triggers export when configure is granted", async () => {
    mockApi.exportPermissionsAccessReport.mockResolvedValue(
      new Blob(["csv"], { type: "text/csv" }),
    );
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Export" }),
      ).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() =>
      expect(mockApi.exportPermissionsAccessReport).toHaveBeenCalled(),
    );
  });

  it("only renders 'Remove broad access' when the row carries a grant_id", async () => {
    mockApi.listPermissionsAccessRows.mockResolvedValue(
      listResponse([makeRow({ grant_id: null })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Remove broad access" }),
    ).not.toBeInTheDocument();
  });

  it("removes broad access when the action button is clicked", async () => {
    mockPermissionsApi.revokeResourceGrant.mockResolvedValue(undefined);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Remove broad access" }),
      ).toBeInTheDocument();
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Remove broad access" }),
    );
    await waitFor(() =>
      expect(mockPermissionsApi.revokeResourceGrant).toHaveBeenCalledWith(
        "grant-1",
      ),
    );
  });

  it("only renders 'Fix conflict' when the row carries a conflict_id", async () => {
    mockApi.listPermissionsAccessRows.mockResolvedValue(
      listResponse([
        makeRow({
          conflict_id: "conflict-1",
          conflict_status: "open",
          grant_id: null,
        }),
      ]),
    );
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Fix conflict" }),
      ).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: "Fix conflict" }));
    await waitFor(() =>
      expect(mockConflictsApi.updateConflictStatus).toHaveBeenCalledWith(
        "conflict-1",
        { status: "investigating" },
      ),
    );
  });

  it("links 'Open access debugger' to a prefilled debugger URL", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: "Open access debugger" }),
      ).toBeInTheDocument();
    });
    const link = screen.getByRole("link", {
      name: "Open access debugger",
    }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain(
      "user=00000000-0000-0000-0000-000000000001",
    );
    expect(link.getAttribute("href")).toContain("resource_type=document");
    expect(link.getAttribute("href")).toContain(
      "resource=11111111-0000-0000-0000-000000000001",
    );
  });
});
