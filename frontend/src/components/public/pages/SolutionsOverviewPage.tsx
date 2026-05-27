import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  type PublicFeatureItem,
  FeatureGridSection,
  FinalCtaBand,
  HeroSection,
  WorkflowStripSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import {
  SOLUTION_AUDIENCES,
  SOLUTION_OVERVIEW_FLOW_STEPS,
  SOLUTION_ROLE_NAV,
} from "@/lib/public-site/solutions";

const crossSolutionValues: PublicFeatureItem[] = [
  {
    icon: "ingestion",
    title: "Secure Upload and Ingestion",
    description:
      "Bring department documents into controlled workflows with traceable processing states.",
  },
  {
    icon: "pipeline",
    title: "Citations and Explainability",
    description:
      "Ground answers in source references so teams can verify context and reduce ambiguity.",
  },
  {
    icon: "evaluation",
    title: "Evaluation-driven Quality",
    description:
      "Use repeatable evaluation runs to track retrieval and answer quality as usage grows.",
  },
  {
    icon: "governance",
    title: "Governance and Access Controls",
    description:
      "Support role-scoped usage patterns with clear boundaries across teams and workflows.",
  },
  {
    icon: "security",
    title: "Auditability for Operators",
    description:
      "Keep visibility into operational events and decision paths for review and accountability.",
  },
];

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

function SolutionsRoleNavigation() {
  return (
    <section
      aria-labelledby="solutions-role-nav-title"
      className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-8"
    >
      <h2
        id="solutions-role-nav-title"
        className="text-xs font-bold tracking-[0.16em] text-[#636a7f] uppercase"
      >
        Browse by team
      </h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {SOLUTION_ROLE_NAV.map((item) => (
          <li key={item.href}>
            <PublicActionLink
              href={item.href}
              className="inline-flex rounded-full border border-[#d0d5e4] bg-white px-4 py-2 text-xs font-semibold text-[#343a50] hover:bg-[#f4f6fb]"
            >
              {item.label}
            </PublicActionLink>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SolutionCardsSection() {
  return (
    <section
      aria-labelledby="solutions-cards-title"
      className="mx-auto w-full max-w-7xl px-4 py-10 lg:px-8 lg:py-14"
    >
      <div className="max-w-3xl">
        <h2
          id="solutions-cards-title"
          className="text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          Solutions by Department
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
          Choose a solution path based on your team’s document workflow and move
          to detailed guidance for implementation planning.
        </p>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {SOLUTION_AUDIENCES.map((solution) => (
          <article
            key={solution.slug}
            className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm"
          >
            <p className="text-[11px] font-bold tracking-[0.12em] text-[#5f6780] uppercase">
              {solution.teamLabel}
            </p>
            <h3 className="mt-2 text-2xl font-semibold text-[#171a24]">
              {solution.name}
            </h3>
            <p className="mt-3 text-sm leading-7 text-[#5a6071]">
              <span className="font-semibold text-[#2f3447]">Pain point:</span>{" "}
              {solution.painPoint}
            </p>
            <p className="mt-3 text-sm leading-7 text-[#5a6071]">
              <span className="font-semibold text-[#2f3447]">
                Rudix workflow:
              </span>{" "}
              {solution.rudixWorkflow}
            </p>
            <div className="mt-4">
              <p className="text-xs font-bold tracking-[0.08em] text-[#57607b] uppercase">
                Example questions
              </p>
              <ul className="mt-2 space-y-2">
                {solution.exampleQuestions.map((question) => (
                  <li
                    key={question}
                    className="rounded-md bg-[#f5f7fc] px-3 py-2 text-xs leading-5 text-[#4a5269]"
                  >
                    {question}
                  </li>
                ))}
              </ul>
            </div>
            <PublicActionLink
              href={solution.routePath}
              className="mt-5 inline-flex text-sm font-semibold text-[#3036db] hover:text-[#2229b5]"
            >
              Explore {solution.shortLabel} solution
            </PublicActionLink>
          </article>
        ))}
      </div>
    </section>
  );
}

export function SolutionsOverviewPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SolutionsBreadcrumb />

      <HeroSection
        badge="Solutions Overview"
        title="Trusted AI answers for every document-driven team"
        description="Rudix helps departments move from scattered files to searchable, evaluated, and citation-backed answers tailored to real workflows."
        actions={[
          {
            label: "Request Demo",
            href: links.requestDemo,
            variant: "primary",
          },
          {
            label: "View Product",
            href: links.product,
            variant: "secondary",
          },
        ]}
      />

      <SolutionsRoleNavigation />
      <SolutionCardsSection />

      <FeatureGridSection
        sectionId="cross-solution-value"
        title="Shared value across all solutions"
        description="Every department benefits from the same secure, grounded, and operationally visible Rudix platform capabilities."
        items={crossSolutionValues}
      />

      <WorkflowStripSection
        title="From scattered documents to trusted answers"
        description="Use a consistent delivery model that supports onboarding, quality assurance, and long-term reliability for department-specific use cases."
        steps={SOLUTION_OVERVIEW_FLOW_STEPS}
      />

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
