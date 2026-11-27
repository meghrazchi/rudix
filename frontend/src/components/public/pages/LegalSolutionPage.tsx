"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  IconCard,
  PrimaryLink,
  QueryList,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  SourceChips,
} from "@/components/public/site/SiteBlocks";
import {
  MockAnswer,
  MockFrame,
  MockQuestion,
  MockSnippet,
} from "@/components/public/site/SiteMocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
  TEXT_LINK_CLASS,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "longContracts", icon: "description" },
  { key: "repeatedQuestions", icon: "forum" },
  { key: "missedDeadlines", icon: "event_busy" },
] as const;

const SOURCES = [
  { key: "customerContracts", icon: "groups" },
  { key: "vendorAgreements", icon: "storefront" },
  { key: "ndas", icon: "lock" },
  { key: "dpas", icon: "gavel" },
  { key: "termsOfService", icon: "verified_user" },
  { key: "legalGuidance", icon: "library_books" },
] as const;

const TRUST_ROWS = [
  { key: "deepLinking", icon: "link" },
  { key: "auditTrails", icon: "history" },
  { key: "accessControls", icon: "admin_panel_settings" },
] as const;

/** Legal solution page (minimal modern redesign, shared solution kit). */
export function LegalSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.legal");
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
        id="legal-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <PrimaryLink href={links.requestDemo} label={t("hero.primaryCta")} />
        }
        aside={
          <MockFrame>
            <MockQuestion>{t("hero.queryExample")}</MockQuestion>
            <MockAnswer
              label="Rudix"
              sources={[t("hero.citation1"), t("hero.citation2")]}
            >
              {t("hero.answerText")}
            </MockAnswer>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="legal-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="legal-problem-title"
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

      <SiteSection labelledBy="legal-doc-sources-title">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <SectionHeading
              id="legal-doc-sources-title"
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
          <div className="border-site-border bg-site-surface rounded-2xl border p-6 lg:col-span-5">
            <span className="bg-site-success-soft text-site-success flex h-10 w-10 items-center justify-center rounded-xl">
              <SiteIcon name="bolt" className="text-xl" />
            </span>
            <p className="text-site-ink mt-4 text-base font-semibold">
              {t("documentSources.instantIngestion")}
            </p>
            <p className="text-site-ink-muted mt-1 text-sm leading-6">
              {t("documentSources.ingestionDesc")}
            </p>
          </div>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="legal-questions-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="legal-questions-title"
          eyebrow={t("questions.sectionLabel")}
          title={t("questions.heading")}
          description={t("questions.description")}
        />
        <div className="mt-10 max-w-3xl">
          <QueryList
            items={[1, 2, 3].map((n) => `"${t(`questions.q${n}`)}"`)}
          />
        </div>
      </SiteSection>

      <SiteSection labelledBy="legal-citations-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <MockFrame title={t("citations.viewerLabel")}>
            <MockSnippet
              label={t("citations.snippetLabel1")}
              body={t("citations.snippetBody1")}
            />
            <MockSnippet
              label={t("citations.snippetLabel2")}
              body={t("citations.snippetBody2")}
            />
          </MockFrame>
          <div>
            <SectionHeading
              id="legal-citations-title"
              title={t("citations.heading")}
              description={t("citations.description")}
            />
            <ul className="mt-8 space-y-4">
              {TRUST_ROWS.map((row) => (
                <li key={row.key} className="flex items-start gap-3">
                  <SiteIcon
                    name={row.icon}
                    className="text-site-accent mt-0.5 text-xl"
                  />
                  <p className="text-site-ink-muted text-sm leading-6">
                    <strong className="text-site-ink font-semibold">
                      {t(`citations.${row.key}Label`)}
                    </strong>{" "}
                    {t(`citations.${row.key}Detail`)}
                  </p>
                </li>
              ))}
            </ul>
            <div className="border-site-border bg-site-surface mt-8 rounded-2xl border p-5">
              <p className="text-site-ink flex items-center gap-2 text-sm font-semibold">
                <SiteIcon name="info" className="text-site-accent text-base" />
                {t("citations.responsibleUseLabel")}
              </p>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t("citations.responsibleUseText")}
              </p>
              <PublicActionLink
                href={links.security}
                className={`${TEXT_LINK_CLASS} mt-3`}
              >
                {t("citations.securityCta")}
                <SiteIcon
                  name="arrow_forward"
                  className="rtl-mirror text-base"
                />
              </PublicActionLink>
            </div>
          </div>
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="legal-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
