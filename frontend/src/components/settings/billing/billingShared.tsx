"use client";

import { useTranslations } from "next-intl";
import {
  type BillingPlanInfo,
  type BillingPlanStatus,
  type InvoiceStatus,
} from "@/lib/api/billing";

export function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

export function formatDate(value: string | null | undefined): string {
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

export function formatCurrency(usd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(usd);
}

export function formatStorageGb(gb: number | null): string {
  if (gb === null) return "—";
  if (gb >= 1000) return `${(gb / 1000).toFixed(1)} TB`;
  return `${gb.toFixed(1)} GB`;
}

export function formatNumber(n: number | null): string {
  if (n === null) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

// ── Sub-components ────────────────────────────────────────────────────────────

export function SectionHeader({
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

export function DeploymentControlledBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
      {label}
    </span>
  );
}

export function PlanStatusBadge({ status }: { status: BillingPlanStatus }) {
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

export function PlanStatusCallout({ plan }: { plan: BillingPlanInfo }) {
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

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
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
