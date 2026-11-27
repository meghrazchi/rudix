"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { ContactDemoFormCard } from "@/components/public/pages/contact/ContactDemoFormCard";
import { SiteIcon, TEXT_LINK_CLASS } from "@/components/public/site/primitives";
import type { PublicSiteLinks } from "@/lib/public-site/links";
import type { ContactSubmissionConfig } from "@/lib/public-site/contact";

type ContactDemoSectionsProps = {
  links: PublicSiteLinks;
  submissionConfig: ContactSubmissionConfig;
};

export function ContactHeroSection() {
  const t = useTranslations("public.contact");

  return (
    <section
      aria-labelledby="contact-hero-title"
      className="relative overflow-hidden px-4 pt-16 pb-12 lg:px-8 lg:pt-24 lg:pb-16"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(60%_60%_at_50%_0%,var(--site-accent-soft),transparent)]"
      />
      <div className="rudix-site-rise relative mx-auto max-w-3xl text-center">
        <p className="border-site-border bg-site-surface text-site-ink-muted inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
          <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
          {t("hero.badge")}
        </p>
        <h1
          id="contact-hero-title"
          className="text-site-ink mt-6 text-4xl font-semibold tracking-[-0.03em] text-balance break-words hyphens-auto sm:text-5xl lg:hyphens-manual"
        >
          {t("hero.heading")}
        </h1>
        <p className="text-site-ink-muted mx-auto mt-6 max-w-2xl text-base leading-7 md:text-lg md:leading-8">
          {t("hero.description")}
        </p>
      </div>
    </section>
  );
}

const CONTACT_CARDS = [
  { key: "sales", icon: "handshake" },
  { key: "support", icon: "support_agent" },
  { key: "security", icon: "shield" },
  { key: "status", icon: "menu_book" },
] as const;

export function ContactMainSection({
  links,
  submissionConfig,
}: ContactDemoSectionsProps) {
  const t = useTranslations("public.contact");
  const hrefs: Record<(typeof CONTACT_CARDS)[number]["key"], string> = {
    sales: links.contact,
    support: links.contact,
    security: links.securityContact,
    status: links.docs,
  };

  return (
    <section
      aria-label={t("hero.heading")}
      className="px-4 pb-20 lg:px-8 lg:pb-28"
    >
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-7">
          <ContactDemoFormCard
            submissionConfig={submissionConfig}
            supportHref={links.contact}
            schedulerHref={submissionConfig.schedulerUrl}
          />
        </div>
        <div className="min-w-0 space-y-6 lg:col-span-5">
          <article className="border-site-accent/25 bg-site-accent-soft rounded-2xl border p-7">
            <h2 className="text-site-ink text-xl font-semibold">
              {t("goodFit.heading")}
            </h2>
            <ul className="mt-5 space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <li
                  key={i}
                  className="text-site-ink flex items-start gap-2.5 text-sm leading-6"
                >
                  <SiteIcon
                    name="check_circle"
                    className="text-site-accent mt-0.5 text-lg"
                  />
                  {t(`goodFit.item${i}`)}
                </li>
              ))}
            </ul>
          </article>
          <div className="grid gap-4 sm:grid-cols-2">
            {CONTACT_CARDS.map((card) => (
              <article
                key={card.key}
                className="border-site-border bg-site-surface flex flex-col rounded-2xl border p-5"
              >
                <SiteIcon
                  name={card.icon}
                  className="text-site-accent text-xl"
                />
                <h3 className="text-site-ink mt-3 text-base font-semibold">
                  {t(`cards.${card.key}Title`)}
                </h3>
                <p className="text-site-ink-muted mt-1.5 text-sm leading-6">
                  {t(`cards.${card.key}Desc`)}
                </p>
                <PublicActionLink
                  href={hrefs[card.key]}
                  className={`${TEXT_LINK_CLASS} mt-auto pt-4`}
                >
                  {t(`cards.${card.key}Cta`)}
                  <SiteIcon
                    name="arrow_forward"
                    className="rtl-mirror text-base"
                  />
                </PublicActionLink>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
