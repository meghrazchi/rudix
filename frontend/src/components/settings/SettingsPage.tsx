"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import { UserProfilePage } from "@/components/user/UserProfilePage";
import {
  SettingsTabs,
  useSettingsTab,
  type SettingsTabId,
} from "@/components/settings/SettingsTabs";

// Only the active tab loads; Profile stays static (R07-03).
const tabLoading = () => <SkeletonBlock rows={6} />;

const OrganizationSettingsTab = dynamic(
  () =>
    import("@/components/settings/OrganizationSettingsTab").then(
      (module) => module.OrganizationSettingsTab,
    ),
  { loading: tabLoading },
);
const SecuritySettingsTab = dynamic(
  () =>
    import("@/components/settings/SecuritySettingsTab").then(
      (module) => module.SecuritySettingsTab,
    ),
  { loading: tabLoading },
);
const BillingSettingsTab = dynamic(
  () =>
    import("@/components/settings/BillingSettingsTab").then(
      (module) => module.BillingSettingsTab,
    ),
  { loading: tabLoading },
);

export function SettingsPage() {
  const t = useTranslations("settings");
  const router = useRouter();

  const activeTab = useSettingsTab();

  function handleTabChange(tab: SettingsTabId): void {
    router.replace(`/settings?tab=${tab}`, { scroll: false });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("rudixSettings")}
        </p>
        {/* The app shell top bar owns the page's single <h1>. */}
        <h2 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("title")}
        </h2>
        <p className="max-w-3xl text-sm text-[#68647b]">{t("description")}</p>
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
          <UserProfilePage />
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
          className="focus-visible:outline-none"
        >
          <SecuritySettingsTab />
        </div>
      )}

      {activeTab === "billing" && (
        <div
          id="settings-tabpanel-billing"
          role="tabpanel"
          aria-labelledby="settings-tab-billing"
          tabIndex={0}
          className="focus-visible:outline-none"
        >
          <BillingSettingsTab />
        </div>
      )}
    </section>
  );
}
