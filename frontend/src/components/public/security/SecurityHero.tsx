import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PRIMARY_BUTTON_CLASS,
  SECONDARY_BUTTON_CLASS,
  SiteIcon,
} from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";

const POSTURE = [
  { callout: "orgIsolationCallout", title: "orgIsolationTitle" },
  { callout: "accessControlCallout", title: "accessControlTitle" },
  { callout: "auditLogsCallout", title: "auditLogsTitle" },
  { callout: "encryptionCallout", title: "encryptionTitle" },
] as const;

function PostureCard() {
  const t = useTranslations("public.security");

  return (
    <div className="border-site-border bg-site-surface rounded-2xl border p-6 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)] sm:p-7">
      <div className="border-site-border mb-5 flex items-center gap-2.5 border-b pb-5">
        <SiteIcon name="verified_user" className="text-site-accent text-xl" />
        <p className="text-site-ink text-sm font-semibold">
          {t("hero.postureLabel")}
        </p>
      </div>
      <ul className="space-y-4">
        {POSTURE.map((item) => (
          <li key={item.callout} className="flex items-start gap-3">
            <span className="bg-site-success-soft text-site-success mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
              <SiteIcon name="check" className="text-sm" />
            </span>
            <div>
              <p className="text-site-ink text-sm font-medium">
                {t(`pillars.${item.callout}`)}
              </p>
              <p className="text-site-ink-subtle text-xs">
                {t(`pillars.${item.title}`)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SecurityHero({ links }: { links: PublicSiteLinks }) {
  const t = useTranslations("public.security.hero");

  return (
    <section
      aria-labelledby="security-hero-title"
      className="relative overflow-hidden px-4 pt-16 pb-20 lg:px-8 lg:pt-24 lg:pb-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-[radial-gradient(50%_60%_at_25%_0%,var(--site-accent-soft),transparent)]"
      />
      <div className="relative mx-auto grid w-full max-w-6xl items-center gap-14 lg:grid-cols-12">
        <div className="rudix-site-rise min-w-0 lg:col-span-7">
          <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
            <SiteIcon name="shield" className="text-site-accent text-sm" />
            {t("badge")}
          </p>
          <h1
            id="security-hero-title"
            className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl"
          >
            {t("heading")}
          </h1>
          <p className="text-site-ink-muted mt-6 max-w-xl text-base leading-7 md:text-lg md:leading-8">
            {t("description")}
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row">
            <PublicActionLink
              href={links.securityContact}
              className={PRIMARY_BUTTON_CLASS}
            >
              {t("primaryCta")}
              <SiteIcon name="arrow_forward" className="rtl-mirror text-base" />
            </PublicActionLink>
            <PublicActionLink
              href={links.docs}
              className={SECONDARY_BUTTON_CLASS}
            >
              {t("secondaryCta")}
            </PublicActionLink>
          </div>
        </div>
        <div className="rudix-site-rise min-w-0 lg:col-span-5">
          <PostureCard />
        </div>
      </div>
    </section>
  );
}
