"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
} from "@/components/public/site/SiteBlocks";
import { MockAnswer, MockQuestion } from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "questionnaires", icon: "assignment_late" },
  { key: "contracts", icon: "compare_arrows" },
  { key: "risk", icon: "warning_amber" },
] as const;

const SOURCES = [
  { key: "soc2", icon: "description" },
  { key: "rfp", icon: "fact_check" },
  { key: "contracts", icon: "gavel" },
  { key: "questionnaires", icon: "security" },
] as const;

const STEPS = [
  { key: "01", icon: "manage_search", hasBody: true },
  { key: "02", icon: "data_object", hasBody: true },
  { key: "03", icon: "report", hasBody: false },
  { key: "04", icon: "verified", hasBody: false },
] as const;

/** Procurement solution page (minimal modern redesign, shared solution kit). */
export function ProcurementSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.procurement");
  const links = resolvePublicSiteLinks();

  return (
    <div className="bg-site-canvas text-site-ink">
      <SiteBreadcrumb
        items={[
          { label: tp("home"), href: "/" },
          { label: tp("breadcrumb.solutions"), href: "/solutions" },
          { label: t("breadcrumb") },
        ]}
      />

      <SiteSplitHero
        id="proc-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <>
            <PrimaryLink
              href={links.requestDemo}
              label={t("hero.secondaryCta")}
            />
          </>
        }
        aside={
          <figure className="border-site-border bg-site-surface w-full rounded-2xl border p-2 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]">
            <div className="relative aspect-[4/3] w-full overflow-hidden rounded-xl">
              <Image
                src="/images/solutions/procurement/vendor-dashboard.jpg"
                alt={t("heroImageAlt")}
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 50vw"
                priority
              />
            </div>
          </figure>
        }
      />

      <SiteSection
        labelledBy="proc-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="proc-problem-title"
          title={t("problems.heading")}
          description={t("problems.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
          {PROBLEMS.map((p) => (
            <IconCard
              key={p.key}
              icon={p.icon}
              title={t(`problems.${p.key}Title`)}
              body={t(`problems.${p.key}Body`)}
            />
          ))}
        </ul>
      </SiteSection>

      <SiteSection labelledBy="proc-doc-title">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="proc-doc-title"
              title={t("documentSources.heading")}
              description={t("documentSources.description")}
            />
            <ul className="mt-8 space-y-3">
              {[0, 1, 2].map((n) => (
                <li key={n} className="flex items-start gap-3">
                  <SiteIcon
                    name="check_circle"
                    className="text-site-success mt-0.5 text-lg"
                  />
                  <span className="text-site-ink-muted min-w-0 text-sm leading-6">
                    {t(`documentSources.feature${n}`)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <ul className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
            {SOURCES.map((s) => (
              <li
                key={s.key}
                className="border-site-border bg-site-surface flex min-w-0 items-center gap-3 rounded-2xl border p-5"
              >
                <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
                  <SiteIcon name={s.icon} className="text-xl" />
                </span>
                <span className="text-site-ink min-w-0 text-sm font-semibold break-words">
                  {t(`documentSources.${s.key}`)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="proc-engine-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="proc-engine-title"
          title={t("engine.heading")}
          description={t("engine.description")}
        />
        <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step) => (
            <li
              key={step.key}
              className="border-site-border bg-site-surface flex min-w-0 flex-col rounded-2xl border p-6"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="bg-site-accent-soft text-site-accent-ink rounded-full px-2.5 py-1 font-mono text-xs font-semibold">
                  {t(`engine.step${step.key}Label`)}
                </span>
                <SiteIcon
                  name={step.icon}
                  className="text-site-ink-subtle text-xl"
                />
              </div>
              <h3 className="text-site-ink mt-5 text-base font-semibold break-words">
                {t(`engine.step${step.key}Title`)}
              </h3>
              {step.hasBody ? (
                <p className="text-site-ink-muted mt-2 text-sm leading-6">
                  {t(`engine.step${step.key}Body`)}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      </SiteSection>

      <SiteSection labelledBy="proc-queries-title">
        <SectionHeading
          id="proc-queries-title"
          title={t("exampleQueries.heading")}
        />
        <ul className="mt-12 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {[1, 2].map((n) => (
            <li
              key={n}
              className="border-site-border bg-site-surface min-w-0 space-y-4 rounded-2xl border p-4 md:p-5"
            >
              <MockQuestion>{t(`exampleQueries.q${n}`)}</MockQuestion>
              <MockAnswer label={t("exampleQueries.analysisLabel")}>
                {t(`exampleQueries.a${n}`)}
              </MockAnswer>
            </li>
          ))}
        </ul>
        <p className="text-site-ink-muted mt-8 flex max-w-3xl items-start gap-2 text-sm leading-6">
          <SiteIcon name="info" className="text-site-accent mt-0.5 text-base" />
          <span className="min-w-0">{t("cta.disclaimer")}</span>
        </p>
      </SiteSection>

      <SiteCtaPanel
        id="proc-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
      />
    </div>
  );
}
