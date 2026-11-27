"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  SecondaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  StepGrid,
} from "@/components/public/site/SiteBlocks";
import { MockFrame } from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "overload", icon: "cloud_off" },
  { key: "manual", icon: "description" },
  { key: "citations", icon: "link" },
  { key: "fragmentation", icon: "troubleshoot" },
] as const;

const SOURCES = [
  { key: "whitepapers", icon: "article" },
  { key: "marketResearch", icon: "query_stats" },
  { key: "analystReports", icon: "lab_profile" },
  { key: "technicalPapers", icon: "science" },
  { key: "strategyDocs", icon: "account_tree" },
] as const;

const QUERIES = [
  { n: 1, icon: "help" },
  { n: 2, icon: "security" },
  { n: 3, icon: "compare" },
  { n: 4, icon: "find_in_page" },
] as const;

function FlowNode({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="border-site-border bg-site-canvas flex min-w-0 items-center gap-3 rounded-xl border px-4 py-3">
      <span className="bg-site-accent-soft text-site-accent-ink flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
        <SiteIcon name={icon} className="text-base" />
      </span>
      <span className="text-site-ink min-w-0 text-sm font-medium break-words">
        {label}
      </span>
    </div>
  );
}

function FlowConnector() {
  return (
    <div className="flex justify-center">
      <SiteIcon
        name="arrow_downward"
        className="text-site-ink-subtle text-lg"
      />
    </div>
  );
}

/** Research solution page (minimal modern redesign, shared solution kit). */
export function ResearchSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.research");
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
        id="research-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <>
            <PrimaryLink
              href={links.requestDemo}
              label={t("hero.primaryCta")}
            />
            <SecondaryLink href={links.docs} label={t("hero.secondaryCta")} />
          </>
        }
        aside={
          <figure className="border-site-border bg-site-surface w-full rounded-2xl border p-2 shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]">
            <div className="relative h-64 w-full overflow-hidden rounded-xl sm:h-72">
              <Image
                src="/images/solutions/research/analyst-dashboard.jpg"
                alt="Enterprise research analyst dashboard showing data visualizations and document insights"
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
        labelledBy="research-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="research-problem-title"
          title={t("problems.heading")}
          description={t("problems.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-2">
          {PROBLEMS.map((item) => (
            <IconCard
              key={item.key}
              icon={item.icon}
              title={t(`problems.${item.key}Title`)}
              body={t(`problems.${item.key}Body`)}
            />
          ))}
        </ul>
      </SiteSection>

      <SiteSection labelledBy="research-doc-sources-title">
        <SectionHeading
          id="research-doc-sources-title"
          title={t("documentSources.heading")}
          description={t("documentSources.description")}
        />
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {SOURCES.map((s) => (
            <li
              key={s.key}
              className="border-site-border bg-site-surface hover:border-site-accent/40 min-w-0 rounded-2xl border p-5 transition-colors"
            >
              <SiteIcon name={s.icon} className="text-site-accent text-xl" />
              <p className="text-site-ink mt-4 text-sm font-semibold break-words">
                {t(`documentSources.${s.key}`)}
              </p>
              <p className="text-site-ink-muted mt-1 text-sm leading-6">
                {t(`documentSources.${s.key}Desc`)}
              </p>
            </li>
          ))}
        </ul>
      </SiteSection>

      <SiteSection
        labelledBy="research-pipeline-title"
        className="bg-site-surface border-site-border border-y"
      >
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-7">
            <SectionHeading
              id="research-pipeline-title"
              title={t("pipeline.heading")}
            />
          </div>
          <div className="min-w-0 lg:col-span-5">
            <MockFrame>
              <FlowNode icon="picture_as_pdf" label={t("pipeline.svgSource")} />
              <FlowConnector />
              <div className="grid gap-3 sm:grid-cols-2">
                <FlowNode icon="hub" label={t("pipeline.svgEmbeddings")} />
                <FlowNode icon="database" label={t("pipeline.svgVectorDb")} />
              </div>
              <FlowConnector />
              <FlowNode icon="insights" label={t("pipeline.svgInsights")} />
            </MockFrame>
          </div>
        </div>
        <div className="mt-12">
          <StepGrid
            columns={3}
            steps={[1, 2, 3].map((n) => ({
              title: t(`pipeline.step${n}Title`),
              description: t(`pipeline.step${n}Body`),
            }))}
          />
        </div>
      </SiteSection>

      <SiteSection labelledBy="research-queries-title">
        <SectionHeading
          id="research-queries-title"
          title={t("exampleQueries.heading")}
          description={t("exampleQueries.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-2">
          {QUERIES.map((q) => (
            <li
              key={q.n}
              className="border-site-border bg-site-surface flex min-w-0 items-start gap-4 rounded-2xl border p-6"
            >
              <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
                <SiteIcon name={q.icon} className="text-xl" />
              </span>
              <div className="min-w-0">
                <p className="text-site-ink text-base font-semibold break-words">
                  {t(`exampleQueries.q${q.n}`)}
                </p>
                <p className="text-site-ink-muted mt-2 text-sm leading-6">
                  {t(`exampleQueries.a${q.n}`)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </SiteSection>

      <SiteCtaPanel
        id="research-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.startTrial, label: t("cta.primaryCta") }}
        secondary={{ href: links.requestDemo, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
