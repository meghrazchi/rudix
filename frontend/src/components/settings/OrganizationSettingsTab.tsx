"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { ChunkingProfilesSection } from "@/components/settings/ChunkingProfilesSection";
import { PromptTemplatesSection } from "@/components/settings/PromptTemplatesSection";
import { DangerZoneSection } from "@/components/settings/organization/DangerZoneSection";
import { IngestionDefaultsSection } from "@/components/settings/organization/IngestionDefaultsSection";
import { OrgProfileSection } from "@/components/settings/organization/OrgProfileSection";
import { WorkspaceDefaultsSection } from "@/components/settings/organization/WorkspaceDefaultsSection";
import { isAdminLikeRole } from "@/components/settings/organization/orgSettingsShared";
import { getOrganizationCapabilities } from "@/lib/api/organization";
import { useAuthSession } from "@/lib/use-auth-session";
import { publicEnv } from "@/lib/public-env";

export function OrganizationSettingsTab() {
  const t = useTranslations("settings.organization");
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLikeRole(role);
  const isOwner = role === "owner";

  const capabilities = useMemo(() => getOrganizationCapabilities(), []);

  const billingHref =
    publicEnv(
      "NEXT_PUBLIC_SETTINGS_BILLING_URL",
      process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL,
    )?.trim() || "/admin";

  return (
    <div className="space-y-6">
      <OrgProfileSection
        capabilities={capabilities}
        isAdmin={isAdmin}
        session={session}
        billingHref={billingHref}
      />

      <WorkspaceDefaultsSection capabilities={capabilities} isAdmin={isAdmin} />

      <IngestionDefaultsSection capabilities={capabilities} isAdmin={isAdmin} />

      {/* ── 5. Chunking Profiles ── */}
      <ChunkingProfilesSection />

      {/* ── 6. Prompt Templates ── */}
      <PromptTemplatesSection />

      {/* ── 7. Admin Controls ── */}
      <section
        className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
        aria-label="Admin controls section"
      >
        <h2 className="mb-3 text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          {t("admin.title")}
        </h2>
        {isAdmin ? (
          <div className="space-y-3">
            <p className="text-sm text-[#4d4963]">{t("admin.desc")}</p>
            <Link
              href="/admin"
              className="inline-flex rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              {t("admin.openAdmin")}
            </Link>
          </div>
        ) : (
          <ForbiddenState
            compact
            title={t("admin.restrictedTitle")}
            description={t("admin.restrictedDesc")}
            backHref="/dashboard"
            backLabel={t("backToDashboard")}
          />
        )}
      </section>

      {isOwner && (
        <DangerZoneSection capabilities={capabilities} session={session} />
      )}
    </div>
  );
}
