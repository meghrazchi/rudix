"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { EmptyState } from "@/components/states/EmptyState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  getTeamCapabilities,
  inviteTeamMember,
  listTeamMembers,
  removeTeamMember,
  setMemberPassword,
  updateTeamMemberRole,
  type TeamMember,
  type TeamInviteRole,
} from "@/lib/api/team";
import {
  listInvitations,
  resendInvitation,
  revokeInvitation,
  deactivateTeamMember,
  type OrganizationInvitation,
} from "@/lib/api/team-invitations";

const PAGE_SIZE = 20;

const inviteSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  name: z.string().trim().max(255).optional(),
  role: z.enum([
    "admin",
    "member",
    "viewer",
    "reviewer",
    "developer",
    "security_admin",
    "billing_admin",
  ]),
});
type InviteValues = z.infer<typeof inviteSchema>;

type ConfirmAction =
  | { kind: "remove"; member: TeamMember }
  | { kind: "deactivate"; member: TeamMember }
  | { kind: "revoke"; invitation: OrganizationInvitation };

function roleBadgeClass(role: string): string {
  if (role === "owner")
    return "inline-flex rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-semibold text-violet-800";
  if (role === "admin")
    return "inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800";
  if (role === "member")
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800";
  if (role === "viewer")
    return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700";
  return "inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800";
}

function statusBadgeClass(s: string): string {
  if (s === "active")
    return "inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800";
  if (s === "invited")
    return "inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800";
  if (s === "disabled" || s === "suspended")
    return "inline-flex rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800";
  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700";
}

function formatDate(v: string | null | undefined): string {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString();
  } catch {
    return v;
  }
}

