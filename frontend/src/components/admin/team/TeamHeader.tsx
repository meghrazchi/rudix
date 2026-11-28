"use client";

import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";
import { useTeamController } from "@/components/admin/team/useTeamController";

export function TeamHeader({
  ctl,
}: {
  ctl: ReturnType<typeof useTeamController>;
}) {
  const {
    t,
    searchQuery,
    setShowInviteDialog,
    toast,
    capabilities,
    membersTotal,
  } = ctl;

  return (
    <>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[#2a2640]">{t("title")}</h1>
          <p className="mt-0.5 text-sm text-[#6b6895]">{t("description")}</p>
        </div>
        {capabilities.inviteEnabled && (
          <button
            type="button"
            onClick={() => setShowInviteDialog(true)}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            {t("inviteMember")}
          </button>
        )}
      </div>

      {capabilities.inviteEnabled && membersTotal <= 1 && !searchQuery ? (
        <OnboardingCtaBanner
          title={t("onboarding.title")}
          description={t("onboarding.description")}
          actionLabel={t("onboarding.action")}
          onAction={() => setShowInviteDialog(true)}
        />
      ) : null}

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
    </>
  );
}
