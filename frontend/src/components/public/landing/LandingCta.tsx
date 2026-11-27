import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/landing/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export function LandingCta({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.landing.cta");

  return (
    <section
      id="pricing"
      aria-labelledby="landing-cta-title"
      className="px-4 pb-24 lg:px-8 lg:pb-32"
    >
      <div className="mx-auto max-w-3xl text-center">
        <h2
          id="landing-cta-title"
          className="text-site-ink text-3xl font-semibold tracking-tight text-balance md:text-5xl"
        >
          {t("heading")}
        </h2>
        <p className="text-site-ink-muted mx-auto mt-5 max-w-xl text-base leading-7 md:text-lg">
          {t("description")}
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <PublicActionLink
            href={links.requestDemo}
            className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("primaryCta")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
          <PublicActionLink
            href={links.docs}
            className={`${SECONDARY_BUTTON_CLASS} w-full sm:w-auto`}
          >
            {t("secondaryCta")}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}
