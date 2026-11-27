"use client";

import { useTranslations } from "next-intl";

import {
  ContactHeroSection,
  ContactMainSection,
} from "@/components/public/pages/contact/ContactDemoSections";
import { SiteCtaPanel } from "@/components/public/site/SiteBlocks";
import { SiteFaq } from "@/components/public/site/SiteFaq";
import { resolveContactSubmissionConfig } from "@/lib/public-site/contact";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const FAQ_KEYS = ["demo", "security", "scheduling", "fallback"] as const;

/** Contact and demo page (minimal modern redesign). */
export function ContactDemoPage() {
  const t = useTranslations("public.contact");
  const links = resolvePublicSiteLinks();
  const submissionConfig = resolveContactSubmissionConfig(links);
  const faqs = FAQ_KEYS.map((key) => ({
    question: t(`faq.${key}Q`),
    answer: t(`faq.${key}A`),
  }));

  return (
    <div className="bg-site-canvas text-site-ink">
      <ContactHeroSection />
      <ContactMainSection links={links} submissionConfig={submissionConfig} />
      <div className="bg-site-surface border-site-border border-t">
        <SiteFaq title={t("faq.title")} items={faqs} />
      </div>
      <SiteCtaPanel
        id="contact-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
        secondary={{ href: links.product, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
