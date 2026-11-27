import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  SECONDARY_BUTTON_CLASS,
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

const STAGES = [
  "upload",
  "extract",
  "chunk",
  "embed",
  "retrieve",
  "answer",
] as const;

export function ProductPipeline({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.product.pipeline");

  return (
    <SiteSection labelledBy="product-pipeline-title">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-16">
        <div className="lg:col-span-5">
          <SectionHeading
            id="product-pipeline-title"
            eyebrow={t("eyebrow")}
            title={t("heading")}
            description={t("description")}
          />
          <PublicActionLink
            href={links.app}
            className={`${SECONDARY_BUTTON_CLASS} mt-8`}
          >
            {t("openCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
        </div>
        <figure
          aria-label={t("imageAlt")}
          className="border-site-border bg-site-surface rounded-2xl border p-6 sm:p-8 lg:col-span-7"
        >
          <ol className="relative space-y-6">
            <span
              aria-hidden="true"
              className="bg-site-border absolute start-4 top-4 bottom-4 w-px"
            />
            {STAGES.map((stage) => (
              <li key={stage} className="relative flex items-start gap-4">
                <span className="border-site-border bg-site-surface text-site-success relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full border">
                  <SiteIcon name="check" className="text-base" />
                </span>
                <div>
                  <p className="text-site-ink text-sm font-semibold">
                    {t(`stages.${stage}Title`)}
                  </p>
                  <p className="text-site-ink-muted text-sm">
                    {t(`stages.${stage}Desc`)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </figure>
      </div>
    </SiteSection>
  );
}
