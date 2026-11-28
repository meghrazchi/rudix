"use client";

import { queryKeys } from "@/lib/api/query";
import { InviteDialog } from "@/components/admin/team/InviteDialog";
import { ConfirmDialog } from "@/components/admin/team/ConfirmDialog";
import { SetPasswordDialog } from "@/components/admin/team/SetPasswordDialog";
import { useTeamController } from "@/components/admin/team/useTeamController";

export function TeamModals({
  ctl,
}: {
  ctl: ReturnType<typeof useTeamController>;
}) {
  const {
    t,
    queryClient,
    showInviteDialog,
    setShowInviteDialog,
    confirmAction,
    setConfirmAction,
    setPasswordMember,
    setSetPasswordMember,
    setToast,
    removeMutation,
    deactivateMutation,
    revokeMutation,
    handleConfirm,
  } = ctl;

  return (
    <>
      {showInviteDialog && (
        <InviteDialog
          onClose={() => setShowInviteDialog(false)}
          onSuccess={() => {
            setShowInviteDialog(false);
            setToast({ tone: "success", message: t("toasts.inviteSent") });
            void queryClient.invalidateQueries({
              queryKey: queryKeys.adminTeam.all,
            });
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
            setToast({ tone: "success", message: t("toasts.passwordUpdated") });
          }}
        />
      )}
    </>
  );
}
