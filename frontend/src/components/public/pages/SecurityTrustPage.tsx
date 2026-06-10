"use client";

import { useTranslations } from "next-intl";

import {
  FaqSection,
  FinalCtaBand,
} from "@/components/public/sections/PublicSections";
import {
  AccessGovernanceSection,
  ComplianceAndRetentionSection,
  DocumentHandlingSection,
  SecurityHeroSection,
  SecurityPillarsSection,
} from "@/components/public/pages/security/SecurityTrustSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function SecurityTrustPage() {
  const t = useTranslations("public.security");
  const links = resolvePublicSiteLinks();

  const securityFaqs = [
    { question: t("faq.logsQ"), answer: t("faq.logsA") },
    { question: t("faq.privateQ"), answer: t("faq.privateA") },
    { question: t("faq.isolationQ"), answer: t("faq.isolationA") },
    { question: t("faq.reviewQ"), answer: t("faq.reviewA") },
  ];

  return (
    <>
      <SecurityHeroSection
        securityReviewHref={links.securityContact}
        architectureHref={links.docs}
      />
      <SecurityPillarsSection />
      <DocumentHandlingSection />
      <AccessGovernanceSection />
      <ComplianceAndRetentionSection
        securityContactHref={links.securityContact}
      />

      <FaqSection title={t("faq.title")} items={securityFaqs} />

      <FinalCtaBand
        title={t("cta.heading")}
        description={t("cta.description")}
        primaryLabel={t("cta.primaryCta")}
        primaryHref={links.securityContact}
        secondaryLabel={t("cta.secondaryCta")}
        secondaryHref={links.requestDemo}
      />
    </>
  );
}
