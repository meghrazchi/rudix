"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { usePermissions } from "@/lib/use-permissions";
import { nextTabForKey } from "@/lib/tablist-keyboard";
import { RoleMatrixTab } from "@/components/admin/permissions/RoleMatrixTab";
import { ResourceAccessTab } from "@/components/admin/permissions/ResourceAccessTab";
import { ConflictsTab } from "@/components/admin/permissions/ConflictsTab";
import { AccessDebuggerTab } from "@/components/admin/permissions/AccessDebuggerTab";

type Tab =
  | "role-matrix"
  | "resource-grants"
  | "resource-denies"
  | "conflicts"
  | "access-debugger";

// ── Main page ──────────────────────────────────────────────────────────────────

export function AdminPermissionsPage() {
  const t = useTranslations("adminPermissions");
  const { hasPermission } = usePermissions();
  const canView = hasPermission("roles:view");
  const canManage = hasPermission("roles:manage");

  const [activeTab, setActiveTab] = useState<Tab>("role-matrix");

  if (!canView) {
    return (
      <ForbiddenState
        title={t("title")}
        description={t("errors.pagePermissionRequired")}
        backHref="/dashboard"
      />
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "role-matrix", label: t("tabs.roleMatrix") },
    { id: "resource-grants", label: t("tabs.resourceGrants") },
    { id: "resource-denies", label: t("tabs.resourceDenies") },
    { id: "conflicts", label: t("tabs.conflicts") },
    { id: "access-debugger", label: t("tabs.accessDebugger") },
  ];

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8">
      <div>
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          {t("adminEyebrow")}
        </p>
        <h1 className="text-2xl font-extrabold text-[#2a2640]">{t("title")}</h1>
        <p className="mt-1 text-sm text-[#68647b]">{t("description")}</p>
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>{t("securityNoteLabel")}</strong> {t("securityNote")}
      </div>

      <div className="border-b border-[#d7d4e8]">
        <div
          role="tablist"
          className="-mb-px flex gap-6 overflow-x-auto"
          aria-label={t("tabs.ariaLabel")}
          onKeyDown={(event) => {
            const next = nextTabForKey(
              tabs.map((tab) => tab.id),
              activeTab,
              event.key,
              document.documentElement.dir === "rtl" ? "rtl" : "ltr",
            );
            if (!next) return;
            event.preventDefault();
            setActiveTab(next);
            document.getElementById(`permissions-tab-${next}`)?.focus();
          }}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              id={`permissions-tab-${tab.id}`}
              role="tab"
              type="button"
              aria-selected={activeTab === tab.id}
              aria-controls="permissions-tabpanel"
              tabIndex={activeTab === tab.id ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              className={`border-b-2 pb-3 text-sm font-semibold transition ${
                activeTab === tab.id
                  ? "border-[#3525cd] text-[#3525cd]"
                  : "border-transparent text-[#68647b] hover:text-[#2a2640]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div
        id="permissions-tabpanel"
        role="tabpanel"
        aria-labelledby={`permissions-tab-${activeTab}`}
      >
        {activeTab === "role-matrix" && <RoleMatrixTab canManage={canManage} />}
        {activeTab === "resource-grants" && (
          <ResourceAccessTab kind="grant" canManage={canManage} />
        )}
        {activeTab === "resource-denies" && (
          <ResourceAccessTab kind="deny" canManage={canManage} />
        )}
        {activeTab === "conflicts" && <ConflictsTab canManage={canManage} />}
        {activeTab === "access-debugger" && <AccessDebuggerTab />}
      </div>
    </div>
  );
}
