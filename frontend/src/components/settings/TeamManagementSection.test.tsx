import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamManagementSection } from "@/components/settings/TeamManagementSection";
import type { AppRole } from "@/lib/auth-session";
import type { TeamMember, TeamCapabilities } from "@/lib/api/team";

const mockTeamApi = vi.hoisted(() => ({
  capabilities: {
    listMembersEnabled: true,
    inviteEnabled: true,
    updateRoleEnabled: true,
    removeMemberEnabled: true,
  } as TeamCapabilities,
  listTeamMembers: vi.fn(),
  inviteTeamMember: vi.fn(),
  updateTeamMemberRole: vi.fn(),
  removeTeamMember: vi.fn(),
}));

vi.mock("@/lib/api/team", () => ({
  getTeamCapabilities: () => mockTeamApi.capabilities,
  listTeamMembers: (...args: unknown[]) => mockTeamApi.listTeamMembers(...args),
  inviteTeamMember: (...args: unknown[]) =>
    mockTeamApi.inviteTeamMember(...args),
  updateTeamMemberRole: (...args: unknown[]) =>
    mockTeamApi.updateTeamMemberRole(...args),
  removeTeamMember: (...args: unknown[]) =>
    mockTeamApi.removeTeamMember(...args),
  isTeamEndpointUnavailableError: () => false,
}));

function renderSection(role: AppRole | null) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TeamManagementSection role={role} />
    </QueryClientProvider>,
  );
}

function buildMember(overrides: Partial<TeamMember> = {}): TeamMember {
  return {
    member_id: "member-1",
    user_id: "user-1",
    name: "Admin User",
    email: "admin@example.com",
    role: "admin",
    status: "active",
    created_at: "2026-05-16T10:00:00Z",
    updated_at: "2026-05-16T10:00:00Z",
    ...overrides,
  };
}

describe("TeamManagementSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTeamApi.capabilities = {
      listMembersEnabled: true,
      inviteEnabled: true,
      updateRoleEnabled: true,
      removeMemberEnabled: true,
    };
    mockTeamApi.listTeamMembers.mockResolvedValue({
      items: [buildMember()],
      total: 1,
      limit: 50,
      offset: 0,
    });
    mockTeamApi.inviteTeamMember.mockResolvedValue({
      member: buildMember({
        member_id: "member-2",
        email: "teammate@example.com",
        role: "member",
      }),
      invited: true,
    });
    mockTeamApi.updateTeamMemberRole.mockResolvedValue(
      buildMember({ role: "viewer" }),
    );
    mockTeamApi.removeTeamMember.mockResolvedValue({ removed: true });
  });

  it("hides member-management actions for non-admin roles", async () => {
    renderSection("member");

    expect(
      await screen.findByText("Team management restricted"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Send invite" }),
    ).not.toBeInTheDocument();
    expect(mockTeamApi.listTeamMembers).not.toHaveBeenCalled();
  });

  it("validates invite email before submission", async () => {
    renderSection("admin");
    await screen.findByText("Admin User");

    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(mockTeamApi.inviteTeamMember).not.toHaveBeenCalled();
  });

  it("marks unavailable actions clearly when endpoints are not configured", async () => {
    mockTeamApi.capabilities = {
      listMembersEnabled: true,
      inviteEnabled: false,
      updateRoleEnabled: false,
      removeMemberEnabled: false,
    };

    renderSection("owner");
    await screen.findByText("Admin User");

    expect(
      screen.getByText(
        "Invite endpoint is not configured. Enable it to send organization invites.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Role for admin@example.com" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Change role" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove" })).toBeDisabled();
  });

  it("invites a member for owner/admin users", async () => {
    renderSection("admin");
    await screen.findByText("Admin User");

    await userEvent.type(
      screen.getByPlaceholderText("teammate@company.com"),
      "teammate@example.com",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Role" }),
      "viewer",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() => {
      expect(mockTeamApi.inviteTeamMember).toHaveBeenCalled();
    });
    expect(mockTeamApi.inviteTeamMember.mock.calls[0]?.[0]).toEqual({
      email: "teammate@example.com",
      role: "viewer",
    });
    expect(
      await screen.findByText("Invite sent successfully."),
    ).toBeInTheDocument();
  });

  it("loads paginated members and switches pages", async () => {
    mockTeamApi.listTeamMembers.mockImplementation(
      async (params?: { limit?: number; offset?: number }) => {
        const limit = params?.limit ?? 10;
        const offset = params?.offset ?? 0;
        if (offset === 0) {
          return {
            items: [
              buildMember({
                member_id: "member-1",
                name: "Page One Member",
                email: "page1@example.com",
              }),
            ],
            total: 11,
            limit,
            offset,
          };
        }
        return {
          items: [
            buildMember({
              member_id: "member-11",
              name: "Page Two Member",
              email: "page2@example.com",
            }),
          ],
          total: 11,
          limit,
          offset,
        };
      },
    );

    renderSection("admin");
    expect(await screen.findByText("Page One Member")).toBeInTheDocument();
    expect(screen.getByText("Showing 1-1 of 11")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Page Two Member")).toBeInTheDocument();
    expect(screen.getByText("Showing 11-11 of 11")).toBeInTheDocument();
    expect(mockTeamApi.listTeamMembers).toHaveBeenCalledWith({
      limit: 10,
      offset: 10,
    });
  });
});
