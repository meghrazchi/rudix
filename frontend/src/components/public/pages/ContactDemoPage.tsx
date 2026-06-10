"use client";

import { useTranslations } from "next-intl";

import {
  ContactHeroSection,
  ContactMainSection,
  ContactMapSection,
} from "@/components/public/pages/contact/ContactDemoSections";
import {
  FinalCtaBand,
  FaqSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import { resolveContactSubmissionConfig } from "@/lib/public-site/contact";

export function ContactDemoPage() {
  const t = useTranslations("public.contact");
  const links = resolvePublicSiteLinks();
  const submissionConfig = resolveContactSubmissionConfig(links);

  const contactFaqs = [
    { question: t("faq.demoQ"), answer: t("faq.demoA") },
    { question: t("faq.securityQ"), answer: t("faq.securityA") },
    { question: t("faq.schedulingQ"), answer: t("faq.schedulingA") },
    { question: t("faq.fallbackQ"), answer: t("faq.fallbackA") },
  ];

  return (
    <>
      <ContactHeroSection />
      <ContactMainSection links={links} submissionConfig={submissionConfig} />
      <ContactMapSection />

      <FaqSection title={t("faq.title")} items={contactFaqs} />

      <FinalCtaBand
        title={t("cta.heading")}
        description={t("cta.description")}
        primaryLabel={t("cta.primaryCta")}
        primaryHref={links.requestDemo}
        secondaryLabel={t("cta.secondaryCta")}
        secondaryHref={links.product}
      />
    </>
  );
}
