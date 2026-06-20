"use client";

import {
  AlertTriangle,
  CreditCard,
  Download,
  ExternalLink,
  FileText,
  Gauge,
  ReceiptText,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { QuotaProgress } from "@/components/settings/QuotaProgress";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getBillingCapabilities,
  getBillingContact,
  getBillingPlanInfo,
  getBillingUsageSummary,
  getBillingQuotas,
  getInvoices,
  isBillingEndpointUnavailableError,
  type BillingDateRange,
  type BillingPlanInfo,
  type BillingPlanStatus,
  type InvoiceStatus,
} from "@/lib/api/billing";
import { usePermissions } from "@/lib/use-permissions";

// ── Helpers ───────────────────────────────────────────────────────────────────

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

function formatCurrency(usd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(usd);
}

function formatStorageGb(gb: number | null): string {
  if (gb === null) return "—";
  if (gb >= 1000) return `${(gb / 1000).toFixed(1)} TB`;
  return `${gb.toFixed(1)} GB`;
}

function formatNumber(n: number | null): string {
  if (n === null) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({
  icon: Icon,
  title,
  badge,
}: {
  icon: React.ElementType;
  title: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Icon size={20} className="text-[#3525cd]" aria-hidden="true" />
        <h2 className="text-lg font-semibold text-[#1b1b24]">{title}</h2>
      </div>
      {badge}
    </div>
  );
}

function DeploymentControlledBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
      {label}
    </span>
  );
}

