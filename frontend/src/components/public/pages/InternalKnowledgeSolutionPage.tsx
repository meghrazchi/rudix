"use client";

import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  QueryList,
  SecondaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  StepGrid,
} from "@/components/public/site/SiteBlocks";
import {
  MockAnswer,
  MockFrame,
  MockQuestion,
} from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
  StatusPill,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "silos", icon: "cloud_off" },
  { key: "onboarding", icon: "person_add" },
  { key: "slack", icon: "forum" },
] as const;

const DOC_TYPES = [
  { key: "sops", icon: "description" },
  { key: "handbooks", icon: "menu_book" },
  { key: "playbooks", icon: "play_circle" },
  { key: "manuals", icon: "school" },
] as const;

const FLOW_STEPS = ["upload", "index", "ask", "answer"] as const;

/** Renders the hero heading with the highlight phrase accented when present. */
function HighlightedHeading({
  heading,
  highlight,
}: {
  heading: string;
  highlight: string;
}) {
  const index = highlight ? heading.lastIndexOf(highlight) : -1;
  if (index < 0) return <>{heading}</>;
  return (
    <>
      {heading.slice(0, index)}
      <span className="text-site-accent-ink">{highlight}</span>
      {heading.slice(index + highlight.length)}
    </>
  );
}

/** Internal knowledge solution page (minimal modern redesign, shared kit). */
export function InternalKnowledgeSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.internalKnowledge");
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
        id="ik-hero-title"
        badge={t("hero.badge")}
        title={
          <HighlightedHeading
            heading={t("hero.heading")}
            highlight={t("hero.headingHighlight")}
          />
        }
        description={t("hero.description")}
        actions={
          <>
            <PrimaryLink href={links.startTrial} label={t("hero.primaryCta")} />
            <SecondaryLink
              href={links.requestDemo}
              label={t("hero.secondaryCta")}
            />
          </>
        }
        aside={
          <MockFrame>
            <MockQuestion>&quot;{t("hero.panelQuestion")}&quot;</MockQuestion>
            <MockAnswer label="Rudix" sources={[t("hero.panelSource")]}>
              <p className="break-words">
                {t("hero.panelIntro")}{" "}
                <strong className="font-semibold">
                  {t("hero.panelDocument")}
                </strong>
                :
              </p>
              <ul className="text-site-ink-muted mt-2 list-disc space-y-1.5 ps-4 text-xs leading-5">
                <li className="break-words">{t("hero.panelBullet1")}</li>
                <li className="break-words">{t("hero.panelBullet2")}</li>
                <li className="break-words">{t("hero.panelBullet3")}</li>
              </ul>
            </MockAnswer>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="ik-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="ik-problem-title"
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

      <SiteSection labelledBy="ik-doc-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="ik-doc-title"
              title={t("documents.heading")}
              description={t("documents.description")}
            />
            <ul className="mt-8 space-y-3">
              {[0, 1, 2].map((n) => (
                <li key={n} className="flex items-start gap-3">
                  <SiteIcon
                    name="check_circle"
                    className="text-site-success mt-0.5 text-xl"
                  />
                  <span className="text-site-ink min-w-0 text-sm leading-6 font-medium md:text-base">
                    {t(`documents.feature${n}`)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <ul className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
            {DOC_TYPES.map((d) => (
              <IconCard
                key={d.key}
                icon={d.icon}
                title={t(`documents.${d.key}Label`)}
                body={t(`documents.${d.key}Desc`)}
              />
            ))}
          </ul>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="ik-flow-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="ik-flow-title"
          title={t("flow.heading")}
          description={t("flow.description")}
        />
        <div className="mt-12">
          <StepGrid
            steps={FLOW_STEPS.map((key) => ({
              title: t(`flow.${key}Title`),
              description: t(`flow.${key}Desc`),
            }))}
          />
        </div>
        <div className="mt-8">
          <MockFrame>
            <StatusPill tone="success">
              <span className="bg-site-success h-1.5 w-1.5 rounded-full" />
              {t("flow.engineStatus")}
            </StatusPill>
            <pre className="border-site-border bg-site-canvas text-site-ink-muted overflow-x-auto rounded-xl border px-4 py-3 font-mono text-xs leading-5 break-words whitespace-pre-wrap">
              <code>{t("flow.codeSample")}</code>
            </pre>
          </MockFrame>
        </div>
      </SiteSection>

      <SiteSection labelledBy="ik-queries-title">
        <SectionHeading
          id="ik-queries-title"
          title={t("exampleQuestions.heading")}
        />
        <div className="mt-10 max-w-3xl">
          <QueryList
            items={[1, 2, 3, 4].map((n) => `"${t(`exampleQuestions.q${n}`)}"`)}
          />
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="ik-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
        secondary={{ href: links.pricing, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
