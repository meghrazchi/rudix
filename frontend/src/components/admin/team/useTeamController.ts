import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  getTeamCapabilities,
  listTeamMembers,
  removeTeamMember,
  updateTeamMemberRole,
  type TeamMember,
  type TeamInviteRole,
} from "@/lib/api/team";
import {
  listInvitations,
  resendInvitation,
  revokeInvitation,
  deactivateTeamMember,
} from "@/lib/api/team-invitations";
import {
  PAGE_SIZE,
  type ConfirmAction,
} from "@/components/admin/team/teamShared";
import { queryKeys } from "@/lib/api/query";

export function useTeamController() {
  const t = useTranslations("adminTeam");
  const locale = useLocale();
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
    queryKey: queryKeys.adminTeam.members(
      PAGE_SIZE,
      offset,
      searchQuery,
      roleFilter,
      statusFilter,
    ),
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
    queryKey: queryKeys.adminTeam.invitations,
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
      setToast({ tone: "success", message: t("toasts.roleUpdated") });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.adminTeam.membersAll,
      });
    },
    onError: (err) =>
      setToast({ tone: "error", message: getApiErrorMessage(err) }),
  });

  const removeMutation = useMutation({
    mutationFn: (memberId: string) => removeTeamMember(memberId),
    onSuccess: async () => {
      setToast({ tone: "success", message: t("toasts.memberRemoved") });
      setConfirmAction(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.adminTeam.all,
      });
    },
    onError: (err) => {
      setToast({ tone: "error", message: getApiErrorMessage(err) });
      setConfirmAction(null);
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (memberId: string) => deactivateTeamMember(memberId),
    onSuccess: async () => {
      setToast({ tone: "success", message: t("toasts.memberDeactivated") });
      setConfirmAction(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.adminTeam.all,
      });
    },
    onError: (err) => {
      setToast({ tone: "error", message: getApiErrorMessage(err) });
      setConfirmAction(null);
    },
  });

  const resendMutation = useMutation({
    mutationFn: (invitationId: string) => resendInvitation(invitationId),
    onSuccess: async () => {
      setToast({ tone: "success", message: t("toasts.inviteResent") });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.adminTeam.invitations,
      });
    },
    onError: (err) =>
      setToast({ tone: "error", message: getApiErrorMessage(err) }),
  });

  const revokeMutation = useMutation({
    mutationFn: (invitationId: string) => revokeInvitation(invitationId),
    onSuccess: async () => {
      setToast({ tone: "success", message: t("toasts.inviteRevoked") });
      setConfirmAction(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.adminTeam.all,
      });
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
  return {
    t,
    locale,
    state,
    queryClient,
    searchInput,
    setSearchInput,
    searchQuery,
    setSearchQuery,
    roleFilter,
    setRoleFilter,
    statusFilter,
    setStatusFilter,
    pageIndex,
    setPageIndex,
    showInviteDialog,
    setShowInviteDialog,
    confirmAction,
    setConfirmAction,
    setPasswordMember,
    setSetPasswordMember,
    toast,
    setToast,
    capabilities,
    role,
    isAdmin,
    offset,
    membersQuery,
    invitationsQuery,
    updateRoleMutation,
    removeMutation,
    deactivateMutation,
    resendMutation,
    revokeMutation,
    handleConfirm,
    isMutating,
    members,
    membersTotal,
    hasPrev,
    hasNext,
    invitations,
  };
}
