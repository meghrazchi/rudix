import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export function PricingCta({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.pricing.cta");

  return (
    <section
      aria-labelledby="pricing-cta-title"
      className="px-4 pb-24 lg:px-8 lg:pb-32"
    >
      <div className="border-site-border bg-site-muted/60 mx-auto max-w-5xl rounded-3xl border px-6 py-14 text-center md:px-12 md:py-20">
        <h2
          id="pricing-cta-title"
          className="text-site-ink text-3xl font-semibold tracking-tight text-balance break-words hyphens-auto md:text-4xl lg:hyphens-manual"
        >
          {t("heading")}
        </h2>
        <p className="text-site-ink-muted mx-auto mt-4 max-w-xl text-base leading-7 md:text-lg">
          {t("description")}
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <PublicActionLink
            href={links.contact}
            className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("primaryCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
          <PublicActionLink
            href={links.requestDemo}
            className={`${SECONDARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("secondaryCta")}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}