function PlanStatusBadge({ status }: { status: BillingPlanStatus }) {
  const t = useTranslations("settings.billing.plan");

  const map: Record<BillingPlanStatus, { labelKey: string; cls: string }> = {
    active: {
      labelKey: "statusActive",
      cls: "bg-emerald-100 text-emerald-800 border-emerald-200",
    },
    trialing: {
      labelKey: "statusTrialing",
      cls: "bg-sky-100 text-sky-800 border-sky-200",
    },
    past_due: {
      labelKey: "statusPastDue",
      cls: "bg-amber-100 text-amber-800 border-amber-200",
    },
    cancelled: {
      labelKey: "statusCancelled",
      cls: "bg-rose-100 text-rose-800 border-rose-200",
    },
    free: {
      labelKey: "statusFree",
      cls: "bg-slate-100 text-slate-700 border-slate-200",
    },
    self_hosted: {
      labelKey: "statusSelfHosted",
      cls: "bg-slate-100 text-slate-700 border-slate-200",
    },
    unknown: {
      labelKey: "statusUnknown",
      cls: "bg-slate-100 text-slate-700 border-slate-200",
    },
  };
  const { labelKey, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wider uppercase ${cls}`}
    >
      {t(labelKey)}
    </span>
  );
}

function PlanStatusCallout({ plan }: { plan: BillingPlanInfo }) {
  const t = useTranslations("settings.billing.plan");

  const tones: Record<BillingPlanStatus, string> = {
    active: "border-emerald-200 bg-emerald-50 text-emerald-900",
    trialing: "border-sky-200 bg-sky-50 text-sky-900",
    past_due: "border-amber-200 bg-amber-50 text-amber-900",
    cancelled: "border-rose-200 bg-rose-50 text-rose-900",
    free: "border-slate-200 bg-slate-50 text-slate-900",
    self_hosted: "border-slate-200 bg-slate-50 text-slate-900",
    unknown: "border-slate-200 bg-slate-50 text-slate-900",
  };

  const titleKeys: Record<BillingPlanStatus, string> = {
    active: "calloutActiveTitle",
    trialing: "calloutTrialingTitle",
    past_due: "calloutPastDueTitle",
    cancelled: "calloutCancelledTitle",
    free: "calloutFreeTitle",
    self_hosted: "calloutSelfHostedTitle",
    unknown: "calloutUnknownTitle",
  };

  const bodyKeys: Record<BillingPlanStatus, string> = {
    active: "calloutActiveBody",
    trialing: plan.trial_end_date
      ? "calloutTrialingBodyDate"
      : "calloutTrialingBody",
    past_due: "calloutPastDueBody",
    cancelled: "calloutCancelledBody",
    free: "calloutFreeBody",
    self_hosted: "calloutSelfHostedBody",
    unknown: "calloutUnknownBody",
  };

  const bodyParams =
    plan.status === "trialing" && plan.trial_end_date
      ? { date: formatDate(plan.trial_end_date) }
      : {};

  return (
    <div className={`rounded-xl border px-4 py-3 ${tones[plan.status]}`}>
      <p className="text-sm font-semibold">{t(titleKeys[plan.status])}</p>
      <p className="mt-0.5 text-xs opacity-90">
        {t(bodyKeys[plan.status], bodyParams as Record<string, string>)}
      </p>
    </div>
  );
}

function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  const t = useTranslations("settings.billing.invoices");

  const map: Record<InvoiceStatus, { labelKey: string; cls: string }> = {
    paid: { labelKey: "statusPaid", cls: "bg-emerald-100 text-emerald-800" },
    open: { labelKey: "statusOpen", cls: "bg-sky-100 text-sky-800" },
    void: { labelKey: "statusVoid", cls: "bg-slate-100 text-slate-600" },
    uncollectible: {
      labelKey: "statusUncollectible",
      cls: "bg-rose-100 text-rose-800",
    },
  };
  const { labelKey, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(labelKey).toUpperCase()}
    </span>
  );
}

// ── Plan Card ─────────────────────────────────────────────────────────────────

function PlanCard({
  plan,
  canManageBilling,
  billingPortalUrl,
  deploymentControlledLabel: _deploymentControlledLabel,
}: {
  plan: BillingPlanInfo;
  canManageBilling: boolean;
  billingPortalUrl: string | null;
  deploymentControlledLabel: string;
}) {
  const t = useTranslations("settings.billing.plan");

  const manageUrl =
    billingPortalUrl ??
    trimToNull(process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL);

  const seatsUsed = plan.seats_used ?? 0;
  const seatsTotal = plan.seats_included;
  const storageUsedGb = plan.storage_used_gb ?? 0;
  const storageTotalGb = plan.storage_included_gb;

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Current plan section"
    >
      <div className="mb-4 flex items-start justify-between">
        <div>
          <p className="mb-1 text-[10px] font-bold tracking-widest text-[#5d58a8] uppercase">
            {t("title")}
          </p>
          <h3 className="text-2xl font-extrabold text-[#3525cd]">
            {plan.plan_name}
          </h3>
        </div>
        <PlanStatusBadge status={plan.status} />
      </div>

      <div className="mb-5">
        <PlanStatusCallout plan={plan} />
      </div>

      <dl className="mb-5 space-y-3">
        {plan.billing_cycle && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">{t("billingCycle")}</dt>
            <dd className="text-sm font-semibold text-[#1b1b24] capitalize">
              {plan.billing_cycle}
            </dd>
          </div>
        )}
        {plan.renewal_date && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">{t("renewsOn")}</dt>
            <dd className="text-sm font-semibold text-[#1b1b24]">
              {formatDate(plan.renewal_date)}
            </dd>
          </div>
        )}
        {plan.status === "trialing" && plan.trial_end_date && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">{t("trialEnds")}</dt>
            <dd className="text-sm font-semibold text-sky-700">
              {formatDate(plan.trial_end_date)}
            </dd>
          </div>
        )}
      </dl>

      <div className="mb-6 space-y-4">
        <QuotaProgress
          label={t("seats")}
          used={seatsUsed}
          total={seatsTotal}
          unit="seats"
        />
        <QuotaProgress
          label={t("monthlyQuestions")}
          used={plan.monthly_questions_used ?? 0}
          total={plan.monthly_questions_included}
          unit="questions"
        />
        <QuotaProgress
          label={t("storage")}
          used={storageUsedGb}
          total={storageTotalGb}
          unit="GB"
        />
      </div>

      <div className="space-y-2">
        {manageUrl ? (
          <a
            href={manageUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8]"
            aria-label={t("manageAriaLabel")}
          >
            {t("manageSubscription")}
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        ) : (
          <p className="text-center text-xs text-[#777587]">
            {t("noPortalUrl")}
          </p>
        )}
        {canManageBilling && manageUrl && (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <a
              href={manageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-3 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
            >
              {t("upgradePlan")}
            </a>
            <a
              href={manageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-3 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
            >
              {t("downgradePlan")}
            </a>
          </div>
        )}
      </div>

      {canManageBilling && plan.can_cancel_plan && (
        <p className="mt-3 text-center text-xs text-[#777587]">
          {t("cancelHint")}
        </p>
      )}
      <p className="mt-2 text-center text-[10px] text-[#aaa6b8]">
        {t("secureNote")}
      </p>
    </section>
  );
}

// ── Usage Summary ─────────────────────────────────────────────────────────────

function UsageSummarySection({
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
    queryKey: ["billing", "usage", dateRange],
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

// ── Quota Cards ───────────────────────────────────────────────────────────────

function QuotaSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const t = useTranslations("settings.billing");

  const quotasQuery = useQuery({
    queryKey: ["billing", "quotas"],
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

function InvoiceSection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const t = useTranslations("settings.billing");

  const invoicesQuery = useQuery({
    queryKey: ["billing", "invoices"],
    queryFn: getInvoices,
    enabled: capabilities.invoicesEnabled,
    retry: false,
  });

  return (
    <section
      className="overflow-hidden rounded-2xl border border-[#c7c4d8] bg-white shadow-sm"
      aria-label="Invoice history section"
    >
      <div className="flex items-center justify-between border-b border-[#e4e1ee] px-6 py-4">
        <div className="flex items-center gap-3">
          <ReceiptText
            size={20}
            className="text-[#3525cd]"
            aria-hidden="true"
          />
          <h2 className="text-lg font-semibold text-[#1b1b24]">
            {t("invoices.title")}
          </h2>
        </div>
      </div>

      {!capabilities.invoicesEnabled ? (
        <div className="p-6">
          <p className="text-sm text-[#777587]">{t("invoices.unavailable")}</p>
        </div>
      ) : invoicesQuery.isLoading ? (
        <div className="p-6">
          <LoadingState compact title={t("invoices.loading")} />
        </div>
      ) : invoicesQuery.isError ? (
        <div className="p-6">
          {isApiClientError(invoicesQuery.error) &&
          invoicesQuery.error.status === 429 ? (
            <RateLimitState
              compact
              onRetry={() => {
                void invoicesQuery.refetch();
              }}
            />
          ) : (
            <ErrorState
              compact
              error={invoicesQuery.error}
              description={getApiErrorMessage(invoicesQuery.error)}
              onRetry={() => {
                void invoicesQuery.refetch();
              }}
            />
          )}
        </div>
      ) : (invoicesQuery.data ?? []).length === 0 ? (
        <div className="p-6">
          <p className="text-sm text-[#777587]">{t("invoices.noInvoices")}</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f5f2ff] text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
              <tr>
                <th className="px-6 py-3">{t("invoices.invoiceId")}</th>
                <th className="px-6 py-3">{t("invoices.date")}</th>
                <th className="px-6 py-3">{t("invoices.amount")}</th>
                <th className="px-6 py-3">{t("invoices.status")}</th>
                <th className="px-6 py-3 text-right">{t("invoices.action")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e4e1ee]">
              {(invoicesQuery.data ?? []).map((inv) => (
                <tr
                  key={inv.id}
                  className="transition-colors hover:bg-[#f5f2ff]/40"
                >
                  <td className="px-6 py-3 font-mono text-xs text-[#464555]">
                    {inv.id}
                  </td>
                  <td className="px-6 py-3 text-[#1b1b24]">
                    {formatDate(inv.date)}
                  </td>
                  <td className="px-6 py-3 font-semibold text-[#1b1b24]">
                    {formatCurrency(inv.amount_usd)}
                  </td>
                  <td className="px-6 py-3">
                    <InvoiceStatusBadge status={inv.status} />
                  </td>
                  <td className="px-6 py-3 text-right">
                    {inv.download_url ? (
                      <a
                        href={inv.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={t("invoices.downloadAriaLabel", {
                          id: inv.id,
                        })}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        <Download size={14} aria-hidden="true" />
                        {t("invoices.download")}
                      </a>
                    ) : (
                      <span className="text-xs text-[#aaa6b8]">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Portal Fallback ───────────────────────────────────────────────────────────

function BillingPortalFallback({
  portalUrl,
  deploymentControlledLabel,
}: {
  portalUrl: string | null;
  deploymentControlledLabel: string;
}) {
  const t = useTranslations("settings.billing.portal");

  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm"
      aria-label="Billing portal section"
    >
      <div className="mb-3 flex items-center gap-3">
        <CreditCard size={20} className="text-[#3525cd]" aria-hidden="true" />
        <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          {t("title")}
        </h2>
        <DeploymentControlledBadge label={deploymentControlledLabel} />
      </div>
      <p className="mb-4 text-sm text-[#4d4963]">{t("desc")}</p>
      {portalUrl ? (
        <a
          href={portalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
        >
          {t("openPortal")}
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      ) : (
        <p className="text-sm text-[#777587]">{t("noPortalUrl")}</p>
      )}
    </section>
  );
}

// ── Billing Notifications Info ────────────────────────────────────────────────

function BillingNotificationsInfo() {
  const t = useTranslations("settings.billing.alerts");

  const alerts = [
    { labelKey: "quota80", descKey: "quota80Desc" },
    { labelKey: "quota90", descKey: "quota90Desc" },
    { labelKey: "quotaExceeded", descKey: "quotaExceededDesc" },
    { labelKey: "failedPayments", descKey: "failedPaymentsDesc" },
    { labelKey: "invoiceAvailable", descKey: "invoiceAvailableDesc" },
  ];

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Billing notifications section"
    >
      <SectionHeader icon={AlertTriangle} title={t("title")} />
      <div className="space-y-3">
        {alerts.map(({ labelKey, descKey }) => (
          <div
            key={labelKey}
            className="flex items-start gap-3 rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
          >
            <Zap
              size={14}
              className="mt-0.5 shrink-0 text-[#3525cd]"
              aria-hidden="true"
            />
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">
                {t(labelKey)}
              </p>
              <p className="text-xs text-[#464555]">{t(descKey)}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-[#777587]">{t("deliveryNote")}</p>
    </section>
  );
}

function BillingContactSection({
  capabilities,
  canViewBilling,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
  canViewBilling: boolean;
}) {
  const t = useTranslations("settings.billing");

  const contactQuery = useQuery({
    queryKey: ["billing", "contact"],
    queryFn: getBillingContact,
    enabled: capabilities.billingContactEnabled && canViewBilling,
    retry: false,
  });

  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Billing contact section"
    >
      <SectionHeader icon={CreditCard} title={t("contact.title")} />

      {!capabilities.billingContactEnabled ? (
        <p className="text-sm text-[#777587]">{t("contact.unavailable")}</p>
      ) : contactQuery.isLoading ? (
        <LoadingState compact title={t("contact.loading")} />
      ) : contactQuery.isError ? (
        isApiClientError(contactQuery.error) &&
        contactQuery.error.status === 429 ? (
          <RateLimitState
            compact
            onRetry={() => {
              void contactQuery.refetch();
            }}
          />
        ) : (
          <ErrorState
            compact
            error={contactQuery.error}
            description={getApiErrorMessage(contactQuery.error)}
            onRetry={() => {
              void contactQuery.refetch();
            }}
          />
        )
      ) : (
        <div className="space-y-4">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              {
                labelKey: "contact.billingContact",
                value:
                  contactQuery.data?.name ?? contactQuery.data?.email ?? "—",
              },
              {
                labelKey: "contact.email",
                value: contactQuery.data?.email ?? "—",
              },
              {
                labelKey: "contact.address",
                value:
                  contactQuery.data?.address_line1 ??
                  contactQuery.data?.address_line2 ??
                  t("contact.addressDefault"),
              },
              {
                labelKey: "contact.paymentMethod",
                value:
                  contactQuery.data?.payment_method_summary ??
                  t("contact.paymentMethodDefault"),
              },
            ].map(({ labelKey, value }) => (
              <div
                key={labelKey}
                className="rounded-xl border border-[#ebe8f7] bg-[#f8f7ff] px-4 py-3"
              >
                <dt className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {t(labelKey)}
                </dt>
                <dd className="mt-1 text-sm font-medium text-[#1b1b24]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-[#777587]">{t("contact.note")}</p>
        </div>
      )}
    </section>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function BillingSettingsTab() {
  const t = useTranslations("settings.billing");
  const { hasPermission } = usePermissions();
  const canViewBilling =
    hasPermission("billing:view") || hasPermission("billing:manage");
  const canManageBilling = hasPermission("billing:manage");

  const capabilities = useMemo(() => getBillingCapabilities(), []);

  const billingPortalUrl = trimToNull(
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL,
  );

  const planQuery = useQuery({
    queryKey: ["billing", "plan"],
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
