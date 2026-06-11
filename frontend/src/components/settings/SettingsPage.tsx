"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { BillingSettingsTab } from "@/components/settings/BillingSettingsTab";
import { OrganizationSettingsTab } from "@/components/settings/OrganizationSettingsTab";
import { ProfileSettingsTab } from "@/components/settings/ProfileSettingsTab";
import { SecuritySettingsTab } from "@/components/settings/SecuritySettingsTab";
import {
  SettingsTabs,
  useSettingsTab,
  type SettingsTabId,
} from "@/components/settings/SettingsTabs";

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
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          {t("title")}
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          {t("description")}
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
