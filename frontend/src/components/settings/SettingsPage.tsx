"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { OrganizationSettingsTab } from "@/components/settings/OrganizationSettingsTab";
import { ProfileSettingsTab } from "@/components/settings/ProfileSettingsTab";
import {
  SettingsTabs,
  useSettingsTab,
  type SettingsTabId,
} from "@/components/settings/SettingsTabs";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { useAuthSession } from "@/lib/use-auth-session";

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

export function SettingsPage() {
  const router = useRouter();
  const { state, signOut } = useAuthSession();
  const session = state.session;
  const [isSigningOut, setIsSigningOut] = useState(false);

  const activeTab = useSettingsTab();

  const billingHref =
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL?.trim() || "/admin";

  const securityFacts = useMemo(
    () => [
      {
        label: "Auth provider",
        value: formatAuthProvider(getFrontendRuntimeConfig().authProviderRaw),
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

  async function handleSignOut(): Promise<void> {
    setIsSigningOut(true);
    try {
      await signOut();
      router.replace("/login?reason=signed_out");
    } finally {
      setIsSigningOut(false);
    }
  }

  function handleTabChange(tab: SettingsTabId): void {
    router.replace(`/settings?tab=${tab}`, { scroll: false });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Rudix Settings
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Settings
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Manage your account, organization, security, and billing settings.
        </p>
      </header>

      <SettingsTabs activeTab={activeTab} onTabChange={handleTabChange} />

      {activeTab === "profile" && (
        <div
          id="settings-tabpanel-profile"
          role="tabpanel"
          aria-labelledby="settings-tab-profile"
          tabIndex={0}
          className="focus-visible:outline-none"
        >
          <ProfileSettingsTab />
        </div>
      )}

      {activeTab === "organization" && (
        <div
          id="settings-tabpanel-organization"
          role="tabpanel"
          aria-labelledby="settings-tab-organization"
          tabIndex={0}
          className="focus-visible:outline-none"
        >
          <OrganizationSettingsTab />
        </div>
      )}

      {activeTab === "security" && (
        <div
          id="settings-tabpanel-security"
          role="tabpanel"
          aria-labelledby="settings-tab-security"
          tabIndex={0}
          className="space-y-6 focus-visible:outline-none"
        >
          <section
            className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
            aria-label="Security section"
          >
            <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
              Security
            </h2>
            <dl className="space-y-3 text-sm">
              {securityFacts.map((fact) => (
                <div
                  key={fact.label}
                  className="flex items-center justify-between gap-4 rounded-lg border border-[#ebe8f7] px-3 py-2"
                >
                  <dt className="font-semibold text-[#5c5871]">{fact.label}</dt>
                  <dd className={statusPill(fact.value === "Yes")}>
                    {fact.value}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-xs text-[#6a6780]">
              Sensitive token values are never displayed in the UI.
            </p>
            <div className="mt-4 border-t border-[#ebe8f7] pt-3">
              <button
                type="button"
                onClick={() => {
                  void handleSignOut();
                }}
                disabled={isSigningOut}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSigningOut ? "Signing out..." : "Sign out"}
              </button>
            </div>
          </section>
        </div>
      )}

      {activeTab === "billing" && (
        <div
          id="settings-tabpanel-billing"
          role="tabpanel"
          aria-labelledby="settings-tab-billing"
          tabIndex={0}
          className="space-y-6 focus-visible:outline-none"
        >
          <section
            className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
            aria-label="Billing and usage section"
          >
            <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
              Billing and usage
            </h2>
            <p className="text-sm text-[#4d4963]">
              Review usage trends and billing-relevant activity from the
              administrative usage surface.
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
      )}
    </section>
  );
}
