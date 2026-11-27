"use client";

import { useTranslations } from "next-intl";

import {
  IconCard,
  PrimaryLink,
  SecondaryLink,
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
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const PROBLEMS = [
  { key: "repeatedQuestions", icon: "repeat" },
  { key: "hardToSearch", icon: "search_off" },
  { key: "accuracyGaps", icon: "verified_user" },
] as const;

const SOURCES = [
  { key: "handbook", icon: "menu_book" },
  { key: "benefits", icon: "health_and_safety" },
  { key: "leavePolicy", icon: "event_available" },
  { key: "expense", icon: "receipt_long" },
  { key: "remoteWork", icon: "home_work" },
  { key: "onboarding", icon: "checklist" },
  { key: "roleTransition", icon: "swap_horiz" },
  { key: "training", icon: "school" },
] as const;

const QUESTIONS = [
  "parentalLeave",
  "vacation",
  "expense",
  "notCovered",
] as const;

const SECURITY_FEATURES = [
  { key: "encryptionFeature", icon: "lock" },
  { key: "roleAccessFeature", icon: "admin_panel_settings" },
  { key: "auditLogFeature", icon: "history" },
] as const;

const SOLUTIONS_HREF = "/solutions";

function FlowSteps() {
  const t = useTranslations("public.hr");

  const steps = [
    {
      label: t("flow.step01"),
      title: t("flow.uploadTitle"),
      body: t("flow.uploadDesc"),
      detail: (
        <div className="border-site-border bg-site-canvas text-site-ink-muted space-y-1.5 rounded-xl border p-3 font-mono text-xs">
          <p className="flex min-w-0 items-center gap-2">
            <SiteIcon name="description" className="text-sm" />
            <span className="min-w-0 truncate">{t("flow.uploadFilename")}</span>
          </p>
          <p className="text-site-accent-ink flex items-center gap-2">
            <SiteIcon name="upload" className="text-sm" />
            <span>{t("flow.uploadProgress")}</span>
          </p>
        </div>
      ),
    },
    {
      label: t("flow.step02"),
      title: t("flow.indexTitle"),
      body: t("flow.indexDesc"),
      detail: (
        <div
          aria-hidden="true"
          className="border-site-border bg-site-canvas flex items-center gap-1.5 rounded-xl border p-3"
        >
          {[0, 1, 2, 3, 4].map((n) => (
            <span
              key={n}
              className={`h-1.5 flex-1 rounded-full ${
                n < 3 ? "bg-site-accent" : "bg-site-border"
              }`}
            />
          ))}
        </div>
      ),
    },
    {
      label: t("flow.step03"),
      title: t("flow.askTitle"),
      body: t("flow.askDesc"),
      detail: (
        <p className="border-site-border bg-site-canvas text-site-ink-muted rounded-full border px-4 py-2 text-xs break-words italic">
          {t("flow.askQuery")}
        </p>
      ),
    },
    {
      label: t("flow.step04"),
      title: t("flow.answerTitle"),
      body: t("flow.answerDesc"),
      detail: (
        <p className="bg-site-accent-soft text-site-ink rounded-xl px-3 py-2 text-xs leading-5 break-words">
          {t("flow.answerExample")}
        </p>
      ),
    },
  ];

  return (
    <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((step) => (
        <li
          key={step.title}
          className="border-site-border bg-site-surface flex min-w-0 flex-col rounded-2xl border p-6"
        >
          <span className="bg-site-accent-soft text-site-accent-ink self-start rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold">
            {step.label}
          </span>
          <h3 className="text-site-ink mt-5 text-base font-semibold">
            {step.title}
          </h3>
          <p className="text-site-ink-muted mt-2 grow text-sm leading-6">
            {step.body}
          </p>
          <div className="mt-6">{step.detail}</div>
        </li>
      ))}
    </ol>
  );
}

