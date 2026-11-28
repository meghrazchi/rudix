"use client";

import { ExternalLink, FileText } from "lucide-react";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getBillingCapabilities,
  getBillingPlanInfo,
  isBillingEndpointUnavailableError,
} from "@/lib/api/billing";
import { usePermissions } from "@/lib/use-permissions";
import {
  trimToNull,
  DeploymentControlledBadge,
} from "@/components/settings/billing/billingShared";
import { queryKeys } from "@/lib/api/query";
import { PlanCard } from "@/components/settings/billing/BillingPlanCard";
import { UsageSummarySection } from "@/components/settings/billing/UsageSummarySection";
import { QuotaSection } from "@/components/settings/billing/QuotaSection";
import { InvoiceSection } from "@/components/settings/billing/InvoiceSection";
import {
  BillingContactSection,
  BillingPortalFallback,
  BillingNotificationsInfo,
} from "@/components/settings/billing/BillingContactSection";
import { publicEnv } from "@/lib/public-env";

export function BillingSettingsTab() {
  const t = useTranslations("settings.billing");
  const { hasPermission } = usePermissions();
  const canViewBilling =
    hasPermission("billing:view") || hasPermission("billing:manage");
  const canManageBilling = hasPermission("billing:manage");

  const capabilities = useMemo(() => getBillingCapabilities(), []);

  const billingPortalUrl = trimToNull(
    publicEnv(
      "NEXT_PUBLIC_SETTINGS_BILLING_URL",
      process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL,
    ),
  );

  const planQuery = useQuery({
    queryKey: queryKeys.billing.plan,
    queryFn: getBillingPlanInfo,
    enabled: capabilities.planEnabled && canViewBilling,
    retry: false,
  });

  if (!canViewBilling) {
    return (
      <ForbiddenState
        compact
        title={t("restricted")}
        description={t("restrictedDesc")}
        backHref="/dashboard"
        backLabel={t("backToDashboard")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left column: Plan + Alerts + Contact */}
        <div className="space-y-6 lg:col-span-4">
          {capabilities.planEnabled ? (
            planQuery.isLoading ? (
              <section className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm">
                <LoadingState compact title={t("plan.loading")} />
              </section>
            ) : planQuery.isError ? (
              <section className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm">
                {isApiClientError(planQuery.error) &&
                planQuery.error.status === 429 ? (
                  <RateLimitState
                    compact
                    onRetry={() => {
                      void planQuery.refetch();
                    }}
                  />
                ) : isBillingEndpointUnavailableError(planQuery.error) ? (
                  <BillingPortalFallback
                    portalUrl={billingPortalUrl}
                    deploymentControlledLabel={t("deploymentControlled")}
                  />
                ) : (
                  <ErrorState
                    compact
                    error={planQuery.error}
                    description={getApiErrorMessage(planQuery.error)}
                    onRetry={() => {
                      void planQuery.refetch();
                    }}
                  />
                )}
              </section>
            ) : planQuery.data ? (
              <PlanCard
                plan={planQuery.data}
                canManageBilling={canManageBilling}
                billingPortalUrl={billingPortalUrl}
                deploymentControlledLabel={t("deploymentControlled")}
              />
            ) : null
          ) : (
            <section className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm">
              <div className="mb-3 flex items-center gap-3">
                <FileText
                  size={20}
                  className="text-[#3525cd]"
                  aria-hidden="true"
                />
                <h2 className="text-lg font-semibold text-[#1b1b24]">
                  {t("plan.title")}
                </h2>
                <DeploymentControlledBadge label={t("deploymentControlled")} />
              </div>
              <p className="text-sm text-[#777587]">{t("plan.unavailable")}</p>
              {billingPortalUrl && (
                <a
                  href={billingPortalUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
                >
                  {t("plan.openBillingPortal")}
                  <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
            </section>
          )}

          <BillingNotificationsInfo />
          <BillingContactSection
            capabilities={capabilities}
            canViewBilling={canViewBilling}
          />
        </div>

        {/* Right column: Usage + Quotas */}
        <div className="space-y-6 lg:col-span-8">
          <UsageSummarySection capabilities={capabilities} />
          <QuotaSection capabilities={capabilities} />
        </div>
      </div>

      {/* Invoices — full width */}
      <InvoiceSection capabilities={capabilities} />
    </div>
  );
}
