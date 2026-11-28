"use client";

import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function AccountActionsSection({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const {
    t,
    tAuth,
    profileCapabilities,
    isSigningOut,
    setShowSignOutAllDialog,
    setShowDeleteAccountDialog,
    handleSignOut,
  } = ctl;

  return (
    <>
      <section
        className="mt-8 rounded-2xl border border-[#c7c4d8] bg-white p-6"
        aria-label={t("aria.accountActionsSection")}
      >
        <h3 className="mb-4 text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
          {t("accountActions")}
        </h3>

        <div className="space-y-3">
          {/* Sign out current session */}
          <div className="flex items-start justify-between gap-4 rounded-xl border border-[#eae6f4] px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">
                {tAuth("signOut")}
              </p>
              <p className="text-xs text-[#464555]">
                {t("signOutDescription")}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                void handleSignOut();
              }}
              disabled={isSigningOut}
              className="shrink-0 rounded-xl border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSigningOut ? tAuth("signingOut") : tAuth("signOut")}
            </button>
          </div>

          {/* Sign out all devices */}
          <div
            className={`flex items-start justify-between gap-4 rounded-xl border px-4 py-3 ${
              profileCapabilities.signOutAllDevicesEnabled
                ? "border-[#eae6f4]"
                : "border-dashed border-[#c7c4d8] opacity-70"
            }`}
          >
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">
                {tAuth("signOutAllDevices")}
              </p>
              <p className="text-xs text-[#464555]">
                {t("signOutAllDevicesDescription")}
              </p>
              {!profileCapabilities.signOutAllDevicesEnabled && (
                <p className="mt-1 text-xs text-[#777587]">
                  {t("notAvailable")}
                </p>
              )}
            </div>
            {profileCapabilities.signOutAllDevicesEnabled ? (
              <button
                type="button"
                onClick={() => setShowSignOutAllDialog(true)}
                className="shrink-0 rounded-xl border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-100"
              >
                {tAuth("signOutEverywhere")}
              </button>
            ) : (
              <span className="shrink-0 rounded-xl border border-dashed border-[#c7c4d8] px-3 py-1.5 text-sm text-[#777587]">
                {t("unavailable")}
              </span>
            )}
          </div>

          {/* Delete account */}
          <div
            className={`flex items-start justify-between gap-4 rounded-xl border px-4 py-3 ${
              profileCapabilities.deleteAccountEnabled
                ? "border-rose-200 bg-rose-50/30"
                : "border-dashed border-[#c7c4d8] opacity-70"
            }`}
          >
            <div>
              <p className="text-sm font-semibold text-rose-700">
                {t("deleteAccount")}
              </p>
              <p className="text-xs text-[#464555]">
                {t("deleteAccountDescription")}
              </p>
              {!profileCapabilities.deleteAccountEnabled && (
                <p className="mt-1 text-xs text-[#777587]">
                  {t("notAvailable")}
                </p>
              )}
            </div>
            {profileCapabilities.deleteAccountEnabled ? (
              <button
                type="button"
                onClick={() => setShowDeleteAccountDialog(true)}
                className="shrink-0 rounded-xl border border-rose-300 px-3 py-1.5 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-100"
              >
                {t("deleteAccountBtn")}
              </button>
            ) : (
              <span className="shrink-0 rounded-xl border border-dashed border-[#c7c4d8] px-3 py-1.5 text-sm text-[#777587]">
                {t("unavailable")}
              </span>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
