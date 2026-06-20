"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  Brain,
  Camera,
  Key,
  Moon,
  Monitor,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { z } from "zod";

import { ContextualHelpLink } from "@/components/help/ContextualHelpLink";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  changePassword,
  getMe,
  getProfileCapabilities,
  removeAvatar,
  signOutAllDevices,
  deletePersonalAccount,
  updateMe,
  uploadAvatar,
} from "@/lib/api/profile";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  createDefaultSettingsPreferences,
  loadSettingsPreferences,
  persistSettingsPreferences,
  settingsConfidenceBounds,
  settingsPreferencesSchema,
  settingsTopKBounds,
  type PersistedSettingsPreferences,
  type SettingsPreferences,
} from "@/lib/settings-preferences";
import {
  createDefaultProfileUiPreferences,
  loadProfileUiPreferences,
  profileUiPreferencesSchema,
  saveProfileUiPreferences,
  LANGUAGE_OPTIONS,
  THEME_OPTIONS,
  TIMEZONE_OPTIONS,
  type ProfileUiPreferences,
} from "@/lib/schemas/settings";
import { isValidLocale, LOCALE_COOKIE_NAME } from "@/i18n/routing";

// ── Helpers ────────────────────────────────────────────────────────────────────

function getInitials(name: string | null, email: string | null): string {
  const source = name ?? email ?? "";
  if (!source) return "?";
  const parts = source
    .split(/[\s._@-]+/)
    .filter(Boolean)
    .slice(0, 2);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return (parts[0]?.slice(0, 2) ?? "?").toUpperCase();
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function deriveDisplayName(email: string | null): string {
  if (!email) return "";
  const local = email.split("@")[0] ?? "";
  return local
    .split(/[._-]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

const THEME_ICONS = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const;

const VALID_ROLES = ["owner", "admin", "member", "viewer"] as const;
type ValidRole = (typeof VALID_ROLES)[number];

const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Current password is required."),
    newPassword: z
      .string()
      .min(8, "New password must be at least 8 characters.")
      .max(128, "New password must not exceed 128 characters."),
    confirmNewPassword: z.string().min(1, "Please confirm your new password."),
  })
  .refine((d) => d.newPassword === d.confirmNewPassword, {
    message: "Passwords do not match.",
    path: ["confirmNewPassword"],
  });

type ChangePasswordValues = z.infer<typeof changePasswordSchema>;

// ── Subcomponents ─────────────────────────────────────────────────────────────

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  isPending,
  danger,
  children,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
  danger?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-2xl">
        <h2 className="mb-2 text-base font-bold text-[#1b1b24]">{title}</h2>
        <p className="mb-4 text-sm text-[#464555]">{body}</p>
        {children}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-xl px-4 py-2 text-sm font-semibold text-[#464555] transition-colors hover:bg-[#eae6f4] disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className={[
              "rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              danger
                ? "border border-rose-300 text-rose-700 hover:bg-rose-100"
                : "bg-[#3525cd] text-white hover:bg-[#2a1db0]",
            ].join(" ")}
          >
            {isPending ? "Please wait…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function UserProfilePage() {
  const t = useTranslations("settings.profile");
  const tAuth = useTranslations("auth");
  const tRoles = useTranslations("appShell.roles");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state, signOut } = useAuthSession();
  const session = state.session;

  const profileCapabilities = getProfileCapabilities();

  // ── UI state ─────────────────────────────────────────────────────────────

  const [userIdCopied, setUserIdCopied] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [isSavingAll, setIsSavingAll] = useState(false);
  const [showChangePasswordDialog, setShowChangePasswordDialog] =
    useState(false);
  const [showSignOutAllDialog, setShowSignOutAllDialog] = useState(false);
  const [showDeleteAccountDialog, setShowDeleteAccountDialog] = useState(false);
  const [deleteConfirmEmail, setDeleteConfirmEmail] = useState("");
  const [avatarDragOver, setAvatarDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Forms ────────────────────────────────────────────────────────────────

  const lastSavedPersonalRef = useRef<ProfileUiPreferences>(
    createDefaultProfileUiPreferences(),
  );

  const personalForm = useForm<ProfileUiPreferences>({
    resolver: zodResolver(profileUiPreferencesSchema),
    defaultValues: createDefaultProfileUiPreferences(),
    mode: "onSubmit",
  });

  useEffect(() => {
    const loaded = loadProfileUiPreferences();
    lastSavedPersonalRef.current = loaded;
    personalForm.reset(loaded);
  }, [personalForm]);

  const lastSavedRagRef = useRef<SettingsPreferences>(
    createDefaultSettingsPreferences(),
  );

  const ragForm = useForm<SettingsPreferences>({
    resolver: zodResolver(settingsPreferencesSchema),
    defaultValues: createDefaultSettingsPreferences(),
    mode: "onSubmit",
  });

  const changePasswordForm = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: {
      currentPassword: "",
      newPassword: "",
      confirmNewPassword: "",
    },
    mode: "onSubmit",
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  const meQuery = useQuery({
    queryKey: ["profile", "me"],
    queryFn: getMe,
    enabled: profileCapabilities.meEnabled,
    retry: false,
  });

  const [nameValue, setNameValue] = useState("");

  useEffect(() => {
    if (meQuery.data) {
      setNameValue(meQuery.data.name ?? "");
    } else if (session?.email) {
      setNameValue(deriveDisplayName(session.email));
    }
  }, [meQuery.data, session?.email]);

  const preferencesQuery = useQuery({
    queryKey: ["settings", "preferences"],
    queryFn: loadSettingsPreferences,
  });

  useEffect(() => {
    if (!preferencesQuery.data) return;
    lastSavedRagRef.current = preferencesQuery.data;
    ragForm.reset(preferencesQuery.data);
  }, [ragForm, preferencesQuery.data]);

  // ── Mutations ────────────────────────────────────────────────────────────

  const ragSaveMutation = useMutation({
    mutationFn: async (values: SettingsPreferences) =>
      persistSettingsPreferences(values),
  });

  const updateMeMutation = useMutation({
    mutationFn: (name: string) => updateMe({ name }),
    onSuccess: (data) => {
      queryClient.setQueryData(["profile", "me"], data);
    },
  });

  const avatarUploadMutation = useMutation({
    mutationFn: (file: File) => uploadAvatar(file),
    onSuccess: (data) => {
      queryClient.setQueryData(["profile", "me"], data);
      showSuccess("Profile photo updated.");
    },
    onError: (err) => {
      showSuccess(getApiErrorMessage(err) ?? "Failed to upload avatar.");
    },
  });

  const avatarRemoveMutation = useMutation({
    mutationFn: removeAvatar,
    onSuccess: () => {
      void meQuery.refetch();
      showSuccess("Profile photo removed.");
    },
  });

  const changePasswordMutation = useMutation({
    mutationFn: (values: ChangePasswordValues) =>
      changePassword(
        values.currentPassword,
        values.newPassword,
        values.confirmNewPassword,
      ),
    onSuccess: () => {
      setShowChangePasswordDialog(false);
      changePasswordForm.reset();
      showSuccess(t("passwordChanged"));
    },
  });

  const signOutAllMutation = useMutation({
    mutationFn: signOutAllDevices,
    onSuccess: () => {
      setShowSignOutAllDialog(false);
      showSuccess("Signed out from all devices.");
    },
  });

  const deleteAccountMutation = useMutation({
    mutationFn: deletePersonalAccount,
    onSuccess: () => {
      router.replace("/login?reason=account_deleted");
    },
  });

  // ── Helpers ──────────────────────────────────────────────────────────────

  const showSuccess = useCallback((msg: string) => {
    setToastMessage(msg);
    setShowToast(true);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setShowToast(false), 3500);
  }, []);

  async function handleUpdateProfile(): Promise<void> {
    const personalValid = await personalForm.trigger();
    const ragValid = await ragForm.trigger();
    if (!personalValid || !ragValid) return;

    setIsSavingAll(true);
    try {
      const personalValues = personalForm.getValues();
      const previousLanguage = lastSavedPersonalRef.current.language;
      saveProfileUiPreferences(personalValues);
      lastSavedPersonalRef.current = personalValues;
      personalForm.reset(personalValues);

      // Save name via /me if available and changed
      if (
        profileCapabilities.meEnabled &&
        nameValue.trim() &&
        nameValue.trim() !== (meQuery.data?.name ?? "")
      ) {
        await updateMeMutation.mutateAsync(nameValue.trim());
      }

      const ragValues = ragForm.getValues();
      const result: PersistedSettingsPreferences =
        await ragSaveMutation.mutateAsync(ragValues);
      lastSavedRagRef.current = result.preferences;
      ragForm.reset(result.preferences);

      showSuccess(
        result.persistenceScope === "remote"
          ? t("savedSuccessfully")
          : t("savedLocally"),
      );

      if (
        personalValues.language !== previousLanguage &&
        isValidLocale(personalValues.language)
      ) {
        document.cookie = `${LOCALE_COOKIE_NAME}=${personalValues.language}; path=/; samesite=lax; max-age=${60 * 60 * 24 * 365}`;
        setTimeout(() => {
          window.location.reload();
        }, 800);
      }
    } finally {
      setIsSavingAll(false);
    }
  }

  function handleDiscard(): void {
    personalForm.reset(lastSavedPersonalRef.current);
    ragForm.reset(lastSavedRagRef.current);
    if (meQuery.data) setNameValue(meQuery.data.name ?? "");
    else setNameValue(deriveDisplayName(session?.email ?? null));
  }

  async function handleSignOut(): Promise<void> {
    setIsSigningOut(true);
    try {
      await signOut();
      router.replace("/login?reason=signed_out");
    } finally {
      setIsSigningOut(false);
    }
  }

  function handleCopyUserId(): void {
    if (!session?.userId) return;
    void navigator.clipboard.writeText(session.userId).then(() => {
      setUserIdCopied(true);
      setTimeout(() => setUserIdCopied(false), 2000);
    });
  }

  function translateRole(role: string | undefined | null): string {
    if (!role) return tRoles("member");
    return VALID_ROLES.includes(role as ValidRole)
      ? tRoles(role as ValidRole)
      : role;
  }

  function handleAvatarFile(file: File): void {
    const allowed = ["image/png", "image/jpeg", "image/webp"];
    if (!allowed.includes(file.type)) {
      showSuccess("Avatar must be PNG, JPEG, or WEBP.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      showSuccess("Avatar file must be under 5 MB.");
      return;
    }
    avatarUploadMutation.mutate(file);
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    if (file) handleAvatarFile(file);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    setAvatarDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleAvatarFile(file);
  }

  // ── Watched values ───────────────────────────────────────────────────────

  const watchedTheme = personalForm.watch("theme");
  const watchedTopK = ragForm.watch("defaultTopK");
  const watchedRerank = ragForm.watch("rerankEnabled");
  const watchedDeveloperMode = ragForm.watch("developerMode");
  const watchedConfidence = ragForm.watch("confidenceThreshold");

  const resolvedName =
    meQuery.data?.name ?? deriveDisplayName(session?.email ?? null);
  const resolvedAvatarUrl = meQuery.data?.avatarUrl ?? null;
  const initials = getInitials(resolvedName, session?.email ?? null);

  const themeLabel: Record<(typeof THEME_OPTIONS)[number], string> = {
    light: t("themes.light"),
    dark: t("themes.dark"),
    system: t("themes.system"),
  };

  const confidencePercent =
    watchedConfidence ?? settingsConfidenceBounds.defaultValue;
  const isHighTrust =
    confidencePercent >= settingsConfidenceBounds.highTrustThreshold;

  return (
    <>
      {/* ── Change Password Dialog ── */}
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

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        {/* ── Left column ── */}
        <div className="space-y-6 lg:col-span-7">
          {/* 1) Account Identity */}
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

          {/* 2) Personal Preferences */}
          <section
            className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
            aria-label={t("aria.personalPreferencesSection")}
          >
            <div className="mb-6 flex items-center gap-3">
              <SlidersHorizontal size={20} className="text-[#3525cd]" />
              <h3 className="text-lg font-semibold text-[#1b1b24]">
                {t("personalPreferences")}
              </h3>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <label
                    htmlFor="language"
                    className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                  >
                    {t("displayLanguage")}
                  </label>
                  <ContextualHelpLink topic="multilingual" />
                </div>
                <select
                  id="language"
                  {...personalForm.register("language")}
                  className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                >
                  {LANGUAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="timezone"
                  className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                >
                  {t("timezone")}
                </label>
                <select
                  id="timezone"
                  {...personalForm.register("timezone")}
                  className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                >
                  {TIMEZONE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Theme picker */}
            <div className="mt-6">
              <p className="mb-3 block text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                {t("interfaceTheme")}
              </p>
              <div className="grid grid-cols-3 gap-4">
                {THEME_OPTIONS.map((opt) => {
                  const Icon = THEME_ICONS[opt];
                  const isActive = watchedTheme === opt;
                  return (
                    <label
                      key={opt}
                      className={[
                        "flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 p-4 transition-all",
                        isActive
                          ? "border-[#3525cd] bg-[#3525cd]/5"
                          : "border-transparent bg-[#f0ecf9] hover:border-[#c7c4d8]",
                      ].join(" ")}
                    >
                      <input
                        type="radio"
                        {...personalForm.register("theme")}
                        value={opt}
                        className="sr-only"
                      />
                      <Icon
                        size={20}
                        className={
                          isActive ? "text-[#3525cd]" : "text-[#464555]"
                        }
                      />
                      <span
                        className={[
                          "text-sm",
                          isActive
                            ? "font-bold text-[#3525cd]"
                            : "text-[#464555]",
                        ].join(" ")}
                      >
                        {themeLabel[opt]}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          </section>
        </div>

        {/* ── Right column ── */}
        <div className="space-y-6 lg:col-span-5">
          {/* 3) AI/RAG Defaults */}
          {preferencesQuery.isLoading ? (
            <div className="rounded-2xl border border-[#c7c4d8] bg-white p-6">
              <LoadingState compact title={t("loadingPreferences")} />
            </div>
          ) : preferencesQuery.isError ? (
            <div className="rounded-2xl border border-[#c7c4d8] bg-white p-6">
              <ErrorState
                compact
                error={preferencesQuery.error}
                description={getApiErrorMessage(preferencesQuery.error)}
                onRetry={() => {
                  void preferencesQuery.refetch();
                }}
              />
            </div>
          ) : (
            <>
              <section
                className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
                aria-label={t("aria.aiDefaultsSection")}
              >
                <div className="mb-6 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Brain size={20} className="text-[#3525cd]" />
                    <h3 className="text-lg font-semibold text-[#1b1b24]">
                      {t("aiRagDefaults")}
                    </h3>
                  </div>
                  {/* Expert mode toggle */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={watchedDeveloperMode}
                    aria-label={t("expertModeToggle")}
                    onClick={() =>
                      ragForm.setValue("developerMode", !watchedDeveloperMode, {
                        shouldDirty: true,
                      })
                    }
                    className={[
                      "rounded px-2 py-1 text-[10px] font-semibold tracking-wider uppercase transition-colors",
                      watchedDeveloperMode
                        ? "bg-[#3525cd] text-white"
                        : "bg-[#d0e1fb] text-[#54647a] hover:bg-[#b8d0f8]",
                    ].join(" ")}
                  >
                    {t("expertMode")}
                  </button>
                </div>

                <div className="space-y-8">
                  {/* Top-K slider */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label
                        htmlFor="topKSlider"
                        className="text-sm font-semibold text-[#1b1b24]"
                      >
                        {t("topK.label")}
                      </label>
                      <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-sm text-[#3525cd]">
                        {watchedTopK ?? settingsTopKBounds.defaultValue}
                      </span>
                    </div>
                    <input
                      id="topKSlider"
                      type="range"
                      min={settingsTopKBounds.min}
                      max={settingsTopKBounds.max}
                      step={1}
                      aria-label={t("topK.label")}
                      {...ragForm.register("defaultTopK", {
                        valueAsNumber: true,
                      })}
                      className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-[#c7c4d8] accent-[#3525cd]"
                    />
                    <div className="flex justify-between text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                      <span>{t("topK.precision")}</span>
                      <span>{t("topK.diversity")}</span>
                    </div>
                  </div>

                  {/* Rerank toggle */}
                  <div className="flex items-center justify-between rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] p-4">
                    <div>
                      <p className="text-sm font-semibold text-[#1b1b24]">
                        {t("rerank.title")}
                      </p>
                      <p className="text-xs text-[#464555]">
                        {t("rerank.description")}
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={watchedRerank}
                      onClick={() =>
                        ragForm.setValue("rerankEnabled", !watchedRerank, {
                          shouldDirty: true,
                        })
                      }
                      className={[
                        "relative flex h-6 w-12 shrink-0 items-center rounded-full px-1 transition-colors",
                        watchedRerank ? "bg-[#3525cd]" : "bg-[#c7c4d8]",
                      ].join(" ")}
                    >
                      <div
                        className={[
                          "h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                          watchedRerank ? "translate-x-6" : "translate-x-0",
                        ].join(" ")}
                      />
                    </button>
                  </div>

                  {/* Confidence threshold */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <label
                        htmlFor="confidenceSlider"
                        className="text-sm font-semibold text-[#1b1b24]"
                      >
                        {t("confidence.label")}
                      </label>
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-[#f0ecf9] px-2 py-0.5 font-mono text-sm text-[#3525cd]">
                          {(confidencePercent / 100).toFixed(2)}
                        </span>
                        {isHighTrust && (
                          <span className="rounded bg-[#3525cd] px-2 py-0.5 text-[10px] font-semibold tracking-wider text-white uppercase">
                            {t("confidence.highTrust")}
                          </span>
                        )}
                      </div>
                    </div>
                    <input
                      id="confidenceSlider"
                      type="range"
                      min={settingsConfidenceBounds.min}
                      max={settingsConfidenceBounds.max}
                      step={1}
                      aria-label={t("confidence.label")}
                      {...ragForm.register("confidenceThreshold", {
                        valueAsNumber: true,
                      })}
                      className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-[#c7c4d8] accent-[#3525cd]"
                    />
                  </div>
                </div>
              </section>

              {/* 4) Notifications */}
              <section
                className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
                aria-label={t("aria.notificationsSection")}
              >
                <div className="mb-6 flex items-center gap-3">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-[#3525cd]"
                    aria-hidden="true"
                  >
                    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                    <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
                    <path d="M4 2C2.8 3.7 2 5.7 2 8" />
                    <path d="M22 8c0-2.3-.8-4.3-2-6" />
                  </svg>
                  <h3 className="text-lg font-semibold text-[#1b1b24]">
                    {t("notifications")}
                  </h3>
                </div>

                <fieldset className="space-y-4">
                  <legend className="sr-only">
                    {t("notificationPreferences")}
                  </legend>

                  <label className="group flex cursor-pointer items-start gap-4">
                    <input
                      type="checkbox"
                      {...ragForm.register("notifications.documentProcessing")}
                      className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                    />
                    <div>
                      <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                        {t("processingAlerts.title")}
                      </span>
                      <span className="block text-xs text-[#464555]">
                        {t("processingAlerts.description")}
                      </span>
                    </div>
                  </label>

                  <label className="group flex cursor-pointer items-start gap-4">
                    <input
                      type="checkbox"
                      {...ragForm.register("notifications.securityAlerts")}
                      className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                    />
                    <div>
                      <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                        {t("securityWarnings.title")}
                      </span>
                      <span className="block text-xs text-[#464555]">
                        {t("securityWarnings.description")}
                      </span>
                    </div>
                  </label>

                  <label className="group flex cursor-pointer items-start gap-4 opacity-60">
                    <input
                      type="checkbox"
                      {...ragForm.register(
                        "notifications.evaluationCompletion",
                      )}
                      className="mt-0.5 h-5 w-5 rounded border-[#c7c4d8] text-[#3525cd] transition-all focus:ring-[#3525cd]/20"
                    />
                    <div>
                      <span className="block text-sm font-semibold text-[#1b1b24] transition-colors group-hover:text-[#3525cd]">
                        {t("evalReports.title")}
                      </span>
                      <span className="block text-xs text-[#464555]">
                        {t("evalReports.description")}
                      </span>
                    </div>
                  </label>
                </fieldset>
              </section>
            </>
          )}
        </div>
      </div>

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

      {/* ── Account Actions ── */}
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

      {/* ── Toast ── */}
      <div
        aria-live="polite"
        aria-atomic="true"
        className={[
          "fixed right-8 bottom-8 z-50 flex items-center gap-3 rounded-2xl px-6 py-4 shadow-2xl transition-all duration-500",
          "bg-[#302f39] text-white",
          showToast
            ? "translate-y-0 opacity-100"
            : "pointer-events-none translate-y-20 opacity-0",
        ].join(" ")}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="shrink-0 text-[#c3c0ff]"
          aria-hidden="true"
        >
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span className="text-sm font-semibold">{toastMessage}</span>
      </div>
    </>
  );
}
