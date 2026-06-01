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

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { RateLimitState } from "@/components/states/RateLimitState";
import { QuotaProgress } from "@/components/settings/QuotaProgress";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  getBillingCapabilities,
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
import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

// ── Helpers ───────────────────────────────────────────────────────────────────

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

function isAdminLike(role: AppRole | null | undefined): boolean {
  return role === "owner" || role === "admin";
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

function DeploymentControlledBadge() {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
      Deployment-controlled
    </span>
  );
}

function PlanStatusBadge({ status }: { status: BillingPlanStatus }) {
  const map: Record<BillingPlanStatus, { label: string; cls: string }> = {
    active: {
      label: "Active",
      cls: "bg-emerald-100 text-emerald-800 border-emerald-200",
    },
    trialing: {
      label: "Trial",
      cls: "bg-sky-100 text-sky-800 border-sky-200",
    },
    past_due: {
      label: "Past due",
      cls: "bg-amber-100 text-amber-800 border-amber-200",
    },
    cancelled: {
      label: "Cancelled",
      cls: "bg-rose-100 text-rose-800 border-rose-200",
    },
    unknown: {
      label: "Unknown",
      cls: "bg-slate-100 text-slate-700 border-slate-200",
    },
  };
  const { label, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wider uppercase ${cls}`}
    >
      {label}
    </span>
  );
}

function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  const map: Record<InvoiceStatus, { label: string; cls: string }> = {
    paid: {
      label: "Paid",
      cls: "bg-emerald-100 text-emerald-800",
    },
    open: {
      label: "Open",
      cls: "bg-sky-100 text-sky-800",
    },
    void: {
      label: "Void",
      cls: "bg-slate-100 text-slate-600",
    },
    uncollectible: {
      label: "Uncollectible",
      cls: "bg-rose-100 text-rose-800",
    },
  };
  const { label, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label.toUpperCase()}
    </span>
  );
}

const DATE_RANGE_OPTIONS: { id: BillingDateRange; label: string }[] = [
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "90d", label: "90 days" },
  { id: "billing_period", label: "Billing period" },
];

// ── Plan Card ─────────────────────────────────────────────────────────────────

function PlanCard({
  plan,
  isOwner,
  billingPortalUrl,
}: {
  plan: BillingPlanInfo;
  isOwner: boolean;
  billingPortalUrl: string | null;
}) {
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
            Current Plan
          </p>
          <h3 className="text-2xl font-extrabold text-[#3525cd]">
            {plan.plan_name}
          </h3>
        </div>
        <PlanStatusBadge status={plan.status} />
      </div>

      <dl className="mb-5 space-y-3">
        {plan.billing_cycle && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">Billing cycle</dt>
            <dd className="text-sm font-semibold text-[#1b1b24] capitalize">
              {plan.billing_cycle}
            </dd>
          </div>
        )}
        {plan.renewal_date && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">Renews on</dt>
            <dd className="text-sm font-semibold text-[#1b1b24]">
              {formatDate(plan.renewal_date)}
            </dd>
          </div>
        )}
        {plan.status === "trialing" && plan.trial_end_date && (
          <div className="flex items-center justify-between">
            <dt className="text-sm text-[#5c5871]">Trial ends</dt>
            <dd className="text-sm font-semibold text-sky-700">
              {formatDate(plan.trial_end_date)}
            </dd>
          </div>
        )}
      </dl>

      <div className="mb-6 space-y-4">
        <QuotaProgress
          label="Seats"
          used={seatsUsed}
          total={seatsTotal}
          unit="seats"
        />
        <QuotaProgress
          label="Storage"
          used={storageUsedGb}
          total={storageTotalGb}
          unit="GB"
        />
      </div>

      {(plan.can_manage_subscription || manageUrl) && (
        <a
          href={manageUrl ?? "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#2b1fa8]"
          aria-label="Manage subscription — opens billing portal"
        >
          Manage Subscription
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      )}

      {isOwner && plan.can_cancel_plan && (
        <p className="mt-3 text-center text-xs text-[#777587]">
          To cancel your plan, use the billing portal above.
        </p>
      )}
      <p className="mt-2 text-center text-[10px] text-[#aaa6b8]">
        Handled securely by your billing provider
      </p>
    </section>
  );
}

// ── LLM Cost Card ─────────────────────────────────────────────────────────────

function LlmCostCard({ costUsd }: { costUsd: number | null }) {
  if (costUsd === null) return null;
  const formatted = formatCurrency(costUsd);
  const [dollars, cents] = formatted.split(".");

  return (
    <section
      className="relative overflow-hidden rounded-2xl bg-[#1b1b24] p-6 shadow-lg"
      aria-label="Estimated LLM cost section"
    >
      <p className="mb-3 text-[10px] font-bold tracking-widest text-[#c3c0ff]/70 uppercase">
        Estimated LLM Costs
      </p>
      <div className="mb-1 flex items-baseline gap-1">
        <span className="text-3xl font-extrabold text-white">{dollars}</span>
        {cents && (
          <span className="text-lg font-semibold text-white/60">.{cents}</span>
        )}
      </div>
      <p className="text-[10px] text-[#aaa6b8]">
        All LLM cost values are estimates only
      </p>
      <div
        className="pointer-events-none absolute -right-6 -bottom-6 h-28 w-28 rounded-full bg-[#3525cd]/20 blur-3xl"
        aria-hidden="true"
      />
    </section>
  );
}

// ── Usage Summary ─────────────────────────────────────────────────────────────

function UsageSummarySection({
  capabilities,
}: {
  capabilities: ReturnType<typeof getBillingCapabilities>;
}) {
  const [dateRange, setDateRange] = useState<BillingDateRange>("30d");

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
        <SectionHeader icon={TrendingUp} title="Usage Summary" />
        <div
          className="ml-4 flex gap-1"
          role="group"
          aria-label="Date range selector"
        >
          {DATE_RANGE_OPTIONS.map((opt) => (
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
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {!capabilities.usageEnabled ? (
        <p className="text-sm text-[#777587]">
          Usage data is not available — deployment-controlled.
        </p>
      ) : usageQuery.isLoading ? (
        <LoadingState compact title="Loading usage data..." />
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
            title="Usage data restricted"
            description="You do not have permission to view usage data."
            backHref="/dashboard"
            backLabel="Back to dashboard"
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
                label: "Questions asked",
                value: formatNumber(usageQuery.data?.questions_asked ?? null),
              },
              {
                label: "Input tokens",
                value: formatNumber(usageQuery.data?.input_tokens ?? null),
              },
              {
                label: "Output tokens",
                value: formatNumber(usageQuery.data?.output_tokens ?? null),
              },
              {
                label: "Documents uploaded",
                value: formatNumber(
                  usageQuery.data?.documents_uploaded ?? null,
                ),
              },
              {
                label: "Indexed documents",
                value: formatNumber(usageQuery.data?.indexed_documents ?? null),
              },
              {
                label: "Storage used",
                value: formatStorageGb(
                  usageQuery.data?.storage_used_gb ?? null,
                ),
              },
              {
                label: "Evaluation runs",
                value: formatNumber(usageQuery.data?.evaluation_runs ?? null),
              },
              {
                label: "Agent runs",
                value: formatNumber(usageQuery.data?.agent_runs ?? null),
              },
              {
                label: "Connector syncs",
                value: formatNumber(
                  usageQuery.data?.connector_sync_jobs ?? null,
                ),
              },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="mb-0.5 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {label}
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
                Avg Latency
              </p>
              <p className="text-xl font-bold text-[#3525cd]">
                {usageQuery.data?.avg_latency_ms != null
                  ? `${Math.round(usageQuery.data.avg_latency_ms)}ms`
                  : "—"}
              </p>
            </div>
            <div className="border-x border-[#e4e1ee] text-center">
              <p className="mb-1 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                Avg Confidence
              </p>
              <p className="text-xl font-bold text-[#3525cd]">
                {usageQuery.data?.avg_confidence != null
                  ? `${(usageQuery.data.avg_confidence * 100).toFixed(1)}%`
                  : "—"}
              </p>
            </div>
            <div className="text-center">
              <p className="mb-1 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                Est. LLM Cost
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
              * LLM cost values are estimates only
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
      <SectionHeader icon={Gauge} title="Quota & Limits" />

      {!capabilities.quotasEnabled ? (
        <p className="text-sm text-[#777587]">
          Quota data is not available — deployment-controlled.
        </p>
      ) : quotasQuery.isLoading ? (
        <LoadingState compact title="Loading quota data..." />
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
        <p className="text-sm text-[#777587]">No quota data available.</p>
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
            Invoice History
          </h2>
        </div>
      </div>

      {!capabilities.invoicesEnabled ? (
        <div className="p-6">
          <p className="text-sm text-[#777587]">
            Invoice history is not available — deployment-controlled.
          </p>
        </div>
      ) : invoicesQuery.isLoading ? (
        <div className="p-6">
          <LoadingState compact title="Loading invoices..." />
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
          <p className="text-sm text-[#777587]">No invoices found.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f5f2ff] text-[10px] font-semibold tracking-widest text-[#464555] uppercase">
              <tr>
                <th className="px-6 py-3">Invoice ID</th>
                <th className="px-6 py-3">Date</th>
                <th className="px-6 py-3">Amount</th>
                <th className="px-6 py-3">Status</th>
                <th className="px-6 py-3 text-right">Action</th>
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
                        aria-label={`Download invoice ${inv.id}`}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-[#3525cd] hover:underline"
                      >
                        <Download size={14} aria-hidden="true" />
                        Download
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

function BillingPortalFallback({ portalUrl }: { portalUrl: string | null }) {
  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm"
      aria-label="Billing portal section"
    >
      <div className="mb-3 flex items-center gap-3">
        <CreditCard size={20} className="text-[#3525cd]" aria-hidden="true" />
        <h2 className="text-sm font-bold tracking-wide text-[#5f5a74] uppercase">
          Billing
        </h2>
        <DeploymentControlledBadge />
      </div>
      <p className="mb-4 text-sm text-[#4d4963]">
        Detailed billing information is managed through your billing portal.
        Plan, usage, and invoice data are not directly available in this
        deployment.
      </p>
      {portalUrl ? (
        <a
          href={portalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
        >
          Open billing portal
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      ) : (
        <p className="text-sm text-[#777587]">
          No billing portal URL is configured for this deployment. Contact your
          administrator.
        </p>
      )}
    </section>
  );
}

// ── Billing Notifications Info ────────────────────────────────────────────────

function BillingNotificationsInfo() {
  return (
    <section
      className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm"
      aria-label="Billing notifications section"
    >
      <SectionHeader icon={AlertTriangle} title="Billing Alerts" />
      <div className="space-y-3">
        {[
          {
            label: "80% quota threshold",
            description: "Email alert when any quota reaches 80%.",
          },
          {
            label: "90% quota threshold",
            description: "Email alert when any quota reaches 90%.",
          },
          {
            label: "Quota exceeded",
            description: "Immediate alert when quota is reached.",
          },
          {
            label: "Failed payments",
            description: "Alert for payment failures (owner/admin).",
          },
          {
            label: "Invoice available",
            description: "Notification when a new invoice is generated.",
          },
        ].map(({ label, description }) => (
          <div
            key={label}
            className="flex items-start gap-3 rounded-lg border border-[#ebe8f7] bg-[#f5f2ff]/40 px-4 py-3"
          >
            <Zap
              size={14}
              className="mt-0.5 shrink-0 text-[#3525cd]"
              aria-hidden="true"
            />
            <div>
              <p className="text-sm font-semibold text-[#1b1b24]">{label}</p>
              <p className="text-xs text-[#464555]">{description}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-[#777587]">
        Alert delivery depends on your deployment&apos;s notification
        configuration.
      </p>
    </section>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function BillingSettingsTab() {
  const { state } = useAuthSession();
  const session = state.session;
  const role = session?.role ?? null;
  const isAdmin = isAdminLike(role);
  const isOwner = role === "owner";

  const capabilities = useMemo(() => getBillingCapabilities(), []);

  const billingPortalUrl = trimToNull(
    process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL,
  );

  const planQuery = useQuery({
    queryKey: ["billing", "plan"],
    queryFn: getBillingPlanInfo,
    enabled: capabilities.planEnabled && isAdmin,
    retry: false,
  });

  if (!isAdmin) {
    return (
      <ForbiddenState
        compact
        title="Billing restricted"
        description="Billing settings are available to owners and admins only."
        backHref="/dashboard"
        backLabel="Back to dashboard"
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left column: Plan + LLM cost */}
        <div className="space-y-6 lg:col-span-4">
          {capabilities.planEnabled ? (
            planQuery.isLoading ? (
              <section className="rounded-2xl border border-[#c7c4d8] bg-white p-6 shadow-sm">
                <LoadingState compact title="Loading plan info..." />
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
                  <BillingPortalFallback portalUrl={billingPortalUrl} />
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
                isOwner={isOwner}
                billingPortalUrl={billingPortalUrl}
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
                  Current Plan
                </h2>
                <DeploymentControlledBadge />
              </div>
              <p className="text-sm text-[#777587]">
                Plan details are not available — deployment-controlled.
              </p>
              {billingPortalUrl && (
                <a
                  href={billingPortalUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f3ff]"
                >
                  Open billing portal
                  <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
            </section>
          )}

          <BillingNotificationsInfo />
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
