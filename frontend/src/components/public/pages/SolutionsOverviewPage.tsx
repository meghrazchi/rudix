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
import { SOLUTION_OVERVIEW_FLOW_STEPS } from "@/lib/public-site/solutions";

function SolutionsBreadcrumb() {
  return (
    <nav
      aria-label="Breadcrumb"
      className="mx-auto w-full max-w-7xl px-4 pt-8 lg:px-8"
    >
      <ol className="flex items-center gap-2 text-xs text-[#61677a]">
        <li>
          <PublicActionLink href="/" className="hover:text-[#2a2f40]">
            Home
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#9ca3b8]">
          /
        </li>
        <li aria-current="page" className="font-semibold text-[#252a3b]">
          Solutions
        </li>
      </ol>
    </nav>
  );
}

export function SolutionsOverviewPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SolutionsBreadcrumb />
      <SolutionsHero />
      <SolutionCardsSection />
      <CrossSolutionValueSection />
      <WorkflowPlaybookSection />

      <WorkflowStripSection
        title="From scattered documents to trusted answers"
        description="Use a consistent delivery model that supports onboarding, quality assurance, and long-term reliability for department-specific use cases."
        steps={SOLUTION_OVERVIEW_FLOW_STEPS}
      />

      <QuestionMatrixSection />

      <FinalCtaBand
        title="Map your team’s workflow"
        description="See the right Rudix solution path for your department and align on a rollout plan."
        primaryLabel="Request Demo"
        primaryHref={links.requestDemo}
        secondaryLabel="View Product"
        secondaryHref={links.product}
      />
    </>
  );
}