function QuestionAccordion() {
  const t = useTranslations("public.hr");

  return (
    <ul className="mt-10 max-w-3xl space-y-3">
      {QUESTIONS.map((key) => (
        <li key={key}>
          <details className="group border-site-border bg-site-surface rounded-2xl border">
            <summary className="flex cursor-pointer list-none items-start gap-4 rounded-2xl px-5 py-4">
              <SiteIcon
                name="search"
                className="text-site-accent mt-0.5 text-xl"
              />
              <span className="text-site-ink min-w-0 flex-1 text-sm font-medium break-words md:text-base">
                {`"${t(`exampleQuestions.${key}Q`)}"`}
              </span>
              <SiteIcon
                name="expand_more"
                className="text-site-ink-subtle text-xl transition-transform group-open:rotate-180"
              />
            </summary>
            <div className="border-site-border border-t px-5 pt-4 pb-5">
              <MockAnswer
                label={t("exampleQuestions.engineLabel")}
                sources={[t(`exampleQuestions.${key}Citation`)]}
              >
                {t(`exampleQuestions.${key}A`)}
              </MockAnswer>
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}

/** HR solution page (minimal modern redesign, shared solution kit). */
export function HRSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.hr");
  const links = resolvePublicSiteLinks();

  return (
    <div className="bg-site-canvas text-site-ink">
      <SiteBreadcrumb
        items={[
          { label: tp("home"), href: "/" },
          { label: tp("breadcrumb.solutions"), href: SOLUTIONS_HREF },
          { label: t("breadcrumb") },
        ]}
      />

      <SiteSplitHero
        id="hr-hero-title"
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
              href={SOLUTIONS_HREF}
              label={t("hero.secondaryCta")}
            />
          </>
        }
        aside={
          <MockFrame title={t("hero.assistantLabel")}>
            <ul className="space-y-2">
              {[t("hero.q0"), t("hero.q1"), t("hero.q2")].map((q) => (
                <li
                  key={q}
                  className="border-site-border text-site-ink-muted flex items-center gap-2 rounded-xl border px-3 py-2 text-sm"
                >
                  <SiteIcon
                    name="chat_bubble"
                    className="text-site-ink-subtle text-base"
                  />
                  <span className="min-w-0">{q}</span>
                </li>
              ))}
            </ul>
            <MockAnswer
              label={t("hero.engineLabel")}
              sources={[t("hero.engineCitation")]}
            >
              {t("hero.engineAnswer")}
            </MockAnswer>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="hr-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="hr-problem-title"
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

      <SiteSection labelledBy="hr-flow-title">
        <SectionHeading
          id="hr-flow-title"
          title={t("flow.heading")}
          description={t("flow.description")}
        />
        <FlowSteps />
      </SiteSection>

      <SiteSection
        labelledBy="hr-doc-sources-title"
        className="bg-site-surface border-site-border border-y"
      >
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="hr-doc-sources-title"
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
          <MockFrame title={t("documentSources.exampleQA")}>
            {([1, 2] as const).map((n) => (
              <div key={n} className="space-y-3">
                <MockQuestion>{t(`documentSources.q${n}`)}</MockQuestion>
                <MockAnswer sources={[t(`documentSources.a${n}Source`)]}>
                  {t(`documentSources.a${n}`)}
                </MockAnswer>
              </div>
            ))}
          </MockFrame>
        </div>
      </SiteSection>

      <SiteSection labelledBy="hr-questions-title">
        <SectionHeading
          id="hr-questions-title"
          eyebrow={t("exampleQuestions.sectionLabel")}
          title={t("exampleQuestions.heading")}
        />
        <QuestionAccordion />
      </SiteSection>

      <SiteSection
        labelledBy="hr-security-title"
        className="bg-site-surface border-site-border border-y"
      >
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="hr-security-title"
              title={t("security.heading")}
              description={t("security.description")}
            />
            <ul className="mt-8 space-y-4">
              {SECURITY_FEATURES.map((f) => (
                <li key={f.key} className="flex items-start gap-3">
                  <SiteIcon
                    name={f.icon}
                    className="text-site-accent mt-0.5 text-xl"
                  />
                  <p className="text-site-ink-muted text-sm leading-6">
                    {t(`security.${f.key}`)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
          <div className="min-w-0">
            <MockFrame>
              <pre className="bg-site-canvas text-site-ink-muted overflow-x-auto rounded-xl p-4 font-mono text-xs leading-6 break-words whitespace-pre-wrap">
                {t.raw("security.codeSample")}
              </pre>
            </MockFrame>
            <div className="border-site-border bg-site-canvas mt-4 flex items-start gap-2 rounded-2xl border p-4">
              <SiteIcon
                name="info"
                className="text-site-accent mt-0.5 text-base"
              />
              <p className="text-site-ink-muted text-sm leading-6">
                {t("security.usageNote")}
              </p>
            </div>
          </div>
        </div>
      </SiteSection>

      <div className="pt-20 lg:pt-28">
        <SiteCtaPanel
          id="hr-cta-title"
          title={t("cta.heading")}
          description={t("cta.description")}
          primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
          secondary={{ href: SOLUTIONS_HREF, label: t("cta.secondaryCta") }}
        />
      </div>
    </div>
  );
}
