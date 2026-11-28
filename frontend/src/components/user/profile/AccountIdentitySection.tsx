"use client";

import { Camera, Key, ShieldCheck, Trash2, Upload } from "lucide-react";
import { useUserProfileController } from "@/components/user/profile/useUserProfileController";

export function AccountIdentitySection({
  ctl,
}: {
  ctl: ReturnType<typeof useUserProfileController>;
}) {
  const {
    t,
    session,
    profileCapabilities,
    userIdCopied,
    setShowChangePasswordDialog,
    avatarDragOver,
    setAvatarDragOver,
    fileInputRef,
    nameValue,
    setNameValue,
    avatarUploadMutation,
    avatarRemoveMutation,
    handleCopyUserId,
    translateRole,
    handleFileInputChange,
    handleDrop,
    resolvedName,
    resolvedAvatarUrl,
    initials,
  } = ctl;

  return (
    <>
      <section
        className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
        aria-label={t("aria.accountIdentitySection")}
      >
        <div className="mb-6 flex items-center gap-3">
          <ShieldCheck size={20} className="text-[#3525cd]" />
          <h3 className="text-lg font-semibold text-[#1b1b24]">
            {t("accountIdentity")}
          </h3>
        </div>

        <div className="flex flex-col items-start gap-8 md:flex-row">
          {/* Avatar */}
          <div className="relative shrink-0">
            <div
              className={[
                "relative flex h-32 w-32 cursor-pointer items-center justify-center overflow-hidden rounded-full border-4",
                avatarDragOver
                  ? "border-[#3525cd] bg-[#3525cd]/10"
                  : "border-[#eae6f4] bg-[#e2dfff]",
              ].join(" ")}
              aria-label={t("aria.userAvatar")}
              onDragOver={(e) => {
                e.preventDefault();
                setAvatarDragOver(true);
              }}
              onDragLeave={() => setAvatarDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ")
                  fileInputRef.current?.click();
              }}
            >
              {resolvedAvatarUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolvedAvatarUrl}
                  alt="Profile photo"
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="text-3xl font-bold text-[#3525cd]">
                  {initials}
                </span>
              )}

              {avatarUploadMutation.isPending && (
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/30">
                  <span className="text-xs font-semibold text-white">
                    {t("uploadingAvatar")}
                  </span>
                </div>
              )}

              {!avatarUploadMutation.isPending && (
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/0 opacity-0 transition-opacity hover:bg-black/30 hover:opacity-100">
                  <Camera size={24} className="text-white" />
                </div>
              )}
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              aria-label={t("uploadAvatar")}
              onChange={handleFileInputChange}
            />

            {/* Avatar action buttons */}
            <div className="mt-2 flex flex-col gap-1">
              {profileCapabilities.avatarEnabled ? (
                <>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={avatarUploadMutation.isPending}
                    className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff] disabled:opacity-60"
                  >
                    <Upload size={12} />
                    {t("uploadAvatar")}
                  </button>
                  {resolvedAvatarUrl && (
                    <button
                      type="button"
                      onClick={() => avatarRemoveMutation.mutate()}
                      disabled={avatarRemoveMutation.isPending}
                      className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-[#777587] transition-colors hover:bg-[#f5f3ff] disabled:opacity-60"
                    >
                      <Trash2 size={12} />
                      {t("removeAvatar")}
                    </button>
                  )}
                </>
              ) : (
                <p className="text-[10px] text-[#777587]">
                  {t("avatarUnavailable")}
                </p>
              )}
            </div>
          </div>

          {/* Fields */}
          <div className="grid w-full flex-1 grid-cols-1 gap-4">
            {/* Full Name */}
            <div className="space-y-1">
              <label
                htmlFor="displayName"
                className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                {t("fullName")}
              </label>
              {profileCapabilities.meEnabled ? (
                <input
                  id="displayName"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                />
              ) : (
                <input
                  id="displayName"
                  readOnly
                  value={resolvedName}
                  className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none"
                />
              )}
            </div>

            {/* Email */}
            <div className="space-y-1">
              <label
                htmlFor="emailAddress"
                className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
              >
                {t("emailAddress")}
              </label>
              <input
                id="emailAddress"
                readOnly
                value={session?.email ?? ""}
                className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none"
              />
            </div>

            {/* Role */}
            <div className="space-y-1">
              <label className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                {t("role")}
              </label>
              <div className="flex items-center gap-2 rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2 text-[#464555]">
                <ShieldCheck
                  size={16}
                  className="shrink-0 text-[#3525cd]"
                  aria-hidden="true"
                />
                <span className="text-sm font-semibold text-[#1b1b24]">
                  {translateRole(session?.role)}
                </span>
              </div>
            </div>

            {/* User ID */}
            {session?.userId ? (
              <div className="flex items-center justify-between gap-2 rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2">
                <span className="max-w-[200px] truncate font-mono text-xs text-[#464555]">
                  {session.userId}
                </span>
                <button
                  type="button"
                  onClick={handleCopyUserId}
                  aria-label={userIdCopied ? t("copied") : t("copyId")}
                  className="shrink-0 rounded-lg border border-[#c7c4d8] px-2 py-0.5 text-xs font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
                >
                  {userIdCopied ? t("copied") : t("copyId")}
                </button>
              </div>
            ) : null}

            {/* Change Password */}
            {profileCapabilities.changePasswordEnabled ? (
              <button
                type="button"
                onClick={() => setShowChangePasswordDialog(true)}
                className="flex items-center gap-2 self-start rounded-xl border border-[#c7c4d8] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
              >
                <Key size={14} />
                {t("changePasswordBtn")}
              </button>
            ) : (
              <p className="text-[10px] text-[#777587]">
                {t("changePasswordUnavailable")}
              </p>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
