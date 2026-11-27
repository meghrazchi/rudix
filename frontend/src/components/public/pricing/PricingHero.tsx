import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export function PricingHero({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.pricing.hero");

  return (
    <section
      aria-labelledby="pricing-hero-title"
      className="relative overflow-hidden px-4 pt-16 pb-12 lg:px-8 lg:pt-24 lg:pb-16"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(60%_60%_at_50%_0%,var(--site-accent-soft),transparent)]"
      />
      <div className="rudix-site-rise relative mx-auto flex max-w-3xl flex-col items-center text-center">
        <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
          <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
          {t("badge")}
        </p>
        <h1
          id="pricing-hero-title"
          className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl lg:hyphens-manual"
        >
          {t("heading")}
        </h1>
        <p className="text-site-ink-muted mt-6 max-w-2xl text-base leading-7 md:text-lg md:leading-8">
          {t("description")}
        </p>
        <div className="mt-9 flex w-full flex-col items-center justify-center gap-3 sm:w-auto sm:flex-row">
          <PublicActionLink
            href={links.requestDemo}
            className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("requestDemoCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}
