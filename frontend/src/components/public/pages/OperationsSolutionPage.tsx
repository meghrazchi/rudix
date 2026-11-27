"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  QueryList,
  SecondaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  SourceChips,
  StepGrid,
} from "@/components/public/site/SiteBlocks";
import {
  MockAnswer,
  MockFrame,
  MockQuestion,
} from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteSection,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "archive", icon: "inventory_2" },
  { key: "steps", icon: "timer" },
  { key: "risk", icon: "warning" },
] as const;

const SOURCES = [
  { key: "runbooks", icon: "description" },
  { key: "sops", icon: "menu_book" },
  { key: "troubleshooting", icon: "build" },
  { key: "deployment", icon: "rocket_launch" },
  { key: "escalation", icon: "notification_important" },
  { key: "recovery", icon: "settings_backup_restore" },
] as const;

/** Operations solution page (minimal modern redesign, shared solution kit). */
export function OperationsSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.operations");
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
        id="ops-hero-title"
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
          <MockFrame>
            <MockQuestion>{t("exampleQueries.mockQuestion")}</MockQuestion>
            <MockAnswer
              label="Rudix"
              sources={[t("exampleQueries.mockCitations")]}
            >
              <p className="font-medium break-words">
                {t("exampleQueries.mockIntro")}
              </p>
              <ul className="text-site-ink-muted mt-2 space-y-1.5 font-mono text-xs leading-5 break-words">
                <li>{t("exampleQueries.mockStep1")}</li>
                <li>{t("exampleQueries.mockStep2")}</li>
                <li>{t("exampleQueries.mockStep3")}</li>
              </ul>
            </MockAnswer>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="ops-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="ops-problem-title"
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

      <SiteSection labelledBy="ops-doc-sources-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="ops-doc-sources-title"
              title={t("documentSources.heading")}
              description={t("documentSources.description")}
            />
            <div className="mt-8">
              <SourceChips
                items={SOURCES.map((s) => ({
                  icon: s.icon,
                  label: t(`documentSources.${s.key}`),
                }))}
              />
            </div>
          </div>
          <div className="border-site-border bg-site-muted relative aspect-[4/3] w-full overflow-hidden rounded-2xl border">
            <Image
              src="/images/solutions/operations/terminal-ops.jpg"
              alt={t("terminalImageAlt")}
              fill
              className="object-cover"
              sizes="(max-width: 1024px) 100vw, 50vw"
            />
          </div>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="ops-flow-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="ops-flow-title"
          title={t("howItWorks.heading")}
          description={t("howItWorks.description")}
        />
        <div className="mt-12">
          <StepGrid
            steps={[1, 2, 3, 4].map((n) => ({
              title: t(`howItWorks.step${n}Title`),
              description: t(`howItWorks.step${n}Body`),
            }))}
          />
        </div>
      </SiteSection>

      <SiteSection labelledBy="ops-queries-title">
        <SectionHeading
          id="ops-queries-title"
          title={t("exampleQueries.heading")}
          description={t("exampleQueries.description")}
        />
        <div className="mt-10 max-w-3xl">
          <QueryList
            items={[1, 2, 3].map((n) => `"${t(`exampleQueries.q${n}`)}"`)}
          />
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="ops-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
        secondary={{ href: links.requestDemo, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
