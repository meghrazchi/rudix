"use client";

import { TrendingUp } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getBillingCapabilities,
  getBillingUsageSummary,
  type BillingDateRange,
} from "@/lib/api/billing";
import {
  formatCurrency,
  formatStorageGb,
  formatNumber,
  SectionHeader,
} from "@/components/settings/billing/billingShared";
import { queryKeys } from "@/lib/api/query";

export function UsageSummarySection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const t = useTranslations("settings.billing");
  const [dateRange, setDateRange] = useState<BillingDateRange>("30d");

  const dateRangeOptions: { id: BillingDateRange; labelKey: string }[] = [
    { id: "7d", labelKey: "usage.dateRange7d" },
    { id: "30d", labelKey: "usage.dateRange30d" },
    { id: "90d", labelKey: "usage.dateRange90d" },
    { id: "billing_period", labelKey: "usage.dateRangeBilling" },
  ];

  const usageQuery = useQuery({
    queryKey: queryKeys.billing.usage(dateRange),
    queryFn: () => getBillingUsageSummary(dateRange),
    enabled: capabilities.usageEnabled,
    retry: false,
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Usage summary section"
    >
      <div className="mb-6 flex items-center justify-between">
        <SectionHeader icon={TrendingUp} title={t("usage.title")} />
        <div
          className="ml-4 flex gap-1"
          role="group"
          aria-label={t("usage.dateRangeAriaLabel")}
        >
          {dateRangeOptions.map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setDateRange(opt.id)}
              aria-pressed={dateRange === opt.id}
              className={[
                "rounded-lg border px-3 py-1 text-xs font-semibold transition-colors",
                dateRange === opt.id
                  ? "border-[#3525cd] bg-[#3525cd] text-white"
                  : "border-[#d7d4e8] text-[#5c5871] hover:bg-[#f5f2ff]",
              ].join(" ")}
            >
              {t(opt.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {!capabilities.usageEnabled ? (
        <p className="text-sm text-[#777587]">{t("usage.unavailable")}</p>
      ) : usageQuery.isLoading ? (
        <LoadingState compact title={t("usage.loading")} />
      ) : usageQuery.isError ? (
        isApiClientError(usageQuery.error) &&
        usageQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void usageQuery.refetch();
            }}
          />
        ) : isApiClientError(usageQuery.error) &&
          usageQuery.error.status === 403 ? (
          <ForbiddenState
            compact
            title={t("usage.restrictedTitle")}
            description={t("usage.restrictedDesc")}
            backHref="/dashboard"
            backLabel={t("backToDashboard")}
          />
        ) : (
          <ErrorState
            compact
            error={usageQuery.error}
            description={getApiErrorMessage(usageQuery.error)}
            onRetry={() => {
              void usageQuery.refetch();
            }}
          />
        )
      ) : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3">
            {[
              {
                labelKey: "usage.questionsAsked",
                value: formatNumber(usageQuery.data?.questions_asked ?? null),
              },
              {
                labelKey: "usage.inputTokens",
                value: formatNumber(usageQuery.data?.input_tokens ?? null),
              },
              {
                labelKey: "usage.outputTokens",
                value: formatNumber(usageQuery.data?.output_tokens ?? null),
              },
              {
                labelKey: "usage.documentsUploaded",
                value: formatNumber(
                  usageQuery.data?.documents_uploaded ?? null,
                ),
              },
              {
                labelKey: "usage.indexedDocuments",
                value: formatNumber(usageQuery.data?.indexed_documents ?? null),
              },
              {
                labelKey: "usage.storageUsed",
                value: formatStorageGb(
                  usageQuery.data?.storage_used_gb ?? null,
                ),
              },
              {
                labelKey: "usage.evaluationRuns",
                value: formatNumber(usageQuery.data?.evaluation_runs ?? null),
              },
              {
                labelKey: "usage.agentRuns",
                value: formatNumber(usageQuery.data?.agent_runs ?? null),
              },
              {
                labelKey: "usage.connectorSyncs",
                value: formatNumber(
                  usageQuery.data?.connector_sync_jobs ?? null,
                ),
              },
            ].map(({ labelKey, value }) => (
              <div key={labelKey}>
                <p className="mb-0.5 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {t(labelKey)}
                </p>
                <p className="font-mono text-base font-semibold text-[#1b1b24]">
                  {value}
                </p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-3 gap-4 border-t border-[#e4e1ee] pt-5">
            <div className="text-center">
              <p className="mb-1 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                {t("usage.avgLatency")}
              </p>
              <p className="text-xl font-bold text-[#3525cd]">
                {usageQuery.data?.avg_latency_ms != null
                  ? `${Math.round(usageQuery.data.avg_latency_ms)}ms`
                  : "—"}
              </p>
            </div>
            <div className="border-x border-[#e4e1ee] text-center">
              <p className="mb-1 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                {t("usage.avgConfidence")}
              </p>
              <p className="text-xl font-bold text-[#3525cd]">
                {usageQuery.data?.avg_confidence != null
                  ? `${(usageQuery.data.avg_confidence * 100).toFixed(1)}%`
                  : "—"}
              </p>
            </div>
            <div className="text-center">
              <p className="mb-1 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                {t("usage.estLlmCost")}
              </p>
              <p className="text-xl font-bold text-[#3525cd]">
                {usageQuery.data?.estimated_llm_cost_usd != null
                  ? formatCurrency(usageQuery.data.estimated_llm_cost_usd)
                  : "—"}
              </p>
            </div>
          </div>
          {usageQuery.data?.estimated_llm_cost_usd != null && (
            <p className="mt-2 text-right text-[10px] text-[#aaa6b8]">
              {t("usage.llmCostNote")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
