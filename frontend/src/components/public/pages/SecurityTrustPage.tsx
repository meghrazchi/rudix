"use client";

import { useTranslations } from "next-intl";

import {
  SecurityCompliance,
  SecurityCta,
} from "@/components/public/security/SecurityCompliance";
import { SecurityHero } from "@/components/public/security/SecurityHero";
import {
  SecurityAccess,
  SecurityLifecycle,
} from "@/components/public/security/SecurityLifecycle";
import { SecurityPillars } from "@/components/public/security/SecurityPillars";
import { SiteFaq } from "@/components/public/site/SiteFaq";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const FAQ_KEYS = ["logs", "private", "isolation", "review"] as const;

/**
 * Public security and trust page (minimal modern redesign). Copy avoids
 * certification claims; readiness depends on each customer's deployment.
 */
export function SecurityTrustPage() {
  const t = useTranslations("public.security");
  const links = resolvePublicSiteLinks();
  const faqs = FAQ_KEYS.map((key) => ({
    question: t(`faq.${key}Q`),
    answer: t(`faq.${key}A`),
  }));

  return (
    <div className="bg-site-canvas text-site-ink">
      <SecurityHero links={links} />
      <SecurityPillars />
      <SecurityLifecycle />
      <SecurityAccess />
      <SecurityCompliance links={links} />
      <SiteFaq title={t("faq.title")} items={faqs} />
      <SecurityCta links={links} />
    </div>
  );
}