function InviteDialog({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const form = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", name: "", role: "member" },
  });
  const [apiError, setApiError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: inviteTeamMember,
    onSuccess: () => {
      onSuccess();
    },
    onError: (err) => {
      setApiError(getApiErrorMessage(err));
    },
  });

  async function handleSubmit(values: InviteValues) {
    setApiError(null);
    const trimmedName = values.name?.trim();
    await mutation.mutateAsync({
      email: values.email.trim().toLowerCase(),
      role: values.role as TeamInviteRole,
      ...(trimmedName ? { name: trimmedName } : {}),
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="Invite team member"
      >
        <div className="flex items-center justify-between border-b border-[#ebe8f7] px-6 py-4">
          <h2 className="text-base font-bold text-[#2a2640]">
            Invite team member
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded p-1 text-[#777587] hover:bg-[#f0edf9] hover:text-[#2f2a46]"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
        <form
          onSubmit={form.handleSubmit(handleSubmit)}
          className="space-y-4 p-6"
        >
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Email address
            </label>
            <input
              type="email"
              placeholder="colleague@company.com"
              {...form.register("email")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            {form.formState.errors.email && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.email.message}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Full name{" "}
              <span className="font-normal text-[#999] normal-case">
                (optional)
              </span>
            </label>
            <input
              type="text"
              placeholder="Jane Smith"
              autoComplete="name"
              {...form.register("name")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Role
            </label>
            <select
              {...form.register("role")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd]"
            >
              <option value="admin">Admin</option>
              <option value="member">Member</option>
              <option value="viewer">Viewer</option>
              <option value="reviewer">Reviewer</option>
              <option value="developer">Developer</option>
              <option value="security_admin">Security Admin</option>
              <option value="billing_admin">Billing Admin</option>
            </select>
          </div>
          {apiError && (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
            >
              {apiError}
            </p>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#4b4662] hover:bg-[#f8f6ff]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {mutation.isPending ? "Sending…" : "Send invite"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ConfirmDialog({
  action,
  onConfirm,
  onCancel,
  isPending,
}: {
  action: ConfirmAction;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const isDestructive = action.kind !== "revoke";
  const title =
    action.kind === "remove"
      ? `Remove ${action.member.name || action.member.email}?`
      : action.kind === "deactivate"
        ? `Deactivate ${action.member.name || action.member.email}?`
        : `Revoke invitation for ${action.invitation.email}?`;

  const description =
    action.kind === "remove"
      ? "This will permanently remove this member from your organization and revoke their active sessions."
      : action.kind === "deactivate"
        ? "This will deactivate the member's account and revoke all active sessions. They will not be able to sign in."
        : "The invitation link will no longer be valid.";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-sm rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-xl"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2 className="mb-2 text-base font-bold text-[#2a2640]">{title}</h2>
        <p className="mb-6 text-sm text-[#6b6895]">{description}</p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60 ${
              isDestructive
                ? "bg-rose-600 hover:bg-rose-700"
                : "bg-[#3525cd] hover:bg-[#2b1fa8]"
            }`}
          >
            {isPending
              ? "Working…"
              : action.kind === "remove"
                ? "Remove"
                : action.kind === "deactivate"
                  ? "Deactivate"
                  : "Revoke"}
          </button>
        </div>
      </div>
    </div>
  );
}

const setPasswordSchema = z
  .object({
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });
type SetPasswordValues = z.infer<typeof setPasswordSchema>;

function SetPasswordDialog({
  member,
  onClose,
  onSuccess,
}: {
  member: TeamMember;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const form = useForm<SetPasswordValues>({
    resolver: zodResolver(setPasswordSchema),
    defaultValues: { password: "", confirm: "" },
  });
  const [apiError, setApiError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const mutation = useMutation({
    mutationFn: ({
      memberId,
      password,
    }: {
      memberId: string;
      password: string;
    }) => setMemberPassword(memberId, password),
    onSuccess: () => onSuccess(),
    onError: (err) => setApiError(getApiErrorMessage(err)),
  });

  async function handleSubmit(values: SetPasswordValues) {
    setApiError(null);
    await mutation.mutateAsync({
      memberId: member.member_id,
      password: values.password,
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="Set member password"
      >
        <div className="flex items-center justify-between border-b border-[#ebe8f7] px-6 py-4">
          <div>
            <h2 className="text-base font-bold text-[#2a2640]">Set password</h2>
            <p className="mt-0.5 text-xs text-[#777587]">
              {member.name || member.email}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded p-1 text-[#777587] hover:bg-[#f0edf9] hover:text-[#2f2a46]"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
        <form
          onSubmit={form.handleSubmit(handleSubmit)}
          className="space-y-4 p-6"
        >
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              New password
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                placeholder="Min 8 characters"
                autoComplete="new-password"
                {...form.register("password")}
                className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 pr-10 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute top-1/2 right-2.5 -translate-y-1/2 text-[#999] hover:text-[#555]"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {form.formState.errors.password && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.password.message}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Confirm password
            </label>
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Repeat password"
              autoComplete="new-password"
              {...form.register("confirm")}
              className="h-10 w-full rounded-lg border border-[#d2cee6] px-3 text-sm text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
            {form.formState.errors.confirm && (
              <p role="alert" className="mt-1 text-xs text-rose-700">
                {form.formState.errors.confirm.message}
              </p>
            )}
          </div>
          {apiError && (
            <p
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
            >
              {apiError}
            </p>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#4b4662] hover:bg-[#f8f6ff]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {mutation.isPending ? "Saving…" : "Set password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function RoleChangeRow({
  member,
  isDisabled,
  onRoleChange,
}: {
  member: TeamMember;
  isDisabled: boolean;
  onRoleChange: (memberId: string, role: TeamInviteRole) => void;
}) {
  const [draft, setDraft] = useState<TeamInviteRole>(
    member.role as TeamInviteRole,
  );
  const changed = draft !== member.role;

  useEffect(() => {
    setDraft(member.role as TeamInviteRole);
  }, [member.role]);

  if (member.role === "owner") {
    return <span className={roleBadgeClass(member.role)}>{member.role}</span>;
  }

  return (
    <div className="flex items-center gap-1.5">
      <select
        aria-label={`Role for ${member.email}`}
        disabled={isDisabled}
        value={draft}
        onChange={(e) => setDraft(e.target.value as TeamInviteRole)}
        className="h-7 rounded border border-[#d2cee6] px-1.5 text-xs text-[#2f2a46] disabled:opacity-60"
      >
        <option value="admin">admin</option>
        <option value="member">member</option>
        <option value="viewer">viewer</option>
        <option value="reviewer">reviewer</option>
        <option value="developer">developer</option>
        <option value="security_admin">security_admin</option>
        <option value="billing_admin">billing_admin</option>
      </select>
      {changed && (
        <button
          type="button"
          disabled={isDisabled}
          onClick={() => onRoleChange(member.member_id, draft)}
          className="rounded border border-[#3525cd] px-1.5 py-0.5 text-[11px] font-semibold text-[#3525cd] hover:bg-[#f0edf9] disabled:opacity-60"
        >
          Save
        </button>
      )}
    </div>
  );
}

export function AdminTeamPage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();

  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [showInviteDialog, setShowInviteDialog] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(
    null,
  );
  const [setPasswordMember, setSetPasswordMember] = useState<TeamMember | null>(
    null,
  );
  const [toast, setToast] = useState<{
    tone: "success" | "error";
    message: string;
  } | null>(null);

  const capabilities = useMemo(() => getTeamCapabilities(), []);

  const role = state.session?.role;
  const isAdmin = role === "owner" || role === "admin";

  useEffect(() => {
    const t = setTimeout(() => {
      setSearchQuery(searchInput.trim());
      setPageIndex(0);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const offset = pageIndex * PAGE_SIZE;

  const membersQuery = useQuery({
    queryKey: [
      "admin",
      "team",
      "members",
      PAGE_SIZE,
      offset,
      searchQuery,
      roleFilter,
      statusFilter,
    ],
    queryFn: () =>
      listTeamMembers({
        limit: PAGE_SIZE,
        offset,
        search: searchQuery || undefined,
        ...(roleFilter ? { role: roleFilter } : {}),
        ...(statusFilter ? { status: statusFilter } : {}),
      } as Parameters<typeof listTeamMembers>[0]),
    enabled: isAdmin && capabilities.listMembersEnabled,
    retry: false,
  });

  const invitationsQuery = useQuery({
    queryKey: ["admin", "team", "invitations"],
    queryFn: () => listInvitations({ limit: 100, offset: 0 }),
    enabled: isAdmin,
    retry: false,
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({
      memberId,
      role,
    }: {
      memberId: string;
      role: TeamInviteRole;
    }) => updateTeamMemberRole(memberId, { role }),
    onSuccess: async () => {
      setToast({ tone: "success", message: "Role updated." });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "team", "members"],
      });
    },
    onError: (err) =>
      setToast({ tone: "error", message: getApiErrorMessage(err) }),
  });

  const removeMutation = useMutation({
    mutationFn: (memberId: string) => removeTeamMember(memberId),
    onSuccess: async () => {
      setToast({ tone: "success", message: "Member removed." });
      setConfirmAction(null);
      await queryClient.invalidateQueries({ queryKey: ["admin", "team"] });
    },
    onError: (err) => {
      setToast({ tone: "error", message: getApiErrorMessage(err) });
      setConfirmAction(null);
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (memberId: string) => deactivateTeamMember(memberId),
    onSuccess: async () => {
      setToast({ tone: "success", message: "Member deactivated." });
      setConfirmAction(null);
      await queryClient.invalidateQueries({ queryKey: ["admin", "team"] });
    },
    onError: (err) => {
      setToast({ tone: "error", message: getApiErrorMessage(err) });
      setConfirmAction(null);
    },
  });

  const resendMutation = useMutation({
    mutationFn: (invitationId: string) => resendInvitation(invitationId),
    onSuccess: async () => {
      setToast({ tone: "success", message: "Invitation resent." });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "team", "invitations"],
      });
    },
    onError: (err) =>
      setToast({ tone: "error", message: getApiErrorMessage(err) }),
  });

  const revokeMutation = useMutation({
    mutationFn: (invitationId: string) => revokeInvitation(invitationId),
    onSuccess: async () => {
      setToast({ tone: "success", message: "Invitation revoked." });
      setConfirmAction(null);
      await queryClient.invalidateQueries({ queryKey: ["admin", "team"] });
    },
    onError: (err) => {
      setToast({ tone: "error", message: getApiErrorMessage(err) });
      setConfirmAction(null);
    },
  });

  function handleConfirm() {
    if (!confirmAction) return;
    if (confirmAction.kind === "remove")
      removeMutation.mutate(confirmAction.member.member_id);
    else if (confirmAction.kind === "deactivate")
      deactivateMutation.mutate(confirmAction.member.member_id);
    else if (confirmAction.kind === "revoke")
      revokeMutation.mutate(confirmAction.invitation.invitation_id);
  }

  const isMutating =
    updateRoleMutation.isPending ||
    removeMutation.isPending ||
    deactivateMutation.isPending;

  const members = membersQuery.data?.items ?? [];
  const membersTotal = membersQuery.data?.total ?? 0;
  const hasPrev = offset > 0;
  const hasNext = offset + members.length < membersTotal;

  const invitations = invitationsQuery.data?.items ?? [];

  if (state.status === "loading") {
    return <LoadingState title="Loading team management…" />;
  }

  if (!isAdmin) {
    return (
      <ForbiddenState
        title="Team management restricted"
        description="Team management is only available to organization owners and admins."
        backHref="/dashboard"
        backLabel="Back to dashboard"
      />
    );
  }

  if (membersQuery.error && isForbiddenError(membersQuery.error)) {
    return (
      <ForbiddenState
        title="Access denied"
        description="You do not have permission to manage team members."
        backHref="/dashboard"
        backLabel="Back to dashboard"
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#2a2640]">Team Management</h1>
          <p className="mt-0.5 text-sm text-[#6b6895]">
            Manage members, invitations, and roles for your organization.
          </p>
        </div>
        {capabilities.inviteEnabled && (
          <button
            type="button"
            onClick={() => setShowInviteDialog(true)}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            Invite member
          </button>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={`rounded-lg border px-4 py-2.5 text-sm font-medium ${
            toast.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          {toast.message}
        </div>
      )}

      {/* Members table */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-3 border-b border-[#ebe8f7] px-5 py-4">
          <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
            Members
            {membersTotal > 0 && (
              <span className="ml-1.5 rounded-full bg-[#f0edf9] px-2 py-0.5 text-xs font-semibold text-[#5a5278]">
                {membersTotal}
              </span>
            )}
          </h2>

          {/* Search */}
          <div className="relative ml-auto">
            <svg
              className="absolute top-1/2 left-2.5 -translate-y-1/2 text-[#999]"
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search name or email…"
              aria-label="Search members"
              className="h-8 w-52 rounded-lg border border-[#d2cee6] bg-white pr-3 pl-7 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
            />
          </div>

          {/* Role filter */}
          <select
            aria-label="Filter by role"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPageIndex(0);
            }}
            className="h-8 rounded-lg border border-[#d2cee6] px-2 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd]"
          >
            <option value="">All roles</option>
            <option value="owner">Owner</option>
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
            <option value="reviewer">Reviewer</option>
            <option value="developer">Developer</option>
          </select>

          {/* Status filter */}
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPageIndex(0);
            }}
            className="h-8 rounded-lg border border-[#d2cee6] px-2 text-xs text-[#2f2a46] outline-none focus:border-[#3525cd]"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="invited">Invited</option>
          </select>
        </div>

        {membersQuery.isLoading ? (
          <div className="p-8">
            <LoadingState compact title="Loading members…" />
          </div>
        ) : membersQuery.isError ? (
          <div className="p-6">
            <ErrorState
              compact
              error={membersQuery.error}
              description={getApiErrorMessage(membersQuery.error)}
              onRetry={() => void membersQuery.refetch()}
            />
          </div>
        ) : members.length === 0 ? (
          <div className="p-8">
            <EmptyState
              compact
              title={
                searchQuery
                  ? `No members match "${searchQuery}"`
                  : "No members found"
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-[#f0edf9] text-sm">
              <thead className="bg-[#faf9ff]">
                <tr>
                  {["Name", "Email", "Role", "Status", "Joined", "Actions"].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-2.5 text-left text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f8f6ff] bg-white">
                {members.map((member) => (
                  <tr key={member.member_id} className="hover:bg-[#fdfcff]">
                    <td className="px-4 py-3 font-medium text-[#2f2a46]">
                      {member.name}
                    </td>
                    <td className="px-4 py-3 text-[#4d4963]">{member.email}</td>
                    <td className="px-4 py-3">
                      <RoleChangeRow
                        member={member}
                        isDisabled={
                          isMutating || !capabilities.updateRoleEnabled
                        }
                        onRoleChange={(memberId, role) =>
                          updateRoleMutation.mutate({ memberId, role })
                        }
                      />
                    </td>
                    <td className="px-4 py-3">
                      <span className={statusBadgeClass(member.status)}>
                        {member.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[#7a7690]">
                      {formatDate(member.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          disabled={isMutating}
                          onClick={() => setSetPasswordMember(member)}
                          className="rounded border border-[#d2cee6] px-2 py-0.5 text-[11px] font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
                        >
                          Set password
                        </button>
                        {member.role !== "owner" && (
                          <>
                            <button
                              type="button"
                              disabled={isMutating}
                              onClick={() =>
                                setConfirmAction({ kind: "deactivate", member })
                              }
                              className="rounded border border-amber-300 px-2 py-0.5 text-[11px] font-semibold text-amber-700 hover:bg-amber-50 disabled:opacity-60"
                            >
                              Deactivate
                            </button>
                            <button
                              type="button"
                              disabled={
                                isMutating || !capabilities.removeMemberEnabled
                              }
                              onClick={() =>
                                setConfirmAction({ kind: "remove", member })
                              }
                              className="rounded border border-rose-300 px-2 py-0.5 text-[11px] font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                            >
                              Remove
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {membersTotal > 0 && (
          <div className="flex items-center justify-between border-t border-[#ebe8f7] bg-[#fcfbff] px-5 py-2.5">
            <p className="text-xs text-[#6a6780]">
              {offset + 1}–{Math.min(offset + members.length, membersTotal)} of{" "}
              {membersTotal}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
                disabled={!hasPrev || membersQuery.isFetching}
                className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => setPageIndex((p) => p + 1)}
                disabled={!hasNext || membersQuery.isFetching}
                className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#4b4662] hover:bg-[#f8f6ff] disabled:opacity-60"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Pending Invitations */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="border-b border-[#ebe8f7] px-5 py-4">
          <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
            Pending Invitations
            {invitations.length > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                {invitations.length}
              </span>
            )}
          </h2>
        </div>

        {invitationsQuery.isLoading ? (
          <div className="p-6">
            <LoadingState compact title="Loading invitations…" />
          </div>
        ) : invitationsQuery.isError ? (
          <div className="p-6">
            <ErrorState
              compact
              error={invitationsQuery.error}
              description={getApiErrorMessage(invitationsQuery.error)}
              onRetry={() => void invitationsQuery.refetch()}
            />
          </div>
        ) : invitations.length === 0 ? (
          <div className="p-8">
            <EmptyState compact title="No pending invitations" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-[#f0edf9] text-sm">
              <thead className="bg-[#faf9ff]">
                <tr>
                  {[
                    "Email",
                    "Role",
                    "Invited by",
                    "Expires",
                    "Sent",
                    "Actions",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 text-left text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f8f6ff] bg-white">
                {invitations.map((inv) => (
                  <tr key={inv.invitation_id} className="hover:bg-[#fdfcff]">
                    <td className="px-4 py-3 text-[#2f2a46]">{inv.email}</td>
                    <td className="px-4 py-3">
                      <span className={roleBadgeClass(inv.role)}>
                        {inv.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[#7a7690]">
                      {inv.invited_by_name ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-[#7a7690]">
                      {formatDate(inv.expires_at)}
                    </td>
                    <td className="px-4 py-3 text-[#7a7690]">
                      {inv.resend_count > 0 ? `${inv.resend_count + 1}×` : "1×"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          disabled={resendMutation.isPending}
                          onClick={() =>
                            resendMutation.mutate(inv.invitation_id)
                          }
                          className="rounded border border-[#d2cee6] px-2 py-0.5 text-[11px] font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
                        >
                          Resend
                        </button>
                        <button
                          type="button"
                          disabled={revokeMutation.isPending}
                          onClick={() =>
                            setConfirmAction({
                              kind: "revoke",
                              invitation: inv,
                            })
                          }
                          className="rounded border border-rose-300 px-2 py-0.5 text-[11px] font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                        >
                          Revoke
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Modals */}
      {showInviteDialog && (
        <InviteDialog
          onClose={() => setShowInviteDialog(false)}
          onSuccess={() => {
            setShowInviteDialog(false);
            setToast({ tone: "success", message: "Invitation sent." });
            void queryClient.invalidateQueries({ queryKey: ["admin", "team"] });
          }}
        />
      )}

      {confirmAction && (
        <ConfirmDialog
          action={confirmAction}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
          isPending={
            removeMutation.isPending ||
            deactivateMutation.isPending ||
            revokeMutation.isPending
          }
        />
      )}

      {setPasswordMember && (
        <SetPasswordDialog
          member={setPasswordMember}
          onClose={() => setSetPasswordMember(null)}
          onSuccess={() => {
            setSetPasswordMember(null);
            setToast({ tone: "success", message: "Password updated." });
          }}
        />
      )}
    </div>
  );
}
