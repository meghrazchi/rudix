"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  SourceChips,
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

const SOURCES = [
  { key: "productSpecs", icon: "description" },
  { key: "caseStudies", icon: "auto_stories" },
  { key: "rfpTemplates", icon: "assignment" },
  { key: "pricingSheets", icon: "payments" },
  { key: "battlecards", icon: "military_tech" },
  { key: "proposalDecks", icon: "handshake" },
] as const;

const IMAGES = [
  {
    src: "/images/solutions/sales/collateral.jpg",
    altKey: "collateralAlt",
  },
  {
    src: "/images/solutions/sales/team-meeting.jpg",
    altKey: "teamMeetingAlt",
  },
  {
    src: "/images/solutions/sales/workspace.jpg",
    altKey: "workspaceAlt",
  },
  {
    src: "/images/solutions/sales/pricing.jpg",
    altKey: "pricingAlt",
  },
] as const;

function SalesProblemCards() {
  const t = useTranslations("public.sales");

  return (
    <ul className="mt-12 grid gap-4 md:grid-cols-3">
      <IconCard
        icon="search_off"
        title={t("problems.lostCaseStudiesTitle")}
        body={t("problems.lostCaseStudiesBody")}
      />
      <IconCard
        icon="history"
        title={t("problems.outdatedPricingTitle")}
        body={t("problems.outdatedPricingBody")}
      />
      <IconCard
        icon="swords"
        title={t("problems.battlecardFrictionTitle")}
        body={t("problems.battlecardFrictionBody")}
      />
    </ul>
  );
}

function SalesQueries() {
  const t = useTranslations("public.sales");

  return (
    <ul className="mt-10 space-y-3">
      <li className="border-site-border bg-site-surface flex items-start gap-4 rounded-2xl border px-5 py-4">
        <SiteIcon name="search" className="text-site-accent mt-0.5 text-xl" />
        <p className="text-site-ink min-w-0 flex-1 text-sm font-medium break-words md:text-base">
          {t("queries.q1")}
        </p>
      </li>
      <li className="border-site-accent/40 bg-site-surface rounded-2xl border px-5 py-4">
        <div className="flex items-start gap-4">
          <SiteIcon name="search" className="text-site-accent mt-0.5 text-xl" />
          <p className="text-site-ink min-w-0 flex-1 text-sm font-medium break-words md:text-base">
            {t("queries.q2")}
          </p>
        </div>
        <p className="border-site-accent/40 text-site-ink-muted ms-9 mt-3 border-s-2 ps-4 text-sm leading-6 break-words italic">
          {t("queries.q2Answer")}
        </p>
      </li>
      <li className="border-site-border bg-site-surface flex items-start gap-4 rounded-2xl border px-5 py-4">
        <SiteIcon name="search" className="text-site-accent mt-0.5 text-xl" />
        <p className="text-site-ink min-w-0 flex-1 text-sm font-medium break-words md:text-base">
          {t("queries.q3")}
        </p>
      </li>
    </ul>
  );
}

function SalesFlowMock() {
  const t = useTranslations("public.sales");

  const nodes = [
    { icon: "folder_zip", label: t("queries.knowledgeBase") },
    { icon: "verified_user", label: t("queries.securityDocs") },
    { icon: "record_voice_over", label: t("queries.aeQuery") },
  ];

  return (
    <MockFrame>
      <ul className="space-y-2">
        {nodes.map((node) => (
          <li
            key={node.label}
            className="border-site-border bg-site-canvas text-site-ink flex items-center gap-3 rounded-xl border px-4 py-3 text-sm"
          >
            <SiteIcon name={node.icon} className="text-site-accent text-lg" />
            <span className="min-w-0 flex-1">{node.label}</span>
            <SiteIcon
              name="arrow_forward"
              className="rtl-mirror text-site-ink-subtle text-base"
            />
          </li>
        ))}
      </ul>
      <div className="bg-site-accent-soft text-site-accent-ink flex items-center justify-center gap-2 rounded-xl px-4 py-4 text-sm font-semibold">
        <SiteIcon name="psychology" className="text-2xl" />
        Rudix
      </div>
    </MockFrame>
  );
}

/** Sales solution page (minimal modern redesign, shared solution kit). */
export function SalesSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.sales");
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
        id="sales-hero-title"
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
          <MockFrame>
            <MockQuestion>{t("hero.mockQuestion")}</MockQuestion>
            {/* Answer points 1 and 3 are omitted: they carry unsourced
                percentage claims that public pages must not display. */}
            <MockAnswer
              label="Rudix"
              sources={[t("hero.mockTag1"), t("hero.mockTag2")]}
            >
              <p>{t("hero.mockAnswerTitle")}</p>
              <p className="mt-1">
                <span className="text-site-accent-ink font-medium">
                  {t("hero.mockAnswer2Label")}
                </span>{" "}
                {t("hero.mockAnswer2Body")}
              </p>
            </MockAnswer>
            <div className="flex flex-wrap gap-2">
              <StatusPill tone="neutral">
                <SiteIcon name="sync" className="text-sm" />
                {t("hero.mockStatus1")}
              </StatusPill>
              <StatusPill tone="success">
                <SiteIcon name="check_circle" className="text-sm" />
                {t("hero.mockStatus2")}
              </StatusPill>
            </div>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="sales-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="sales-problem-title"
          title={t("problems.heading")}
          description={t("problems.description")}
        />
        <SalesProblemCards />
      </SiteSection>

      <SiteSection labelledBy="sales-doc-sources-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="sales-doc-sources-title"
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
          <div className="grid min-w-0 grid-cols-2 gap-3">
            {IMAGES.map((img) => (
              <div
                key={img.src}
                className="border-site-border bg-site-muted relative aspect-[4/3] overflow-hidden rounded-2xl border"
              >
                <Image
                  src={img.src}
                  alt={t(`images.${img.altKey}`)}
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
              </div>
            ))}
          </div>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="sales-queries-title"
        className="bg-site-surface border-site-border border-y"
      >
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="sales-queries-title"
              title={t("queries.heading")}
              description={t("queries.description")}
            />
            <SalesQueries />
          </div>
          <SalesFlowMock />
        </div>
      </SiteSection>

      <div className="pt-20 lg:pt-28">
        <SiteCtaPanel
          id="sales-cta-title"
          title={t("cta.heading")}
          description={t("cta.description")}
          primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
          secondary={{ href: links.pricing, label: t("cta.secondaryCta") }}
        />
      </div>
    </div>
  );
}
