"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  FinalCtaBand,
  WorkflowStripSection,
} from "@/components/public/sections/PublicSections";
import {
  CrossSolutionValueSection,
  QuestionMatrixSection,
  SolutionCardsSection,
  SolutionsHero,
} from "@/components/public/pages/solutions/SolutionsOverviewSections";
import { WorkflowPlaybookSection } from "@/components/public/pages/solutions/WorkflowPlaybookSection";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

function SolutionsBreadcrumb() {
  const t = useTranslations("public");

  return (
    <div className="border-b border-[#e2e5ef] bg-[#f2f3f6]">
      <nav
        aria-label="Breadcrumb"
        className="mx-auto w-full max-w-7xl px-4 py-3 lg:px-8"
      >
        <ol className="flex items-center gap-2 text-xs text-[#61677a]">
          <li>
            <PublicActionLink href="/" className="hover:text-[#2a2f40]">
              {t("home")}
            </PublicActionLink>
          </li>
          <li aria-hidden="true" className="text-[#9ca3b8]">
            /
          </li>
          <li aria-current="page" className="font-semibold text-[#252a3b]">
            {t("breadcrumb.solutions")}
          </li>
        </ol>
      </nav>
    </div>
  );
}

export function SolutionsOverviewPage() {
  const t = useTranslations("public.solutions");
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SolutionsBreadcrumb />
      <SolutionsHero />
      <SolutionCardsSection />
      <CrossSolutionValueSection />
      <WorkflowPlaybookSection />

      <WorkflowStripSection
        title={t("workflowStrip.title")}
        description={t("workflowStrip.description")}
        steps={[
          {
            title: t("workflowStrip.collectTitle"),
            description: t("workflowStrip.collectDesc"),
          },
          {
            title: t("workflowStrip.prepareTitle"),
            description: t("workflowStrip.prepareDesc"),
          },
          {
            title: t("workflowStrip.answerTitle"),
            description: t("workflowStrip.answerDesc"),
          },
          {
            title: t("workflowStrip.improveTitle"),
            description: t("workflowStrip.improveDesc"),
          },
        ]}
      />

      <QuestionMatrixSection />

      <FinalCtaBand
        title={t("cta.heading")}
        description={t("cta.description")}
        primaryLabel={t("cta.primaryCta")}
        primaryHref={links.requestDemo}
        secondaryLabel={t("cta.secondaryCta")}
        secondaryHref={links.product}
      />
    </>
  );
}
