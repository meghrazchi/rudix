import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
  SiteSection,
  TEXT_LINK_CLASS,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

function Panel({
  id,
  icon,
  title,
  description,
  items,
}: {
  id: string;
  icon: string;
  title: string;
  description?: string;
  items: string[];
}) {
  return (
    <div className="border-site-border bg-site-surface rounded-2xl border p-7">
      <div className="flex items-center gap-3">
        <SiteIcon name={icon} className="text-site-accent text-2xl" />
        <h2 id={id} className="text-site-ink text-xl font-semibold">
          {title}
        </h2>
      </div>
      {description ? (
        <p className="text-site-ink-muted mt-3 text-sm leading-6">
          {description}
        </p>
      ) : null}
      <ul className="mt-6 space-y-4">
        {items.map((item) => (
          <li
            key={item}
            className="text-site-ink-muted flex items-start gap-3 text-sm leading-6"
          >
            <span className="bg-site-accent mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SecurityCompliance({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.security");

  return (
    <SiteSection
      labelledBy="security-readiness-title"
      className="bg-site-surface border-site-border border-y"
    >
      <p className="text-site-accent-ink text-xs font-semibold tracking-[0.08em] uppercase">
        {t("compliance.eyebrow")}
      </p>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel
          id="security-readiness-title"
          icon="assignment_turned_in"
          title={t("compliance.heading")}
          description={t("compliance.description")}
          items={[0, 1, 2].map((i) => t(`compliance.readiness${i}`))}
        />
        <Panel
          id="security-retention-title"
          icon="auto_delete"
          title={t("compliance.retentionHeading")}
          items={[0, 1, 2].map((i) => t(`compliance.retention${i}`))}
        />
      </div>
      <PublicActionLink
        href={links.securityContact}
        className={`${TEXT_LINK_CLASS} mt-8`}
      >
        {t("cta.primaryCta")}
        <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
      </PublicActionLink>
    </SiteSection>
  );
}

export function SecurityCta({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.security.cta");

  return (
    <section
      aria-labelledby="security-cta-title"
      className="px-4 pb-24 lg:px-8 lg:pb-32"
    >
      <div className="border-site-border bg-site-muted/60 mx-auto max-w-5xl rounded-3xl border px-6 py-14 text-center md:px-12 md:py-20">
        <h2
          id="security-cta-title"
          className="text-site-ink text-3xl font-semibold tracking-tight text-balance md:text-4xl"
        >
          {t("heading")}
        </h2>
        <p className="text-site-ink-muted mx-auto mt-4 max-w-xl text-base leading-7 md:text-lg">
          {t("description")}
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <PublicActionLink
            href={links.securityContact}
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
