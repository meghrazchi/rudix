"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

export type SettingsTabId = "profile" | "organization" | "security" | "billing";

const VALID_TAB_IDS: readonly SettingsTabId[] = [
  "profile",
  "organization",
  "security",
  "billing",
];

const TAB_IDS: SettingsTabId[] = [
  "profile",
  "organization",
  "security",
  "billing",
];

export function useSettingsTab(): SettingsTabId {
  const searchParams = useSearchParams();
  const raw = searchParams.get("tab");
  return (VALID_TAB_IDS as readonly string[]).includes(raw ?? "")
    ? (raw as SettingsTabId)
    : "profile";
}

type SettingsTabsProps = {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
};

export function SettingsTabs({ activeTab, onTabChange }: SettingsTabsProps) {
  const t = useTranslations("settings.tabs");

  return (
    <div
      role="tablist"
      aria-label="Settings navigation"
      className="flex overflow-x-auto border-b border-[#d7d4e8]"
    >
      {TAB_IDS.map((id) => (
        <button
          key={id}
          id={`settings-tab-${id}`}
          role="tab"
          type="button"
          aria-selected={activeTab === id}
          aria-controls={`settings-tabpanel-${id}`}
          onClick={() => onTabChange(id)}
          className={[
            "px-5 py-3 text-sm font-semibold whitespace-nowrap transition-colors",
            "focus-visible:ring-2 focus-visible:ring-[#3525cd]/40 focus-visible:outline-none",
            activeTab === id
              ? "border-b-2 border-[#3525cd] text-[#3525cd]"
              : "border-b-2 border-transparent text-[#6a6780] hover:text-[#2d2a3f]",
          ].join(" ")}
        >
          {t(id)}
        </button>
      ))}
    </div>
  );
}
