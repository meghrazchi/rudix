import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export type PlanId = "starter" | "team" | "enterprise";

export const PLAN_IDS: readonly PlanId[] = ["starter", "team", "enterprise"];

const FEATURED_PLAN: PlanId = "team";

function planHref(planId: PlanId, links: PublicSiteLinks): string {
  if (planId === "starter") return links.startTrial;
  if (planId === "team") return links.requestDemo;
  return links.contact;
}

export function PricingPlans({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.pricing.plans");

  return (
    <SiteSection
      id="plans"
      labelledBy="pricing-plans-title"
      className="pt-8 lg:pt-12"
    >
      <SectionHeading
        id="pricing-plans-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
        align="center"
      />
      <ul className="mt-14 grid grid-cols-1 items-stretch gap-6 lg:grid-cols-3">
        {PLAN_IDS.map((planId) => {
          const featured = planId === FEATURED_PLAN;
          return (
            <li
              key={planId}
              className={`bg-site-surface relative flex flex-col rounded-2xl border p-7 ${
                featured
                  ? "border-site-accent shadow-[0_24px_60px_-36px_var(--site-accent)]"
                  : "border-site-border"
              }`}
            >
              {featured ? (
                <span className="bg-site-accent text-site-on-accent absolute start-1/2 -top-3 -translate-x-1/2 rounded-full px-3 py-1 text-xs font-medium whitespace-nowrap rtl:translate-x-1/2">
                  {t(`${planId}Badge`)}
                </span>
              ) : (
                <span className="bg-site-muted text-site-ink-muted w-fit rounded-full px-2.5 py-0.5 text-xs font-medium">
                  {t(`${planId}Badge`)}
                </span>
              )}
              <h3
                className={`text-site-ink text-xl font-semibold ${featured ? "mt-1" : "mt-4"}`}
              >
                {t(`${planId}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t(`${planId}Summary`)}
              </p>
              <p className="text-site-ink mt-6 text-3xl font-semibold tracking-tight">
                {t("contactUs")}
              </p>
              <p className="text-site-ink-subtle mt-1 text-xs leading-5">
                {t(`${planId}BillingHint`)}
              </p>
              <ul className="border-site-border mt-6 mb-8 flex-1 space-y-3 border-t pt-6">
                {[0, 1, 2, 3].map((index) => (
                  <li
                    key={index}
                    className="text-site-ink flex items-start gap-2.5 text-sm leading-6"
                  >
                    <SiteIcon
                      name="check"
                      className="text-site-accent mt-0.5 text-lg"
                    />
                    {t(`${planId}H${index}`)}
                  </li>
                ))}
              </ul>
              <PublicActionLink
                href={planHref(planId, links)}
                className={`${featured ? PRIMARY_BUTTON_CLASS : SECONDARY_BUTTON_CLASS} w-full`}
              >
                {t(`${planId}Cta`)}
              </PublicActionLink>
            </li>
          );
        })}
      </ul>
    </SiteSection>
  );
}
