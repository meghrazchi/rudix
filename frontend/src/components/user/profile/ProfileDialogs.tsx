"use client";

import { X } from "lucide-react";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  type ChangePasswordValues,
  ConfirmDialog,
} from "@/components/user/profile/profileShared";
import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function ProfileDialogs({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const {
    t,
    session,
    showChangePasswordDialog,
    setShowChangePasswordDialog,
    showSignOutAllDialog,
    setShowSignOutAllDialog,
    showDeleteAccountDialog,
    setShowDeleteAccountDialog,
    deleteConfirmEmail,
    setDeleteConfirmEmail,
    changePasswordForm,
    changePasswordMutation,
    signOutAllMutation,
    deleteAccountMutation,
  } = ctl;

  return (
    <>
      {showChangePasswordDialog && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("changePassword")}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-bold text-[#1b1b24]">
                {t("changePassword")}
              </h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => {
                  setShowChangePasswordDialog(false);
                  changePasswordForm.reset();
                }}
                className="rounded-lg p-1 text-[#464555] hover:bg-[#eae6f4]"
              >
                <X size={18} />
              </button>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                void changePasswordForm.handleSubmit((values) => {
                  changePasswordMutation.mutate(values);
                })();
              }}
              className="space-y-4"
            >
              {(
                [
                  ["currentPassword", t("currentPassword"), "current-password"],
                  ["newPassword", t("newPassword"), "new-password"],
                  [
                    "confirmNewPassword",
                    t("confirmNewPassword"),
                    "new-password",
                  ],
                ] as [keyof ChangePasswordValues, string, string][]
              ).map(([field, label, autoComplete]) => (
                <div key={field} className="space-y-1">
                  <label
                    htmlFor={field}
                    className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                  >
                    {label}
                  </label>
                  <input
                    id={field}
                    type="password"
                    autoComplete={autoComplete}
                    {...changePasswordForm.register(field)}
                    className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                  {changePasswordForm.formState.errors[field] && (
                    <p className="text-xs text-rose-600" role="alert">
                      {changePasswordForm.formState.errors[field]?.message}
                    </p>
                  )}
                </div>
              ))}

              {changePasswordMutation.isError && (
                <p className="text-xs text-rose-600" role="alert">
                  {getApiErrorMessage(changePasswordMutation.error) ??
                    "Failed to change password."}
                </p>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowChangePasswordDialog(false);
                    changePasswordForm.reset();
                  }}
                  className="rounded-xl px-4 py-2 text-sm font-semibold text-[#464555] hover:bg-[#eae6f4]"
                >
                  {t("cancel")}
                </button>
                <button
                  type="submit"
                  disabled={changePasswordMutation.isPending}
                  className="rounded-xl bg-[#3525cd] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:opacity-60"
                >
                  {changePasswordMutation.isPending
                    ? "Saving…"
                    : t("changePasswordBtn")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Sign Out All Dialog ── */}
      {showSignOutAllDialog && (
        <ConfirmDialog
          title={t("confirmSignOutAll")}
          body={t("confirmSignOutAllBody")}
          confirmLabel={
            signOutAllMutation.isPending
              ? t("signingOutEverywhere")
              : t("confirmSignOutAllBtn")
          }
          onConfirm={() => signOutAllMutation.mutate()}
          onCancel={() => setShowSignOutAllDialog(false)}
          isPending={signOutAllMutation.isPending}
        />
      )}

      {/* ── Delete Account Dialog ── */}
      {showDeleteAccountDialog && (
        <ConfirmDialog
          title={t("confirmDeleteAccount")}
          body={t("confirmDeleteAccountBody")}
          confirmLabel={
            deleteAccountMutation.isPending
              ? t("deleting")
              : t("confirmDeleteAccountBtn")
          }
          onConfirm={() => {
            if (deleteConfirmEmail.trim() === (session?.email ?? "")) {
              deleteAccountMutation.mutate();
            }
          }}
          onCancel={() => {
            setShowDeleteAccountDialog(false);
            setDeleteConfirmEmail("");
          }}
          isPending={deleteAccountMutation.isPending}
          danger
        >
          <div className="mb-4 space-y-1">
            <label
              htmlFor="delete-confirm-email"
              className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
            >
              {t("confirmDeleteAccountEmailLabel")}
            </label>
            <input
              id="delete-confirm-email"
              type="email"
              value={deleteConfirmEmail}
              onChange={(e) => setDeleteConfirmEmail(e.target.value)}
              placeholder={session?.email ?? ""}
              className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-rose-400 focus:ring-2 focus:ring-rose-400/10"
            />
          </div>
        </ConfirmDialog>
      )}
    </>
  );
}
