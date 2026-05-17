"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getTeamCapabilities,
  inviteTeamMember,
  isTeamEndpointUnavailableError,
  listTeamMembers,
  removeTeamMember,
  updateTeamMemberRole,
  type TeamInviteRole,
  type TeamMember,
} from "@/lib/api/team";
import type { AppRole } from "@/lib/auth-session";

type TeamManagementSectionProps = {
  role: AppRole | null | undefined;
};

type TeamSaveState = {
  tone: "neutral" | "success" | "error";
  message: string;
} | null;

const TEAM_MEMBERS_PAGE_SIZE = 10;

const teamInviteSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Invite email is required.")
    .email("Enter a valid email."),
  role: z.enum(["admin", "member", "viewer"]),
});

type TeamInviteValues = z.infer<typeof teamInviteSchema>;

function isAdminLikeRole(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function formatDate(value: string | null): string {
  if (!value) {
    return "N/A";
  }
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function roleBadge(role: AppRole): string {
  if (role === "owner") {
    return "inline-flex rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-800";
  }
  if (role === "admin") {
    return "inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800";
  }
  if (role === "member") {
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800";
  }
  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700";
}

function statusBadge(status: TeamMember["status"]): string {
  if (status === "active") {
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800";
  }
  if (status === "invited") {
    return "inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800";
  }
  if (status === "disabled" || status === "suspended") {
    return "inline-flex rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-800";
  }
  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700";
}

function saveStateClass(saveState: TeamSaveState): string {
  if (!saveState || saveState.tone === "neutral") {
    return "rounded-lg border border-[#e0dced] bg-[#faf8ff] px-3 py-2 text-sm text-[#4d4963]";
  }
  if (saveState.tone === "success") {
    return "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800";
  }
  return "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
}

export function TeamManagementSection({ role }: TeamManagementSectionProps) {
  const isAdmin = isAdminLikeRole(role);
  const capabilities = useMemo(() => getTeamCapabilities(), []);
  const [saveState, setSaveState] = useState<TeamSaveState>(null);
  const [roleDraftByMemberId, setRoleDraftByMemberId] = useState<Record<string, TeamInviteRole>>({});
  const [memberPageIndex, setMemberPageIndex] = useState(0);
  const memberOffset = memberPageIndex * TEAM_MEMBERS_PAGE_SIZE;

  const inviteForm = useForm<TeamInviteValues>({
    resolver: zodResolver(teamInviteSchema),
    defaultValues: {
      email: "",
      role: "member",
    },
    mode: "onSubmit",
  });

  const membersQuery = useQuery({
    queryKey: ["team", "members", TEAM_MEMBERS_PAGE_SIZE, memberOffset],
    queryFn: () =>
      listTeamMembers({
        limit: TEAM_MEMBERS_PAGE_SIZE,
        offset: memberOffset,
      }),
    enabled: isAdmin && capabilities.listMembersEnabled,
    retry: false,
  });

  const inviteMutation = useMutation({
    mutationFn: inviteTeamMember,
    onSuccess: async () => {
      setSaveState({
        tone: "success",
        message: "Invite sent successfully.",
      });
      inviteForm.reset({
        email: "",
        role: "member",
      });
      await membersQuery.refetch();
    },
    onError: (error) => {
      setSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  const updateRoleMutation = useMutation({
    mutationFn: (params: { memberId: string; role: TeamInviteRole }) =>
      updateTeamMemberRole(params.memberId, { role: params.role }),
    onSuccess: async () => {
      setSaveState({
        tone: "success",
        message: "Member role updated.",
      });
      await membersQuery.refetch();
    },
    onError: (error) => {
      setSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: (memberId: string) => removeTeamMember(memberId),
    onSuccess: async () => {
      setSaveState({
        tone: "success",
        message: "Member removed from organization.",
      });
      await membersQuery.refetch();
    },
    onError: (error) => {
      setSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  function resolveDraftRole(member: TeamMember): TeamInviteRole {
    if (member.role === "owner") {
      return "admin";
    }
    return roleDraftByMemberId[member.member_id] ?? member.role;
  }

  function canUpdateRole(member: TeamMember): boolean {
    return capabilities.updateRoleEnabled && member.role !== "owner";
  }

  function canRemoveMember(member: TeamMember): boolean {
    return capabilities.removeMemberEnabled && member.role !== "owner";
  }

  async function handleInvite(values: TeamInviteValues): Promise<void> {
    setSaveState(null);
    await inviteMutation.mutateAsync({
      email: values.email.trim().toLowerCase(),
      role: values.role,
    });
  }

  if (!isAdmin) {
    return (
      <section
        className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
        aria-label="Team management section"
      >
        <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          Team management
        </h2>
        <ForbiddenState
          compact
          title="Team management restricted"
          description="Member management actions are only available to owner/admin roles."
          backHref="/dashboard"
          backLabel="Back to dashboard"
        />
      </section>
    );
  }

  const members = membersQuery.data?.items ?? [];
  const membersTotal = membersQuery.data?.total ?? members.length;
  const hasPreviousMembersPage = memberOffset > 0;
  const hasNextMembersPage = memberOffset + members.length < membersTotal;
  const membersRangeStart = membersTotal === 0 ? 0 : memberOffset + 1;
  const membersRangeEnd = membersTotal === 0 ? 0 : memberOffset + members.length;

  useEffect(() => {
    if (membersQuery.isFetching) {
      return;
    }
    if (membersTotal > 0 && members.length === 0 && memberPageIndex > 0) {
      setMemberPageIndex((previous) => Math.max(0, previous - 1));
    }
  }, [memberPageIndex, members.length, membersQuery.isFetching, membersTotal]);

  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
      aria-label="Team management section"
    >
      <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
        Team management
      </h2>
      <p className="mb-4 text-sm text-[#4d4963]">
        Review organization members, send invites, and manage roles for active users.
      </p>

      {!capabilities.listMembersEnabled ? (
        <EmptyState
          compact
          className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          title="Member list endpoint is not configured for this deployment."
        />
      ) : membersQuery.isLoading ? (
        <LoadingState compact className="mb-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]" title="Loading team members..." />
      ) : membersQuery.isError ? (
        <div className="mb-4">
          <ErrorState
            compact
            error={membersQuery.error}
            description={getApiErrorMessage(membersQuery.error)}
            onRetry={() => {
              void membersQuery.refetch();
            }}
          />
        </div>
      ) : members.length === 0 ? (
        <EmptyState
          compact
          className="mb-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
          title="No members are currently available for this organization."
        />
      ) : (
        <div className="mb-4 overflow-x-auto rounded-lg border border-[#ebe8f7]">
          <table className="min-w-full divide-y divide-[#ebe8f7] bg-white text-sm">
            <thead className="bg-[#faf9ff]">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Name</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Email</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Role</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Status</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Updated</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f0edf9]">
              {members.map((member) => {
                const draftRole = resolveDraftRole(member);
                const roleChanged = member.role !== "owner" && draftRole !== member.role;
                const isRowBusy =
                  updateRoleMutation.isPending || removeMemberMutation.isPending;
                return (
                  <tr key={member.member_id} className="bg-white">
                    <td className="px-3 py-2 text-[#2f2a46]">{member.name}</td>
                    <td className="px-3 py-2 text-[#2f2a46]">{member.email}</td>
                    <td className="px-3 py-2">
                      <span className={roleBadge(member.role)}>{member.role}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={statusBadge(member.status)}>{member.status}</span>
                    </td>
                    <td className="px-3 py-2 text-[#4f4b63]">{formatDate(member.updated_at)}</td>
                    <td className="px-3 py-2">
                      <div className="flex min-w-[260px] flex-wrap items-center gap-2">
                        <select
                          aria-label={`Role for ${member.email}`}
                          disabled={!canUpdateRole(member) || isRowBusy}
                          value={draftRole}
                          onChange={(event) => {
                            setRoleDraftByMemberId((previous) => ({
                              ...previous,
                              [member.member_id]: event.target.value as TeamInviteRole,
                            }));
                          }}
                          className="h-8 rounded border border-[#d2cee6] px-2 text-xs text-[#2f2a46] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <option value="admin">admin</option>
                          <option value="member">member</option>
                          <option value="viewer">viewer</option>
                        </select>
                        <button
                          type="button"
                          disabled={!canUpdateRole(member) || !roleChanged || isRowBusy}
                          onClick={() => {
                            setSaveState(null);
                            updateRoleMutation.mutate({
                              memberId: member.member_id,
                              role: draftRole,
                            });
                          }}
                          className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Change role
                        </button>
                        <button
                          type="button"
                          disabled={!canRemoveMember(member) || isRowBusy}
                          onClick={() => {
                            const confirmed = window.confirm(
                              `Remove ${member.email} from this organization?`,
                            );
                            if (!confirmed) {
                              return;
                            }
                            setSaveState(null);
                            removeMemberMutation.mutate(member.member_id);
                          }}
                          className="rounded border border-rose-300 px-2 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-[#ebe8f7] bg-[#fcfbff] px-3 py-2">
            <p className="text-xs text-[#6a6780]">
              Showing {membersRangeStart}-{membersRangeEnd} of {membersTotal}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setMemberPageIndex((previous) => Math.max(0, previous - 1));
                }}
                disabled={!hasPreviousMembersPage || membersQuery.isFetching}
                className="rounded border border-[#d2cee6] bg-white px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => {
                  setMemberPageIndex((previous) => previous + 1);
                }}
                disabled={!hasNextMembersPage || membersQuery.isFetching}
                className="rounded border border-[#d2cee6] bg-white px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-[#ebe8f7] bg-[#faf9ff] p-3">
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-[#5f5a74]">
          Invite member
        </h3>
        {!capabilities.inviteEnabled ? (
          <p className="text-sm text-[#68647b]">
            Invite endpoint is not configured. Enable it to send organization invites.
          </p>
        ) : (
          <form onSubmit={inviteForm.handleSubmit(handleInvite)} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_140px_auto]">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Invite email
              </span>
              <input
                type="email"
                placeholder="teammate@company.com"
                {...inviteForm.register("email")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm ring-[#3525cd]/20 outline-none focus:ring"
              />
              {inviteForm.formState.errors.email?.message ? (
                <p role="alert" className="mt-1 text-xs text-rose-700">
                  {inviteForm.formState.errors.email.message}
                </p>
              ) : null}
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                Role
              </span>
              <select
                {...inviteForm.register("role")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46]"
              >
                <option value="admin">admin</option>
                <option value="member">member</option>
                <option value="viewer">viewer</option>
              </select>
            </label>

            <div className="flex items-end">
              <button
                type="submit"
                disabled={inviteMutation.isPending}
                className="h-10 rounded-lg bg-[#3525cd] px-4 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {inviteMutation.isPending ? "Sending..." : "Send invite"}
              </button>
            </div>
          </form>
        )}
      </div>

      {saveState ? <p className={`mt-4 ${saveStateClass(saveState)}`}>{saveState.message}</p> : null}

      {(isTeamEndpointUnavailableError(membersQuery.error) ||
        isTeamEndpointUnavailableError(inviteMutation.error) ||
        isTeamEndpointUnavailableError(updateRoleMutation.error) ||
        isTeamEndpointUnavailableError(removeMemberMutation.error)) ? (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Some team management actions are unavailable until membership endpoints are configured.
        </p>
      ) : null}
    </section>
  );
}
