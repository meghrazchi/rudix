"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { type PlanId } from "@/components/public/pages/pricing/pricingData";
import type { PublicSiteLinks } from "@/lib/public-site/links";

type PlanCtaConfig = {
  href: string;
  className: string;
};

function planCtaConfig(planId: PlanId, links: PublicSiteLinks): PlanCtaConfig {
  if (planId === "starter") {
    return {
      href: links.startTrial,
      className:
        "rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2a1fc1]",
    };
  }

  if (planId === "team") {
    return {
      href: links.requestDemo,
      className:
        "rounded-lg bg-[#252a3d] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#1b2031]",
    };
  }

  return {
    href: links.contact,
    className:
      "rounded-lg border border-[#c9d0e2] bg-white px-4 py-2 text-sm font-semibold text-[#1f2538] transition hover:bg-[#f4f6fc]",
  };
}

export function PricingHeroSection({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.pricing");

  return (
    <section className="relative overflow-hidden border-b border-[#d8dce7] bg-[radial-gradient(circle_at_top,rgba(56,43,225,0.1),transparent_62%)] py-16 lg:py-22">
      <div className="mx-auto w-full max-w-7xl px-4 text-center lg:px-8">
        <span className="inline-flex rounded-full bg-[#e4e1ff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#3b2fcb] uppercase">
          {t("hero.badge")}
        </span>
        <h1 className="mx-auto mt-5 max-w-4xl text-4xl leading-tight font-black text-[#10131c] lg:text-6xl">
          {t("hero.heading")}
        </h1>
        <p className="mx-auto mt-4 max-w-3xl text-sm leading-7 text-[#5a6074] lg:text-base">
          {t("hero.description")}
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <PublicActionLink
            href={links.startTrial}
            className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_14px_30px_rgba(53,37,205,0.24)] transition hover:bg-[#2a1fc1]"
          >
            {t("hero.startTrialCta")}
          </PublicActionLink>
          <PublicActionLink
            href={links.requestDemo}
            className="rounded-lg border border-[#cfd4e4] bg-white px-5 py-3 text-sm font-semibold text-[#21283d] transition hover:bg-[#f4f6fd]"
          >
            {t("hero.requestDemoCta")}
          </PublicActionLink>
          <PublicActionLink
            href={links.login}
            className="rounded-lg border border-[#d6dbe9] bg-[#f8f9fc] px-5 py-3 text-sm font-semibold text-[#2a3044] transition hover:bg-[#eef1f8]"
          >
            {t("hero.loginCta")}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

export function PricingPlanCardsSection({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.pricing");

  const plans: Array<{
    id: PlanId;
    badge: string;
    title: string;
    summary: string;
    priceLabel: string;
    billingHint: string;
    highlights: string[];
    ctaLabel: string;
  }> = [
    {
      id: "starter",
      badge: t("plans.starterBadge"),
      title: t("plans.starterTitle"),
      summary: t("plans.starterSummary"),
      priceLabel: t("plans.contactUs"),
      billingHint: t("plans.starterBillingHint"),
      highlights: [
        t("plans.starterH0"),
        t("plans.starterH1"),
        t("plans.starterH2"),
        t("plans.starterH3"),
      ],
      ctaLabel: t("plans.starterCta"),
    },
    {
      id: "team",
      badge: t("plans.teamBadge"),
      title: t("plans.teamTitle"),
      summary: t("plans.teamSummary"),
      priceLabel: t("plans.contactUs"),
      billingHint: t("plans.teamBillingHint"),
      highlights: [
        t("plans.teamH0"),
        t("plans.teamH1"),
        t("plans.teamH2"),
        t("plans.teamH3"),
      ],
      ctaLabel: t("plans.teamCta"),
    },
    {
      id: "enterprise",
      badge: t("plans.enterpriseBadge"),
      title: t("plans.enterpriseTitle"),
      summary: t("plans.enterpriseSummary"),
      priceLabel: t("plans.contactUs"),
      billingHint: t("plans.enterpriseBillingHint"),
      highlights: [
        t("plans.enterpriseH0"),
        t("plans.enterpriseH1"),
        t("plans.enterpriseH2"),
        t("plans.enterpriseH3"),
      ],
      ctaLabel: t("plans.enterpriseCta"),
    },
  ];

  return (
    <section
      aria-labelledby="pricing-plans-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="max-w-3xl">
        <h2
          id="pricing-plans-title"
          className="text-3xl font-black text-[#12151f] lg:text-5xl"
        >
          {t("plans.heading")}
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6278] lg:text-base">
          {t("plans.description")}
        </p>
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-3">
        {plans.map((plan) => {
          const cta = planCtaConfig(plan.id, links);
          return (
            <article
              key={plan.id}
              className={`flex h-full flex-col rounded-2xl border p-6 shadow-sm ${
                plan.id === "team"
                  ? "border-[#4a42de] bg-[#f8f7ff]"
                  : "border-[#d8dce8] bg-white"
              }`}
            >
              <p className="text-[11px] font-bold tracking-[0.12em] text-[#4b53d6] uppercase">
                {plan.badge}
              </p>
              <h3 className="mt-3 text-2xl font-black text-[#171c2b]">
                {plan.title}
              </h3>
              <p className="mt-2 min-h-[84px] text-sm leading-7 text-[#5a6073]">
                {plan.summary}
              </p>
              <p className="mt-5 text-3xl font-black text-[#121729]">
                {plan.priceLabel}
              </p>
              <p className="mt-2 min-h-[40px] text-xs leading-6 text-[#646b81]">
                {plan.billingHint}
              </p>

              <ul className="mt-5 space-y-2">
                {plan.highlights.map((highlight) => (
                  <li
                    key={highlight}
                    className="flex gap-2 text-sm text-[#394055]"
                  >
                    <span className="mt-2 inline-block h-1.5 w-1.5 rounded-full bg-[#4941de]" />
                    <span>{highlight}</span>
                  </li>
                ))}
              </ul>

              <div className="mt-auto pt-6">
                <PublicActionLink href={cta.href} className={cta.className}>
                  {plan.ctaLabel}
                </PublicActionLink>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function UsageLimitsSection() {
  const t = useTranslations("public.pricing");

  const usageLimitNotes = [
    {
      title: t("usageLimits.documentsTitle"),
      detail: t("usageLimits.documentsDetail"),
    },
    {
      title: t("usageLimits.questionsTitle"),
      detail: t("usageLimits.questionsDetail"),
    },
    {
      title: t("usageLimits.storageTitle"),
      detail: t("usageLimits.storageDetail"),
    },
  ];

  return (
    <section
      aria-labelledby="usage-limits-title"
      className="border-y border-[#d8dce8] bg-[#f2f4f9]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <h2
            id="usage-limits-title"
            className="text-3xl font-black text-[#12151f] lg:text-5xl"
          >
            {t("usageLimits.heading")}
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5a6074] lg:text-base">
            {t("usageLimits.description")}
          </p>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {usageLimitNotes.map((note) => (
            <article
              key={note.title}
              className="rounded-2xl border border-[#d8dce8] bg-white p-5 shadow-sm"
            >
              <h3 className="text-xl font-semibold text-[#1a1f30]">
                {note.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-[#5a6073]">
                {note.detail}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function PlanComparisonSection() {
  const t = useTranslations("public.pricing");

  const comparisonRows = [
    {
      capability: t("comparison.rowDocumentCapabilityLabel"),
      starter: t("comparison.rowDocumentStarterValue"),
      team: t("comparison.rowDocumentTeamValue"),
      enterprise: t("comparison.rowDocumentEnterpriseValue"),
    },
    {
      capability: t("comparison.rowStorageCapabilityLabel"),
      starter: t("comparison.rowStorageStarterValue"),
      team: t("comparison.rowStorageTeamValue"),
      enterprise: t("comparison.rowStorageEnterpriseValue"),
    },
    {
      capability: t("comparison.rowTeamAccessCapabilityLabel"),
      starter: t("comparison.rowTeamAccessStarterValue"),
      team: t("comparison.rowTeamAccessTeamValue"),
      enterprise: t("comparison.rowTeamAccessEnterpriseValue"),
    },
    {
      capability: t("comparison.rowEvaluationsCapabilityLabel"),
      starter: t("comparison.rowEvaluationsStarterValue"),
      team: t("comparison.rowEvaluationsTeamValue"),
      enterprise: t("comparison.rowEvaluationsEnterpriseValue"),
    },
    {
      capability: t("comparison.rowAuditCapabilityLabel"),
      starter: t("comparison.rowAuditStarterValue"),
      team: t("comparison.rowAuditTeamValue"),
      enterprise: t("comparison.rowAuditEnterpriseValue"),
    },
    {
      capability: t("comparison.rowDeploymentCapabilityLabel"),
      starter: t("comparison.rowDeploymentStarterValue"),
      team: t("comparison.rowDeploymentTeamValue"),
      enterprise: t("comparison.rowDeploymentEnterpriseValue"),
    },
    {
      capability: t("comparison.rowSupportCapabilityLabel"),
      starter: t("comparison.rowSupportStarterValue"),
      team: t("comparison.rowSupportTeamValue"),
      enterprise: t("comparison.rowSupportEnterpriseValue"),
    },
  ];

  return (
    <section
      aria-labelledby="plan-comparison-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="mb-8 max-w-3xl">
        <h2
          id="plan-comparison-title"
          className="text-3xl font-black text-[#12151f] lg:text-5xl"
        >
          {t("comparison.heading")}
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5a6074] lg:text-base">
          {t("comparison.description")}
        </p>
      </div>

      <div className="hidden overflow-x-auto rounded-2xl border border-[#d2d7e6] bg-white shadow-sm md:block">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                {t("comparison.capability")}
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                {t("comparison.starter")}
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                {t("comparison.team")}
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                {t("comparison.enterprise")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e3e7f0]">
            {comparisonRows.map((row) => (
              <tr key={row.capability}>
                <td className="px-4 py-3 text-sm font-semibold text-[#1f2538]">
                  {row.capability}
                </td>
                <td className="px-4 py-3 text-sm text-[#4d5570]">
                  {row.starter}
                </td>
                <td className="px-4 py-3 text-sm text-[#4d5570]">{row.team}</td>
                <td className="px-4 py-3 text-sm text-[#4d5570]">
                  {row.enterprise}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-3 md:hidden">
        {comparisonRows.map((row) => (
          <article
            key={row.capability}
            className="rounded-xl border border-[#d8dce8] bg-white p-4 shadow-sm"
          >
            <h3 className="text-sm font-bold text-[#1f2538]">
              {row.capability}
            </h3>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex items-start justify-between gap-3">
                <dt className="font-semibold text-[#50576f]">{t("comparison.starter")}</dt>
                <dd className="text-right text-[#2a3043]">{row.starter}</dd>
              </div>
              <div className="flex items-start justify-between gap-3">
                <dt className="font-semibold text-[#50576f]">{t("comparison.team")}</dt>
                <dd className="text-right text-[#2a3043]">{row.team}</dd>
              </div>
              <div className="flex items-start justify-between gap-3">
                <dt className="font-semibold text-[#50576f]">{t("comparison.enterprise")}</dt>
                <dd className="text-right text-[#2a3043]">{row.enterprise}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}
