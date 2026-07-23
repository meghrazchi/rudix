"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { ContactDemoFormCard } from "@/components/public/pages/contact/ContactDemoFormCard";
import type { PublicSiteLinks } from "@/lib/public-site/links";
import type { ContactSubmissionConfig } from "@/lib/public-site/contact";

type ContactDemoSectionsProps = {
  links: PublicSiteLinks;
  submissionConfig: ContactSubmissionConfig;
};

export function ContactHeroSection() {
  const t = useTranslations("public.contact");

  return (
    <section className="mx-auto w-full max-w-7xl px-4 pt-14 pb-12 lg:px-8 lg:pt-20 lg:pb-16">
      <span className="text-xs font-bold tracking-[0.13em] text-[#3f37cd] uppercase">
        {t("hero.badge")}
      </span>
      <h1 className="mt-3 max-w-4xl text-4xl leading-tight font-black text-[#10131c] lg:text-6xl">
        {t("hero.heading")}
      </h1>
      <p className="mt-4 max-w-3xl text-sm leading-8 text-[#5c6278] lg:text-lg">
        {t("hero.description")}
      </p>
    </section>
  );
}

export function ContactMainSection({
  links,
  submissionConfig,
}: ContactDemoSectionsProps) {
  const t = useTranslations("public.contact");

  const fitHighlights = [
    t("goodFit.item0"),
    t("goodFit.item1"),
    t("goodFit.item2"),
    t("goodFit.item3"),
  ];

  const cards = [
    {
      title: t("cards.salesTitle"),
      desc: t("cards.salesDesc"),
      cta: t("cards.salesCta"),
      href: links.contact,
    },
    {
      title: t("cards.supportTitle"),
      desc: t("cards.supportDesc"),
      cta: t("cards.supportCta"),
      href: links.contact,
    },
    {
      title: t("cards.securityTitle"),
      desc: t("cards.securityDesc"),
      cta: t("cards.securityCta"),
      href: links.securityContact,
    },
    {
      title: t("cards.statusTitle"),
      desc: t("cards.statusDesc"),
      cta: t("cards.statusCta"),
      href: links.docs,
    },
  ];

  return (
    <section className="mx-auto w-full max-w-7xl px-4 pb-16 lg:px-8 lg:pb-20">
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <ContactDemoFormCard
            submissionConfig={submissionConfig}
            supportHref={links.contact}
            schedulerHref={submissionConfig.schedulerUrl}
          />
        </div>

        <div className="space-y-6 lg:col-span-5">
          <article className="rounded-xl bg-[#3525cd] p-7 text-white shadow-sm md:p-9">
            <h2 className="text-2xl font-black">{t("goodFit.heading")}</h2>
            <ul className="mt-5 space-y-3">
              {fitHighlights.map((highlight) => (
                <li key={highlight} className="flex items-start gap-2">
                  <span
                    className="material-symbols-outlined mt-0.5 text-[#8af1a8]"
                    aria-hidden="true"
                  >
                    check_circle
                  </span>
                  <span className="text-sm leading-7 text-white/90">
                    {highlight}
                  </span>
                </li>
              ))}
            </ul>
          </article>

          <article className="rounded-xl border border-[#2e3140] bg-[#1f1f24] p-6 text-white shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.08em] text-[#c5cae0] uppercase">
                <span className="h-2 w-2 rounded-full bg-[#108548]" />
                {t("systemHealth.label")}
              </div>
              <span className="text-xs text-[#9ca2bd]">
                {t("systemHealth.operational")}
              </span>
            </div>
            <ul className="space-y-1.5 text-sm text-[#d6dbf0]">
              <li>{t("systemHealth.ingestion")}</li>
              <li>{t("systemHealth.retrieval")}</li>
              <li>{t("systemHealth.evaluation")}</li>
              <li>{t("systemHealth.audit")}</li>
            </ul>
          </article>

          <div className="grid gap-4 sm:grid-cols-2">
            {cards.map((card) => (
              <article
                key={card.title}
                className="rounded-xl border border-[#d8dce8] bg-white p-5 shadow-sm"
              >
                <h3 className="text-lg font-bold text-[#1a1f30]">
                  {card.title}
                </h3>
                <p className="mt-2 text-sm leading-7 text-[#5b6278]">
                  {card.desc}
                </p>
                <PublicActionLink
                  href={card.href}
                  className="mt-4 inline-block text-sm font-semibold text-[#3128ad] underline decoration-[#b8bde9]"
                >
                  {card.cta}
                </PublicActionLink>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function ContactMapSection() {
  return (
    <section className="mx-auto w-full max-w-7xl px-4 pb-16 lg:px-8 lg:pb-24"></section>
  );
}
