import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { SiteIcon, SiteSection } from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

const FEATURES = [
  { key: "dataIsolation", icon: "domain" },
  { key: "auditLogs", icon: "history_edu" },
  { key: "encryption", icon: "lock" },
] as const;

export function LandingSecurity({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.landing.security");
  const nav = useTranslations("public.nav.items");

  return (
    <SiteSection
      id="security"
      labelledBy="landing-security-title"
      className="pt-0 lg:pt-0"
    >
      <div className="border-site-border bg-site-muted/60 rounded-3xl border p-6 md:p-12">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <p className="border-site-border bg-site-surface text-site-accent-ink inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium">
              <SiteIcon name="shield_lock" className="text-sm" />
              {t("eyebrow")}
            </p>
            <h2
              id="landing-security-title"
              className="text-site-ink mt-4 text-3xl font-semibold tracking-tight text-balance break-words hyphens-auto md:text-4xl lg:hyphens-manual"
            >
              {t("heading")}
            </h2>
            <p className="text-site-ink-muted mt-4 text-base leading-7 md:text-lg">
              {t("description")}
            </p>
          </div>
          <PublicActionLink
            href={links.security}
            className="text-site-accent-ink inline-flex shrink-0 items-center gap-1 rounded-md text-sm font-medium hover:underline"
          >
            {nav("security")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
          </PublicActionLink>
        </div>
        <ul className="mt-10 grid gap-4 md:grid-cols-3">
          {FEATURES.map((item) => (
            <li
              key={item.key}
              className="border-site-border bg-site-surface rounded-2xl border p-6"
            >
              <span className="bg-site-accent-soft text-site-accent-ink flex h-9 w-9 items-center justify-center rounded-lg">
                <SiteIcon name={item.icon} className="text-lg" />
              </span>
              <h3 className="text-site-ink mt-4 text-base font-semibold">
                {t(`${item.key}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t(`${item.key}Desc`)}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </SiteSection>
  );
}
