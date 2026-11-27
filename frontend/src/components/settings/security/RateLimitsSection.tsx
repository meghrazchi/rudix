"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  SectionHeader,
  DeploymentControlledBadge,
} from "@/components/settings/security/securityShared";

export function RateLimitsSection() {
  const t = useTranslations("settings.security");

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="Rate limits section"
    >
      <SectionHeader
        icon={AlertTriangle}
        title={t("rateLimits.title")}
        badge={<DeploymentControlledBadge label={t("deploymentControlled")} />}
      />
      <p className="mb-4 text-sm text-[#777587]">{t("rateLimits.desc")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {[
          {
            label: t("rateLimits.uploadRateLimit"),
            description: t("rateLimits.deploymentControlledValue"),
          },
          {
            label: t("rateLimits.chatRateLimit"),
            description: t("rateLimits.deploymentControlledValue"),
          },
          {
            label: t("rateLimits.deleteRateLimit"),
            description: t("rateLimits.deploymentControlledValue"),
          },
          {
            label: t("rateLimits.evalRateLimit"),
            description: t("rateLimits.deploymentControlledValue"),
          },
          {
            label: t("rateLimits.apiKeyRateLimit"),
            description: t("rateLimits.notYetAvailable"),
          },
          {
            label: t("rateLimits.agentRateLimit"),
            description: t("rateLimits.notYetAvailable"),
          },
        ].map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between rounded-lg border border-dashed border-[#c7c4d8] px-4 py-3 opacity-80"
          >
            <span className="text-sm font-semibold text-[#1b1b24]">
              {row.label}
            </span>
            <span className="text-xs text-[#777587]">{row.description}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
