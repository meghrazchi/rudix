"use client";

import { useTranslations } from "next-intl";

import { PricingComparison } from "@/components/public/pricing/PricingComparison";
import { PricingCta } from "@/components/public/pricing/PricingCta";
import { PricingHero } from "@/components/public/pricing/PricingHero";
import { PricingPlans } from "@/components/public/pricing/PricingPlans";
import { PricingUsage } from "@/components/public/pricing/PricingUsage";
import { SiteFaq } from "@/components/public/site/SiteFaq";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const FAQ_KEYS = [
  "trial",
  "upgrades",
  "securityReview",
  "selfHosted",
  "billing",
] as const;

/**
 * Public pricing page (minimal modern redesign). Plans show "Contact us"
 * instead of numeric prices until commercial packaging is published.
 */
export function PricingOverviewPage() {
  const t = useTranslations("public.pricing");
  const links = resolvePublicSiteLinks();
  const faqs = FAQ_KEYS.map((key) => ({
    question: t(`faq.${key}Q`),
    answer: t(`faq.${key}A`),
  }));

  return (
    <div className="bg-site-canvas text-site-ink">
      <PricingHero links={links} />
      <PricingPlans links={links} />
      <PricingUsage />
      <PricingComparison />
      <SiteFaq title={t("faq.title")} items={faqs} />
      <PricingCta links={links} />
    </div>
  );
}
