"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  SecondaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
} from "@/components/public/site/SiteBlocks";
import { MockFrame, MockQuestion } from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
  StatusPill,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "toolFatigue", icon: "search_off" },
  { key: "slowOnboarding", icon: "speed" },
  { key: "inconsistentData", icon: "sync_problem" },
] as const;

const SOURCES = [
  { key: "productDocumentation", icon: "menu_book" },
  { key: "troubleshootingGuides", icon: "build" },
  { key: "faqs", icon: "quiz" },
  { key: "releaseNotes", icon: "new_releases" },
  { key: "knownIssues", icon: "warning" },
  { key: "escalationRunbooks", icon: "priority_high" },
] as const;

const STEPS = [
  { n: 1, icon: "upload_file" },
  { n: 2, icon: "database" },
  { n: 3, icon: "chat" },
  { n: 4, icon: "verified" },
] as const;

/** Source excerpt rendered as a calm monospace block inside mocks. */
function MockSourceBlock({
  source,
  lines,
}: {
  source: string;
  lines: ReactNode[];
}) {
  return (
    <div className="border-site-border bg-site-canvas rounded-xl border px-4 py-3 font-mono text-xs leading-5">
      <p className="text-site-accent-ink font-semibold break-words">{source}</p>
      <ul className="text-site-ink-muted mt-2 space-y-1">
        {lines.map((line, index) => (
          <li key={index} className="break-words">
            {line}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Support solution page (minimal modern redesign, shared solution kit). */
export function SupportSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.support");
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
        id="support-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <>
            <PrimaryLink
              href={links.requestDemo}
              label={t("hero.primaryCta")}
            />
            <SecondaryLink
              href={links.contact}
              label={t("hero.secondaryCta")}
            />
          </>
        }
        aside={
          <MockFrame title={t("hero.workspaceLabel")}>
            <MockQuestion>{t("hero.workspaceQuestion")}</MockQuestion>
            <MockSourceBlock
              source={t("hero.workspaceSource")}
              lines={[
                t("hero.workspaceStep1"),
                t("hero.workspaceStep2"),
                t("hero.workspaceStep3"),
              ]}
            />
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="support-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="support-problem-title"
          title={t("problems.heading")}
          description={t("problems.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
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

      <SiteSection labelledBy="support-doc-sources-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="support-doc-sources-title"
              title={t("documentSources.heading")}
              description={t("documentSources.description")}
            />
            <ul className="mt-8 space-y-3">
              {[0, 1, 2].map((n) => (
                <li key={n} className="flex items-start gap-3">
                  <SiteIcon
                    name="check_circle"
                    className="text-site-success mt-0.5 text-xl"
                  />
                  <span className="text-site-ink-muted min-w-0 text-sm leading-6 md:text-base">
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
                className="border-site-border bg-site-surface flex min-w-0 items-start gap-3 rounded-2xl border p-4"
              >
                <span className="bg-site-accent-soft text-site-accent-ink flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
                  <SiteIcon name={s.icon} className="text-lg" />
                </span>
                <div className="min-w-0">
                  <p className="text-site-ink-subtle text-xs font-medium tracking-[0.06em] uppercase">
                    {t("documentSources.dataSourceLabel")}
                  </p>
                  <p className="text-site-ink mt-0.5 text-sm font-semibold break-words">
                    {t(`documentSources.${s.key}`)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="support-flow-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="support-flow-title"
          title={t("howItWorks.heading")}
          description={t("howItWorks.description")}
        />
        <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step) => (
            <IconCard
              key={step.n}
              icon={step.icon}
              title={t(`howItWorks.step${step.n}Title`)}
              body={t(`howItWorks.step${step.n}Body`)}
            />
          ))}
        </ol>
      </SiteSection>

      <SiteSection labelledBy="support-queries-title">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <SectionHeading
            id="support-queries-title"
            title={t("exampleQueries.heading")}
            description={t("exampleQueries.description")}
          />
          <div
            aria-hidden="true"
            className="border-site-border bg-site-surface inline-flex shrink-0 gap-1 self-start rounded-full border p-1 md:self-auto"
          >
            <span className="bg-site-muted text-site-ink rounded-full px-4 py-1.5 text-xs font-medium">
              {t("exampleQueries.agentView")}
            </span>
            <span className="text-site-ink-muted px-4 py-1.5 text-xs font-medium">
              {t("exampleQueries.adminView")}
            </span>
          </div>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-7">
            <MockFrame>
              <StatusPill tone="accent">
                <span className="bg-site-accent h-1.5 w-1.5 rounded-full" />
                {t("exampleQueries.activeQuery")}
              </StatusPill>
              <p className="text-site-ink text-base font-semibold break-words md:text-lg">
                &quot;{t("exampleQueries.mockQuestion")}&quot;
              </p>
              <MockSourceBlock
                source={t("exampleQueries.mockSource")}
                lines={[
                  t("exampleQueries.mockStep1"),
                  t("exampleQueries.mockStep2"),
                  t("exampleQueries.mockStep3"),
                ]}
              />
            </MockFrame>
          </div>

          <ul className="grid min-w-0 gap-4 lg:col-span-5">
            {[1, 2].map((n) => (
              <li
                key={n}
                className="border-site-border bg-site-surface rounded-2xl border p-5"
              >
                <h3 className="text-site-ink text-base font-semibold break-words">
                  &quot;{t(`exampleQueries.q${n}`)}&quot;
                </h3>
                <p className="text-site-ink-muted mt-2 text-sm leading-6 break-words">
                  &quot;{t(`exampleQueries.a${n}`)}&quot;
                </p>
              </li>
            ))}
            <li className="border-site-accent/30 bg-site-accent-soft rounded-2xl border p-5">
              <p className="text-site-accent-ink flex items-center gap-2 text-xs font-semibold tracking-[0.06em] uppercase">
                <SiteIcon name="auto_awesome" className="text-base" />
                {t("exampleQueries.smartSuggestLabel")}
              </p>
              <p className="text-site-ink mt-2 text-sm font-semibold">
                {t("exampleQueries.smartSuggest")}
              </p>
            </li>
          </ul>
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="support-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
