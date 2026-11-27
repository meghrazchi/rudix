import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { LandingAnswerPreview } from "@/components/public/landing/LandingAnswerPreview";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

export function LandingHero({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.landing.hero");
  const trustItems = [t("trustSoc2"), t("trustGdpr"), t("trustPrivateCloud")];

  return (
    <section
      aria-labelledby="landing-hero-title"
      className="relative overflow-hidden px-4 pt-16 pb-20 lg:px-8 lg:pt-24 lg:pb-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 -z-0 h-[480px] bg-[radial-gradient(60%_60%_at_50%_0%,var(--site-accent-soft),transparent)]"
      />
      <div className="relative mx-auto flex w-full max-w-6xl flex-col items-center text-center">
        <p className="rudix-site-rise border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
          <SiteIcon
            name="auto_awesome"
            className="text-site-accent text-sm"
            filled
          />
          {t("badge")}
        </p>

        <h1
          id="landing-hero-title"
          className="rudix-site-rise text-site-ink mt-6 max-w-4xl text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl lg:text-6xl"
        >
          <span className="block">{t("title")}</span>
          <span className="text-site-ink-subtle block">
            {t("titleHighlight")}
          </span>
        </h1>

        <p className="rudix-site-rise text-site-ink-muted mt-6 max-w-2xl text-base leading-7 text-pretty md:text-lg md:leading-8">
          {t("description")}
        </p>

        <div className="rudix-site-rise mt-9 flex w-full flex-col items-center justify-center gap-3 sm:w-auto sm:flex-row">
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
            <SiteIcon name="upload" className="text-base" />
            {t("secondaryCta")}
          </PublicActionLink>
        </div>

        <ul className="text-site-ink-muted mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-medium">
          {trustItems.map((label) => (
            <li key={label} className="inline-flex items-center gap-1.5">
              <SiteIcon
                name="verified"
                className="text-site-success text-base"
              />
              {label}
            </li>
          ))}
        </ul>

        <div className="rudix-site-rise mt-14 w-full lg:mt-16">
          <LandingAnswerPreview />
        </div>
      </div>
    </section>
  );
}
