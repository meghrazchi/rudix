"use client";

import { BadgeCheck, Bot, FileSearch, Lock, ShieldAlert } from "lucide-react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getSecurityCapabilities,
  getSecurityPosture,
} from "@/lib/api/security";
import { queryKeys } from "@/lib/api/query";
import {
  formatTimestamp,
  SectionHeader,
  DeploymentControlledBadge,
  SecurityPostureCard,
  type PostureCardProps,
} from "@/components/settings/security/securityShared";

export function AiPostureSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getSecurityCapabilities>;
}) {
  const t = useTranslations("settings.security");

  const postureQuery = useQuery({
    queryKey: queryKeys.security.posture,
    queryFn: getSecurityPosture,
    enabled: capabilities.postureEnabled,
    retry: false,
  });

  const postureCards = useMemo((): PostureCardProps[] => {
    const p = postureQuery.data;
    return [
      {
        icon: ShieldAlert,
        label: t("posture.promptInjection"),
        status: p?.prompt_injection_protection ?? null,
        detail: t("posture.promptInjectionDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: BadgeCheck,
        label: t("posture.citationValidation"),
        status: p?.citation_validation ?? null,
        detail: t("posture.citationValidationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: Lock,
        label: t("posture.tenantIsolation"),
        status: p?.tenant_isolation ?? null,
        detail: t("posture.tenantIsolationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: FileSearch,
        label: t("posture.outputValidation"),
        status: p?.output_validation ?? null,
        detail: t("posture.outputValidationDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
      {
        icon: Bot,
        label: t("posture.toolPolicy"),
        status: p?.tool_policy_enforced ?? null,
        detail: t("posture.toolPolicyDetail"),
        activeLabel: t("active"),
        inactiveLabel: t("inactive"),
        unknownLabel: t("unknown"),
      },
    ];
  }, [postureQuery.data, t]);

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6"
      aria-label="AI safety posture section"
    >
      <SectionHeader
        icon={Bot}
        title={t("posture.title")}
        badge={
          !capabilities.postureEnabled && (
            <DeploymentControlledBadge label={t("deploymentControlled")} />
          )
        }
      />

      {!capabilities.postureEnabled ? (
        <div className="space-y-3">
          {postureCards.map((card) => (
            <SecurityPostureCard key={card.label} {...card} />
          ))}
          <p className="pt-1 text-xs text-[#777587]">
            {t("posture.defaultNote")}
          </p>
        </div>
      ) : postureQuery.isLoading ? (
        <LoadingState compact title={t("posture.loading")} />
      ) : postureQuery.isError ? (
        <ErrorState
          compact
          error={postureQuery.error}
          description={getApiErrorMessage(postureQuery.error)}
          onRetry={() => {
            void postureQuery.refetch();
          }}
        />
      ) : (
        <div className="space-y-3">
          {postureCards.map((card) => (
            <SecurityPostureCard key={card.label} {...card} />
          ))}
          {postureQuery.data?.last_audit_at && (
            <p className="pt-1 text-xs text-[#777587]">
              {t("posture.lastAudit", {
                time: formatTimestamp(postureQuery.data.last_audit_at),
              })}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
