"use client";

import { Gauge } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { QuotaProgress } from "@/components/settings/QuotaProgress";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { getBillingCapabilities, getBillingQuotas } from "@/lib/api/billing";
import { SectionHeader } from "@/components/settings/billing/billingShared";
import { queryKeys } from "@/lib/api/query";

export function QuotaSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const t = useTranslations("settings.billing");

  const quotasQuery = useQuery({
    queryKey: queryKeys.billing.quotas,
    queryFn: getBillingQuotas,
    enabled: capabilities.quotasEnabled,
    retry: false,
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Quota and limits section"
    >
      <SectionHeader icon={Gauge} title={t("quotas.title")} />

      {!capabilities.quotasEnabled ? (
        <p className="text-sm text-[#777587]">{t("quotas.unavailable")}</p>
      ) : quotasQuery.isLoading ? (
        <LoadingState compact title={t("quotas.loading")} />
      ) : quotasQuery.isError ? (
        isApiClientError(quotasQuery.error) &&
        quotasQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void quotasQuery.refetch();
            }}
          />
        ) : (
          <ErrorState
            compact
            error={quotasQuery.error}
            description={getApiErrorMessage(quotasQuery.error)}
            onRetry={() => {
              void quotasQuery.refetch();
            }}
          />
        )
      ) : (quotasQuery.data ?? []).length === 0 ? (
        <p className="text-sm text-[#777587]">{t("quotas.noData")}</p>
      ) : (
        <div className="space-y-5">
          {(quotasQuery.data ?? []).map((quota) => (
            <QuotaProgress
              key={quota.resource}
              label={quota.label}
              used={quota.used}
              total={quota.limit}
              unit={quota.unit}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ── Invoice History ───────────────────────────────────────────────────────────
