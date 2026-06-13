"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  Brain,
  Moon,
  Monitor,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getProfileCapabilities } from "@/lib/api/profile";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  createDefaultSettingsPreferences,
  loadSettingsPreferences,
  persistSettingsPreferences,
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

function getInitials(email: string | null): string {
  if (!email) return "?";
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._-]/);
  if (parts.length >= 2 && parts[0] && parts[1]) {
    return (parts[0][0]! + parts[1][0]!).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase() || "?";
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

export function ProfileSettingsTab() {
  const t = useTranslations("settings.profile");
  const tAuth = useTranslations("auth");
  const tRoles = useTranslations("appShell.roles");
  const router = useRouter();
  const { state, signOut } = useAuthSession();
  const session = state.session;

  const profileCapabilities = getProfileCapabilities();

  const [userIdCopied, setUserIdCopied] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [isSavingAll, setIsSavingAll] = useState(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const preferencesQuery = useQuery({
    queryKey: ["settings", "preferences"],
    queryFn: loadSettingsPreferences,
  });

  useEffect(() => {
    if (!preferencesQuery.data) return;
    lastSavedRagRef.current = preferencesQuery.data;
    ragForm.reset(preferencesQuery.data);
  }, [ragForm, preferencesQuery.data]);

  const ragSaveMutation = useMutation({
    mutationFn: async (values: SettingsPreferences) =>
      persistSettingsPreferences(values),
  });

  const showSuccess = useCallback((msg: string) => {
    setToastMessage(msg);
    setShowToast(true);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setShowToast(false), 3000);
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

  const watchedTheme = personalForm.watch("theme");
  const watchedTopK = ragForm.watch("defaultTopK");
  const watchedRerank = ragForm.watch("rerankEnabled");

  const initials = getInitials(session?.email ?? null);
  const displayName = deriveDisplayName(session?.email ?? null);

  const themeLabel: Record<(typeof THEME_OPTIONS)[number], string> = {
    light: t("themes.light"),
    dark: t("themes.dark"),
    system: t("themes.system"),
  };

  return (
    <>
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
                  className="flex h-32 w-32 items-center justify-center rounded-full border-4 border-[#eae6f4] bg-[#e2dfff] text-3xl font-bold text-[#3525cd]"
                  aria-label={t("aria.userAvatar")}
                >
                  {initials}
                </div>
              </div>

              {/* Fields */}
              <div className="grid w-full flex-1 grid-cols-1 gap-4">
                <div className="space-y-1">
                  <label className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                    {t("fullName")}
                  </label>
                  <input
                    readOnly
                    value={displayName}
                    className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                </div>

                <div className="space-y-1">
                  <label className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
                    {t("emailAddress")}
                  </label>
                  <input
                    readOnly
                    value={session?.email ?? ""}
                    className="w-full rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
                  />
                </div>

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

                {session?.userId ? (
                  <div className="flex items-center justify-between gap-2 rounded-xl border border-[#c7c4d8] bg-[#f5f2ff] px-4 py-2">
                    <span className="max-w-[200px] truncate font-mono text-xs text-[#464555]">
                      {session.userId}
                    </span>
                    <button
                      type="button"
                      onClick={handleCopyUserId}
                      className="shrink-0 rounded-lg border border-[#c7c4d8] px-2 py-0.5 text-xs font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
                    >
                      {userIdCopied ? t("copied") : t("copyId")}
                    </button>
                  </div>
                ) : null}
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
                <label
                  htmlFor="language"
                  className="block text-[10px] font-semibold tracking-widest text-[#464555] uppercase"
                >
                  {t("displayLanguage")}
                </label>
                <select
                  id="language"
                  {...personalForm.register("language")}
                  className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
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
                  className="w-full appearance-none rounded-xl border border-[#c7c4d8] bg-[#fcf8ff] px-4 py-2 text-sm text-[#1b1b24] transition-all outline-none focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/10"
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
                  <span className="rounded bg-[#d0e1fb] px-2 py-1 text-[10px] font-semibold tracking-wider text-[#54647a] uppercase">
                    {t("expertMode")}
                  </span>
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

                  {/* Confidence threshold (display only) */}
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-[#1b1b24]">
                      {t("confidence.label")}
                    </p>
                    <div className="relative flex h-12 items-center overflow-hidden rounded-xl border border-[#c7c4d8] bg-[#f0ecf9] px-4">
                      <div className="absolute top-0 bottom-0 left-0 w-[82%] border-r-2 border-[#3525cd] bg-[#3525cd]/10" />
                      <span className="relative z-10 font-mono text-xl text-[#3525cd]">
                        0.82{" "}
                        <span className="text-sm font-normal text-[#464555]">
                          / 1.0
                        </span>
                      </span>
                      <span className="relative z-10 ml-auto rounded-lg bg-[#3525cd] px-2 py-1 text-[10px] font-semibold tracking-wider text-white uppercase">
                        {t("confidence.highTrust")}
                      </span>
                    </div>
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
