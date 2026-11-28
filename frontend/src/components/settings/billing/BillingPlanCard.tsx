"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { QuotaProgress } from "@/components/settings/QuotaProgress";
import { type BillingPlanInfo } from "@/lib/api/billing";
import {
  trimToNull,
  formatDate,
  PlanStatusBadge,
  PlanStatusCallout,
} from "@/components/settings/billing/billingShared";
import { publicEnv } from "@/lib/public-env";

export function PlanCard({
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
    trimToNull(
      publicEnv(
        "NEXT_PUBLIC_SETTINGS_BILLING_URL",
        process.env.NEXT_PUBLIC_SETTINGS_BILLING_URL,
      ),
    );

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
