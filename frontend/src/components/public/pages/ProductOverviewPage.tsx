"use client";

import { useTranslations } from "next-intl";

import {
  ProductAdmin,
  ProductIntegration,
} from "@/components/public/product/ProductAdmin";
import { ProductCta } from "@/components/public/product/ProductCta";
import { ProductDocuments } from "@/components/public/product/ProductDocuments";
import { ProductGroundedAnswers } from "@/components/public/product/ProductGroundedAnswers";
import { ProductHero } from "@/components/public/product/ProductHero";
import { ProductPipeline } from "@/components/public/product/ProductPipeline";
import { ProductWorkflow } from "@/components/public/product/ProductWorkflow";
import { SiteFaq } from "@/components/public/site/SiteFaq";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const FAQ_KEYS = [
  "fileTypes",
  "citations",
  "evaluation",
  "isolation",
  "deployment",
] as const;

/**
 * Public product overview (minimal modern redesign). Uses the shared `site-*`
 * tokens so it follows the light/dark preference set by the marketing layout.
 */
export function ProductOverviewPage() {
  const t = useTranslations("public.product");
  const links = resolvePublicSiteLinks();
  const faqs = FAQ_KEYS.map((key) => ({
    question: t(`faq.${key}Q`),
    answer: t(`faq.${key}A`),
  }));

  return (
    <div className="bg-site-canvas text-site-ink">
      <ProductHero links={links} />
      <ProductWorkflow />
      <ProductDocuments />
      <ProductGroundedAnswers />
      <ProductPipeline links={links} />
      <ProductAdmin />
      <ProductIntegration />
      <SiteFaq title={t("faq.title")} items={faqs} />
      <ProductCta links={links} />
    </div>
  );
}
