"use client";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { EmptyState } from "@/components/states/EmptyState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { roleBadgeClass, formatDate } from "@/components/admin/team/teamShared";
import { useTeamController } from "@/components/admin/team/useTeamController";

export function InvitationsSection({
  ctl,
}: {
  ctl: ReturnType<typeof useTeamController>;
}) {
  const {
    t,
    locale,
    setConfirmAction,
    invitationsQuery,
    resendMutation,
    revokeMutation,
    invitations,
  } = ctl;

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
      <div className="border-b border-[#ebe8f7] px-5 py-4">
        <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          {t("pendingInvitations")}
          {invitations.length > 0 && (
            <span className="ml-1.5 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
              {invitations.length}
            </span>
          )}
        </h2>
      </div>

      {invitationsQuery.isLoading ? (
        <div className="p-6">
          <LoadingState compact title={t("loading.invitations")} />
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
          <EmptyState compact title={t("empty.invitations")} />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-[#f0edf9] text-sm">
            <thead className="bg-[#faf9ff]">
              <tr>
                {[
                  "email",
                  "role",
                  "invitedBy",
                  "expires",
                  "sent",
                  "actions",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-2.5 text-left text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase"
                  >
                    {t(`columns.${h}`)}
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
                      {t(
                        `roles.${inv.role === "security_admin" ? "securityAdmin" : inv.role === "billing_admin" ? "billingAdmin" : inv.role}`,
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[#7a7690]">
                    {inv.invited_by_name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-[#7a7690]">
                    {formatDate(inv.expires_at, locale)}
                  </td>
                  <td className="px-4 py-3 text-[#7a7690]">
                    {inv.resend_count > 0 ? `${inv.resend_count + 1}×` : "1×"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        disabled={resendMutation.isPending}
                        onClick={() => resendMutation.mutate(inv.invitation_id)}
                        className="rounded border border-[#d2cee6] px-2 py-0.5 text-[11px] font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
                      >
                        {t("actions.resend")}
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
                        {t("actions.revoke")}
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
  );
}
