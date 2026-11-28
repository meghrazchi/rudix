"use client";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { isForbiddenError } from "@/lib/forbidden";
import { useTeamController } from "@/components/admin/team/useTeamController";
import { TeamHeader } from "@/components/admin/team/TeamHeader";
import { MembersSection } from "@/components/admin/team/MembersSection";
import { InvitationsSection } from "@/components/admin/team/InvitationsSection";
import { TeamModals } from "@/components/admin/team/TeamModals";

export function AdminTeamPage() {
  const ctl = useTeamController();
  const { t, state, isAdmin, membersQuery } = ctl;

  if (state.status === "loading") {
    return <LoadingState title={t("loading.team")} />;
  }

  if (!isAdmin) {
    return (
      <ForbiddenState
        title={t("errors.forbiddenTitle")}
        description={t("errors.forbidden")}
        backHref="/dashboard"
        backLabel={t("backToDashboard")}
      />
    );
  }

  if (membersQuery.error && isForbiddenError(membersQuery.error)) {
    return (
      <ForbiddenState
        title={t("errors.accessDenied")}
        description={t("errors.noPermission")}
        backHref="/dashboard"
        backLabel={t("backToDashboard")}
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <TeamHeader ctl={ctl} />
      <MembersSection ctl={ctl} />
      <InvitationsSection ctl={ctl} />
      <TeamModals ctl={ctl} />
    </div>
  );
}
