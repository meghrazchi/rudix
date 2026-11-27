"use client";

import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function ProfileActionBar({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const { t, isSavingAll, handleUpdateProfile, handleDiscard } = ctl;

  return (
    <>
      {/* ── Action Bar ── */}
      <div className="mt-8 flex items-center justify-end gap-4">
        <button
          type="button"
          onClick={handleDiscard}
          disabled={isSavingAll}
          className="rounded-2xl px-6 py-3 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("discardChanges")}
        </button>
        <button
          type="button"
          onClick={() => {
            void handleUpdateProfile();
          }}
          disabled={isSavingAll}
          className="rounded-2xl bg-[#3525cd] px-8 py-3 text-sm font-semibold text-white shadow-lg transition-all hover:shadow-[#3525cd]/30 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSavingAll ? t("saving") : t("updateProfile")}
        </button>
      </div>
    </>
  );
}
