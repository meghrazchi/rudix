"use client";

import { useTranslations } from "next-intl";

import {
  FinalCtaBand,
  FaqSection,
} from "@/components/public/sections/PublicSections";
import {
  PlanComparisonSection,
  PricingHeroSection,
  PricingPlanCardsSection,
  UsageLimitsSection,
} from "@/components/public/pages/pricing/PricingSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function PricingOverviewPage() {
  const t = useTranslations("public.pricing");
  const links = resolvePublicSiteLinks();

  const pricingFaqs = [
    { question: t("faq.trialQ"), answer: t("faq.trialA") },
    { question: t("faq.upgradesQ"), answer: t("faq.upgradesA") },
    { question: t("faq.securityReviewQ"), answer: t("faq.securityReviewA") },
    { question: t("faq.selfHostedQ"), answer: t("faq.selfHostedA") },
    { question: t("faq.billingQ"), answer: t("faq.billingA") },
  ];

  return (
    <>
      <PricingHeroSection links={links} />
      <PricingPlanCardsSection links={links} />
      <UsageLimitsSection />
      <PlanComparisonSection />

      <FaqSection title={t("faq.title")} items={pricingFaqs} />

      <FinalCtaBand
        title={t("cta.heading")}
        description={t("cta.description")}
        primaryLabel={t("cta.primaryCta")}
        primaryHref={links.contact}
        secondaryLabel={t("cta.secondaryCta")}
        secondaryHref={links.requestDemo}
      />
    </>
  );
}
