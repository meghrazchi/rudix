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
  { key: "repeatedQuestions", icon: "forum" },
  { key: "scatteredDocs", icon: "folder_off" },
  { key: "handoffs", icon: "transfer_within_a_station" },
] as const;

const SOURCES = [
  { key: "onboardingGuides", icon: "rocket_launch" },
  { key: "apiDocumentation", icon: "code" },
  { key: "implementationGuides", icon: "build" },
  { key: "knowledgeBase", icon: "support_agent" },
  { key: "productGuides", icon: "menu_book" },
  { key: "enablementMaterials", icon: "handshake" },
] as const;

const USE_CASES = [
  { key: "customerOnboarding", icon: "person_add" },
  { key: "implementationDocs", icon: "integration_instructions" },
  { key: "partnerEnablement", icon: "diversity_3" },
  { key: "supportKnowledge", icon: "support_agent" },
  { key: "accountHandoff", icon: "sync_alt" },
] as const;

const EXAMPLES = [1, 2] as const;

function WorkflowSteps() {
  const t = useTranslations("public.clientPortal");

  const steps = [
    {
      label: t("workflow.step01Label"),
      title: t("workflow.step01Title"),
      body: t("workflow.step01Body"),
      icon: "task_alt",
    },
    {
      label: t("workflow.step02Label"),
      title: t("workflow.step02Title"),
      body: t("workflow.step02Body"),
      icon: "account_tree",
    },
    {
      label: t("workflow.step03Label"),
      title: t("workflow.step03Title"),
      icon: "question_answer",
    },
    {
      label: t("workflow.step04Label"),
      title: t("workflow.step04Title"),
      icon: "fact_check",
    },
  ];

  return (
    <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((step) => (
        <li
          key={step.title}
          className="border-site-border bg-site-surface flex min-w-0 flex-col rounded-2xl border p-6"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="bg-site-accent-soft text-site-accent-ink rounded-full px-2.5 py-1 font-mono text-xs font-semibold">
              {step.label}
            </span>
            <SiteIcon name={step.icon} className="text-site-accent text-xl" />
          </div>
          <h3 className="text-site-ink mt-5 text-base font-semibold">
            {step.title}
          </h3>
          {step.body ? (
            <p className="text-site-ink-muted mt-2 text-sm leading-6">
              {step.body}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** Client portal solution page (minimal modern redesign, shared kit). */
export function ClientPortalSolutionPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.clientPortal");
  const links = resolvePublicSiteLinks();

  const related = [
    { label: t("related.support"), href: "/solutions/support" },
    { label: t("related.sales"), href: "/solutions/sales" },
    {
      label: t("related.internalKnowledge"),
      href: "/solutions/internal-knowledge",
    },
    { label: t("related.security"), href: "/security" },
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
        id="cp-hero-title"
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
          <MockFrame title={t("hero.mockPanelLabel")}>
            <div>
              <p className="text-site-ink-subtle mb-1.5 text-end text-xs font-medium">
                {t("hero.mockCustomerLabel")}
              </p>
              <MockQuestion>{t("hero.mockQuestion")}</MockQuestion>
            </div>
            <MockAnswer
              label={t("hero.mockAnswerLabel")}
              sources={[t("hero.mockTag1"), t("hero.mockTag2")]}
            >
              {t("hero.mockAnswer")}
            </MockAnswer>
          </MockFrame>
        }
      />

      <SiteSection
        labelledBy="cp-problem-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="cp-problem-title"
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

      <SiteSection labelledBy="cp-doc-title">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading
              id="cp-doc-title"
              title={t("documentSources.heading")}
              description={t("documentSources.description")}
            />
            <ul className="mt-8 space-y-3">
              {[0, 1, 2, 3].map((n) => (
                <li key={n} className="flex items-start gap-3">
                  <SiteIcon
                    name="check_circle"
                    className="text-site-success mt-0.5 text-xl"
                  />
                  <span className="text-site-ink-muted text-sm leading-6">
                    {t(`documentSources.feature${n}`)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-2">
            {SOURCES.map((s) => (
              <li
                key={s.key}
                className="border-site-border bg-site-surface flex min-w-0 flex-col items-start gap-3 rounded-2xl border p-5"
              >
                <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
                  <SiteIcon name={s.icon} className="text-xl" />
                </span>
                <span className="text-site-ink text-sm font-medium break-words">
                  {t(`documentSources.${s.key}`)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="cp-workflow-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="cp-workflow-title"
          title={t("workflow.heading")}
          description={t("workflow.description")}
        />
        <WorkflowSteps />
      </SiteSection>

      <SiteSection labelledBy="cp-usecases-title">
        <SectionHeading
          id="cp-usecases-title"
          title={t("useCases.heading")}
          description={t("useCases.description")}
        />
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {USE_CASES.map((u) => (
            <IconCard
              key={u.key}
              icon={u.icon}
              title={t(`useCases.${u.key}Title`)}
              body={t(`useCases.${u.key}Body`)}
            />
          ))}
        </ul>
      </SiteSection>

      <SiteSection
        labelledBy="cp-queries-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="cp-queries-title"
          title={t("exampleQueries.heading")}
        />
        <ul className="mt-10 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {EXAMPLES.map((n) => (
            <li
              key={n}
              className="border-site-border bg-site-canvas min-w-0 space-y-4 rounded-2xl border p-4 md:p-5"
            >
              <MockQuestion>{t(`exampleQueries.q${n}`)}</MockQuestion>
              <MockAnswer
                label={t("exampleQueries.answerLabel")}
                sources={[
                  t(`exampleQueries.source${n}a`),
                  t(`exampleQueries.source${n}b`),
                ]}
              >
                {t(`exampleQueries.a${n}`)}
              </MockAnswer>
            </li>
          ))}
        </ul>
      </SiteSection>

      <SiteSection labelledBy="cp-related-title">
        <SectionHeading
          id="cp-related-title"
          title={t("related.heading")}
          align="center"
        />
        <ul className="mt-8 flex flex-wrap justify-center gap-3">
          {related.map((r) => (
            <li key={r.href}>
              <PublicActionLink
                href={r.href}
                className="border-site-border bg-site-surface text-site-ink hover:bg-site-muted inline-flex h-11 items-center gap-2 rounded-full border px-5 text-sm font-medium transition-colors"
              >
                {r.label}
                <SiteIcon
                  name="arrow_forward"
                  className="rtl-mirror text-site-ink-subtle text-base"
                />
              </PublicActionLink>
            </li>
          ))}
        </ul>
        <div className="border-site-border bg-site-surface mx-auto mt-12 flex max-w-3xl items-start gap-2 rounded-2xl border p-5">
          <SiteIcon name="info" className="text-site-accent mt-0.5 text-base" />
          <p className="text-site-ink-muted text-sm leading-6">
            {t("cta.disclaimer")}
          </p>
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="cp-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
      />
    </div>
  );
}
