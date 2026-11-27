"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  IconCard,
  PrimaryLink,
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
  TEXT_LINK_CLASS,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const SOURCES = [
  { key: "securityPolicies", icon: "gpp_good" },
  { key: "auditEvidence", icon: "fact_check" },
  { key: "riskAssessments", icon: "warning" },
  { key: "accessReviews", icon: "group" },
  { key: "incidentResponse", icon: "emergency" },
] as const;

const EXAMPLES = [
  { key: "retention", icon: "question_mark" },
  { key: "accessReviews", icon: "verified" },
  { key: "encryption", icon: "enhanced_encryption" },
] as const;

const TRUST_FEATURES = [
  { key: "auditRefs", icon: "menu_book" },
  { key: "permFilter", icon: "lock_person" },
  { key: "activityLogs", icon: "receipt_long" },
] as const;

/** Compliance solution page (minimal modern redesign, shared solution kit). */
export function ComplianceSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.compliance");
  const links = resolvePublicSiteLinks();

  // Illustrative activity rows shown inside the decorative audit-trail mock.
  const activity = [
    {
      action: t("trust.auditLogRetrieval"),
      doc: "SOC2_v2",
      meta: `${t("trust.userPrefix")} j_smith@enterprise.com • 2m ago`,
      badge: t("trust.verifiedBadge"),
      tone: "success" as const,
      dim: false,
    },
    {
      action: t("trust.sourceDownload"),
      doc: "ISO_Annex_A",
      meta: `${t("trust.userPrefix")} k_chen@corp.com • 15m ago`,
      badge: t("trust.verifiedBadge"),
      tone: "success" as const,
      dim: false,
    },
    {
      action: t("trust.newDocumentIndexed"),
      doc: "Q4_Evidence_01",
      meta: `${t("trust.systemPrefix")} • 1h ago`,
      badge: t("trust.indexedBadge"),
      tone: "accent" as const,
      dim: true,
    },
  ];

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
        id="compliance-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <PrimaryLink href={links.requestDemo} label={t("hero.primaryCta")} />
        }
        aside={
          <MockFrame title={t("hero.engineLabel")}>
            <MockQuestion>{t("hero.queryExample")}</MockQuestion>
            <div className="border-site-border rounded-2xl border p-4">
              <p className="text-site-ink-muted flex items-center gap-2 text-xs font-medium">
                <SiteIcon name="shield" className="text-site-accent text-sm" />
                {t("hero.retrievingEvidence")}
              </p>
              <div className="bg-site-muted mt-3 h-1 overflow-hidden rounded-full">
                <div className="bg-site-accent h-full w-2/3 rounded-full" />
              </div>
              <p className="text-site-ink mt-4 text-xs font-semibold">
                {t("hero.matchesFound")}
              </p>
              <ul className="mt-2 space-y-1.5">
                {[t("hero.match1"), t("hero.match2")].map((match) => (
                  <li
                    key={match}
                    className="bg-site-canvas flex min-w-0 items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs"
                  >
                    <SiteIcon
                      name="description"
                      className="text-site-ink-subtle text-sm"
                    />
                    <span className="text-site-ink-muted min-w-0 truncate">
                      {match}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="compliance-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="compliance-problem-title"
          title={t("problems.heading")}
          description={t("problems.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
          <IconCard
            icon="folder_off"
            title={t("problems.evidenceFragTitle")}
            body={t("problems.evidenceFragBody")}
          />
          <IconCard
            icon="link"
            title={t("problems.traceabilityTitle")}
            body={t("problems.traceabilityBody")}
          />
          <IconCard
            icon="timer"
            title={t("problems.manualDrainTitle")}
            body={t("problems.manualDrainBody")}
          />
        </ul>
      </SiteSection>

      <SiteSection labelledBy="compliance-doc-sources-title">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-6">
            <SectionHeading
              id="compliance-doc-sources-title"
              title={t("documentSources.heading")}
              description={t("documentSources.description")}
            />
          </div>
          <ul className="grid min-w-0 gap-3 sm:grid-cols-2 lg:col-span-6">
            {SOURCES.map((s) => (
              <li
                key={s.key}
                className="border-site-border bg-site-surface flex min-w-0 items-center gap-3 rounded-2xl border px-4 py-3.5"
              >
                <span className="bg-site-accent-soft text-site-accent-ink flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                  <SiteIcon name={s.icon} className="text-lg" />
                </span>
                <span className="text-site-ink min-w-0 text-sm font-medium break-words">
                  {t(`documentSources.${s.key}`)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="compliance-questions-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="compliance-questions-title"
          title={t("examples.heading")}
          description={t("examples.description")}
        />
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
          {EXAMPLES.map((e) => (
            <li
              key={e.key}
              className="border-site-border bg-site-surface min-w-0 rounded-2xl border p-6"
            >
              <SiteIcon name={e.icon} className="text-site-accent text-xl" />
              <p className="text-site-ink mt-4 text-base font-semibold break-words">
                {`"${t(`examples.${e.key}Q`)}"`}
              </p>
              <p className="text-site-ink-muted border-site-border mt-4 border-t pt-4 text-sm leading-6">
                {t(`examples.${e.key}A`)}
              </p>
            </li>
          ))}
        </ul>
      </SiteSection>

      <SiteSection labelledBy="compliance-trust-title">
        <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="compliance-trust-title"
              title={t("trust.heading")}
              description={t("trust.description")}
            />
            <ul className="mt-8 space-y-5">
              {TRUST_FEATURES.map((f) => (
                <li key={f.key} className="flex items-start gap-4">
                  <span className="border-site-border bg-site-surface text-site-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border">
                    <SiteIcon name={f.icon} className="text-xl" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-site-ink text-base font-semibold">
                      {t(`trust.${f.key}Title`)}
                    </h3>
                    <p className="text-site-ink-muted mt-1 text-sm leading-6">
                      {t(`trust.${f.key}Body`)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
            <div className="border-site-border bg-site-surface mt-8 rounded-2xl border p-5">
              <p className="text-site-ink flex items-center gap-2 text-sm font-semibold">
                <SiteIcon name="info" className="text-site-accent text-base" />
                {t("trust.disclaimerLabel")}
              </p>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t("trust.disclaimerText")}
              </p>
              <PublicActionLink
                href={links.security}
                className={`${TEXT_LINK_CLASS} mt-3`}
              >
                {t("trust.securityCta")}
                <SiteIcon
                  name="arrow_forward"
                  className="rtl-mirror text-base"
                />
              </PublicActionLink>
            </div>
          </div>

          <MockFrame title={t("trust.activityStream")}>
            <ul className="space-y-2.5">
              {activity.map((item) => (
                <li
                  key={item.doc}
                  className={`border-site-border bg-site-canvas flex min-w-0 items-center justify-between gap-3 rounded-xl border p-3.5 ${
                    item.dim ? "opacity-60" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <p className="text-site-ink text-sm break-words">
                      {item.action}:{" "}
                      <strong className="font-semibold">{item.doc}</strong>
                    </p>
                    <p className="text-site-ink-subtle mt-0.5 truncate text-xs">
                      {item.meta}
                    </p>
                  </div>
                  <StatusPill tone={item.tone}>{item.badge}</StatusPill>
                </li>
              ))}
            </ul>
            <p className="text-site-accent-ink border-site-border border-t pt-3 text-center text-xs font-semibold">
              {t("trust.viewFullAuditTrail")}
            </p>
          </MockFrame>
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="compliance-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
        secondary={{ href: links.docs, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
