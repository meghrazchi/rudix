"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage } from "@/lib/api/errors";
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

type SaveState = {
  tone: "neutral" | "success" | "error";
  message: string;
} | null;

function isAdminLikeRole(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

function formatAuthProvider(value: string | undefined): string {
  if (!value?.trim()) {
    return "app";
  }
  return value
    .trim()
    .split(/[\s_-]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function statusPill(isEnabled: boolean) {
  if (isEnabled) {
    return "inline-flex rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-800";
  }
  return "inline-flex rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700";
}

function saveStateClassName(saveState: SaveState): string {
  if (!saveState || saveState.tone === "neutral") {
    return "rounded-lg border border-[#e0dced] bg-[#faf8ff] px-3 py-2 text-sm text-[#4d4963]";
  }
  if (saveState.tone === "success") {
    return "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800";
  }
  return "rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800";
}

export function SettingsPage() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLikeRole(role);
  const [saveState, setSaveState] = useState<SaveState>(null);

  const lastSavedPreferencesRef = useRef<SettingsPreferences>(createDefaultSettingsPreferences());

  const form = useForm<SettingsPreferences>({
    resolver: zodResolver(settingsPreferencesSchema),
    defaultValues: createDefaultSettingsPreferences(),
    mode: "onSubmit",
  });

  const preferencesQuery = useQuery({
    queryKey: ["settings", "preferences"],
    queryFn: loadSettingsPreferences,
  });

  useEffect(() => {
    if (!preferencesQuery.data) {
      return;
    }
    lastSavedPreferencesRef.current = preferencesQuery.data;
    form.reset(preferencesQuery.data);
  }, [form, preferencesQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async (values: SettingsPreferences) => persistSettingsPreferences(values),
    onSuccess: (result: PersistedSettingsPreferences) => {
      lastSavedPreferencesRef.current = result.preferences;
      form.reset(result.preferences);
      setSaveState({
        tone: "success",
        message:
          result.persistenceScope === "remote"
            ? "Preferences saved successfully."
            : "Preferences saved locally for this browser session.",
      });
    },
    onError: (error) => {
      setSaveState({
        tone: "error",
        message: getApiErrorMessage(error),
      });
    },
  });

  const billingHref = process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL?.trim() || "/admin";

  const securityFacts = useMemo(
    () => [
      {
        label: "Auth provider",
        value: formatAuthProvider(process.env.NEXT_PUBLIC_AUTH_PROVIDER),
      },
      {
        label: "Access token attached",
        value: session?.accessToken ? "Yes" : "No",
      },
      {
        label: "Refresh token available",
        value: session?.refreshToken ? "Yes" : "No",
      },
    ],
    [session?.accessToken, session?.refreshToken],
  );

  function handleDiscard(): void {
    form.reset(lastSavedPreferencesRef.current);
    setSaveState({
      tone: "neutral",
      message: "Unsaved changes were discarded.",
    });
  }

  async function handleSave(values: SettingsPreferences): Promise<void> {
    setSaveState(null);
    await saveMutation.mutateAsync(values);
  }

  const hasUnsavedChanges = form.formState.isDirty;
  const isSubmitting = saveMutation.isPending;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Settings</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Profile, organization, and preferences</h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Manage safe account context details and retrieval defaults used by the chat experience.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Profile section">
          <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Profile</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">Email</dt>
              <dd className="text-[#2f2a46]">{session?.email ?? "Not available"}</dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">User ID</dt>
              <dd className="text-[#2f2a46]">{session?.userId ?? "Not available"}</dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">Role</dt>
              <dd className="text-[#2f2a46]">{role ?? "Not available"}</dd>
            </div>
          </dl>
        </section>

        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Organization section">
          <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Organization context</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">Organization name</dt>
              <dd className="text-[#2f2a46]">{session?.organizationName ?? "Not assigned"}</dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">Organization ID</dt>
              <dd className="text-[#2f2a46]">{session?.organizationId ?? "Not assigned"}</dd>
            </div>
            <div className="flex flex-col gap-1">
              <dt className="font-semibold text-[#5c5871]">Permission scope</dt>
              <dd className="text-[#2f2a46]">
                {isAdmin ? "Administrator controls are enabled." : "Standard member/viewer permissions."}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Security section">
          <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Security</h2>
          <dl className="space-y-3 text-sm">
            {securityFacts.map((fact) => (
              <div key={fact.label} className="flex items-center justify-between gap-4 rounded-lg border border-[#ebe8f7] px-3 py-2">
                <dt className="font-semibold text-[#5c5871]">{fact.label}</dt>
                <dd className={statusPill(fact.value === "Yes")}>{fact.value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-[#6a6780]">Sensitive token values are never displayed in the UI.</p>
        </section>

        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Billing and usage section">
          <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Billing and usage</h2>
          <p className="text-sm text-[#4d4963]">
            Review usage trends and billing-relevant activity from the administrative usage surface.
          </p>
          <div className="mt-4">
            <Link
              href={billingHref}
              className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Open billing/usage
            </Link>
          </div>
        </section>
      </div>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Preferences section">
        <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Preferences</h2>

        {preferencesQuery.isLoading ? (
          <p className="text-sm text-[#68647b]">Loading preferences...</p>
        ) : preferencesQuery.isError ? (
          <div className="space-y-3">
            <p className="text-sm text-rose-700">{getApiErrorMessage(preferencesQuery.error)}</p>
            <button
              type="button"
              onClick={() => {
                void preferencesQuery.refetch();
              }}
              className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50"
            >
              Retry
            </button>
          </div>
        ) : (
          <form onSubmit={form.handleSubmit(handleSave)} className="space-y-4" noValidate>
            <label className="block" htmlFor="defaultTopK">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                Default top-k
              </span>
              <input
                id="defaultTopK"
                type="number"
                min={settingsTopKBounds.min}
                max={settingsTopKBounds.max}
                step={1}
                {...form.register("defaultTopK", { valueAsNumber: true })}
                className="h-10 w-full max-w-[220px] rounded-lg border border-[#d2cee6] px-3 text-sm outline-none ring-[#3525cd]/20 focus:ring"
              />
              <p className="mt-1 text-xs text-[#6a6780]">
                Allowed range: {settingsTopKBounds.min} to {settingsTopKBounds.max}
              </p>
              {form.formState.errors.defaultTopK?.message ? (
                <p role="alert" className="mt-1 text-xs text-rose-700">
                  {form.formState.errors.defaultTopK.message}
                </p>
              ) : null}
            </label>

            <label className="flex items-start gap-2 rounded-lg border border-[#e0dced] bg-[#faf8ff] px-3 py-2 text-sm text-[#2d2a3f]">
              <input type="checkbox" {...form.register("rerankEnabled")} className="mt-0.5" />
              <span>Enable rerank by default for new chat queries</span>
            </label>

            <label className="flex items-start gap-2 rounded-lg border border-[#e0dced] bg-[#faf8ff] px-3 py-2 text-sm text-[#2d2a3f]">
              <input type="checkbox" {...form.register("developerMode")} className="mt-0.5" />
              <span>Enable developer/debug diagnostics in settings surfaces</span>
            </label>

            <fieldset className="space-y-2 rounded-lg border border-[#e0dced] bg-[#faf8ff] px-3 py-3">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Notifications</legend>
              <label className="flex items-center gap-2 text-sm text-[#2d2a3f]">
                <input type="checkbox" {...form.register("notifications.productUpdates")} />
                Product updates
              </label>
              <label className="flex items-center gap-2 text-sm text-[#2d2a3f]">
                <input type="checkbox" {...form.register("notifications.securityAlerts")} />
                Security alerts
              </label>
              <label className="flex items-center gap-2 text-sm text-[#2d2a3f]">
                <input type="checkbox" {...form.register("notifications.documentProcessing")} />
                Document processing updates
              </label>
            </fieldset>

            {saveState ? <p className={saveStateClassName(saveState)}>{saveState.message}</p> : null}

            {hasUnsavedChanges ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                You have unsaved changes.
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                disabled={!hasUnsavedChanges || isSubmitting}
                className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? "Saving..." : "Save preferences"}
              </button>
              <button
                type="button"
                onClick={handleDiscard}
                disabled={!hasUnsavedChanges || isSubmitting}
                className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Discard changes
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm" aria-label="Admin controls section">
        <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Admin-only controls</h2>
        {isAdmin ? (
          <div className="space-y-3">
            <p className="text-sm text-[#4d4963]">
              Administrative security and organization controls are available to owner/admin roles.
            </p>
            <Link
              href="/admin"
              className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Open admin surface
            </Link>
          </div>
        ) : (
          <ForbiddenState
            compact
            title="Admin controls restricted"
            description="Your current role does not permit viewing or modifying organization security controls."
            backHref="/dashboard"
            backLabel="Back to dashboard"
          />
        )}
      </section>
    </section>
  );
}
