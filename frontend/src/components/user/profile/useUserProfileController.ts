"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
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
  type PersistedSettingsPreferences,
  type SettingsPreferences,
} from "@/lib/settings-preferences";
import {
  createDefaultProfileUiPreferences,
  loadProfileUiPreferences,
  profileUiPreferencesSchema,
  saveProfileUiPreferences,
  THEME_OPTIONS,
  type ProfileUiPreferences,
} from "@/lib/schemas/settings";
import { isValidLocale } from "@/i18n/routing";
import {
  type ValidRole,
  type ChangePasswordValues,
  getInitials,
  deriveDisplayName,
  VALID_ROLES,
  applyDisplayLanguage,
  changePasswordSchema,
} from "@/components/user/profile/profileShared";
import { queryKeys } from "@/lib/api/query";

export function useUserProfileController() {
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
    queryKey: queryKeys.profileMe,
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
    queryKey: queryKeys.settingsPreferences,
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
      queryClient.setQueryData(queryKeys.profileMe, data);
    },
  });

  const avatarUploadMutation = useMutation({
    mutationFn: (file: File) => uploadAvatar(file),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.profileMe, data);
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
      const selectedDisplayLanguage = isValidLocale(personalValues.language)
        ? personalValues.language
        : null;
      // Display language is a personal UI preference and must not depend on an
      // unrelated profile or retrieval-settings endpoint succeeding.
      if (
        selectedDisplayLanguage !== null &&
        selectedDisplayLanguage !== previousLanguage
      ) {
        applyDisplayLanguage(selectedDisplayLanguage);
        router.refresh();
      }

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
  return {
    t,
    tAuth,
    tRoles,
    router,
    queryClient,
    state,
    signOut,
    session,
    profileCapabilities,
    userIdCopied,
    setUserIdCopied,
    isSigningOut,
    setIsSigningOut,
    showToast,
    setShowToast,
    toastMessage,
    setToastMessage,
    isSavingAll,
    setIsSavingAll,
    showChangePasswordDialog,
    setShowChangePasswordDialog,
    showSignOutAllDialog,
    setShowSignOutAllDialog,
    showDeleteAccountDialog,
    setShowDeleteAccountDialog,
    deleteConfirmEmail,
    setDeleteConfirmEmail,
    avatarDragOver,
    setAvatarDragOver,
    fileInputRef,
    toastTimerRef,
    lastSavedPersonalRef,
    personalForm,
    lastSavedRagRef,
    ragForm,
    changePasswordForm,
    meQuery,
    nameValue,
    setNameValue,
    preferencesQuery,
    ragSaveMutation,
    updateMeMutation,
    avatarUploadMutation,
    avatarRemoveMutation,
    changePasswordMutation,
    signOutAllMutation,
    deleteAccountMutation,
    showSuccess,
    handleUpdateProfile,
    handleDiscard,
    handleSignOut,
    handleCopyUserId,
    translateRole,
    handleAvatarFile,
    handleFileInputChange,
    handleDrop,
    watchedTheme,
    watchedTopK,
    watchedRerank,
    watchedDeveloperMode,
    watchedConfidence,
    resolvedName,
    resolvedAvatarUrl,
    initials,
    themeLabel,
    confidencePercent,
    isHighTrust,
  };
}
