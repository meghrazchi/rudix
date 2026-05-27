import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  FaqSection,
  FinalCtaBand,
  HeroSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import type { SolutionAudience } from "@/lib/public-site/solutions";
import { SOLUTION_ROLE_NAV } from "@/lib/public-site/solutions";

type SolutionDetailPageProps = {
  solution: SolutionAudience;
};

function SolutionBreadcrumb({ solution }: { solution: SolutionAudience }) {
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
        <li>
          <PublicActionLink href="/solutions" className="hover:text-[#2a2f40]">
            Solutions
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#9ca3b8]">
          /
        </li>
        <li aria-current="page" className="font-semibold text-[#252a3b]">
          {solution.shortLabel}
        </li>
      </ol>
    </nav>
  );
}

function SolutionRoleNavigation({ activeSlug }: { activeSlug: string }) {
  return (
    <section
      aria-labelledby="solution-role-nav-title"
      className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-8"
    >
      <h2
        id="solution-role-nav-title"
        className="text-xs font-bold tracking-[0.16em] text-[#636a7f] uppercase"
      >
        Explore by team
      </h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {SOLUTION_ROLE_NAV.map((item) => (
          <li key={item.href}>
            <PublicActionLink
              href={item.href}
              className={`inline-flex rounded-full border px-4 py-2 text-xs font-semibold ${
                item.href.endsWith(`/${activeSlug}`)
                  ? "border-[#3a35e8] bg-[#ecebff] text-[#2f33c5]"
                  : "border-[#d0d5e4] bg-white text-[#343a50] hover:bg-[#f4f6fb]"
              }`}
            >
              {item.label}
            </PublicActionLink>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SolutionDetailBody({ solution }: { solution: SolutionAudience }) {
  return (
    <section
      aria-labelledby="solution-detail-title"
      className="mx-auto w-full max-w-7xl px-4 py-10 lg:px-8 lg:py-14"
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <article className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm">
          <h2 className="text-xl font-semibold text-[#171a24]">Pain point</h2>
          <p className="mt-3 text-sm leading-7 text-[#5a6071]">
            {solution.painPoint}
          </p>
        </article>
        <article className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm">
          <h2 className="text-xl font-semibold text-[#171a24]">
            Rudix workflow
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5a6071]">
            {solution.rudixWorkflow}
          </p>
        </article>
        <article className="rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm">
          <h2 className="text-xl font-semibold text-[#171a24]">Team outcome</h2>
          <p className="mt-3 text-sm leading-7 text-[#5a6071]">
            {solution.summary}
          </p>
        </article>
      </div>

      <div className="mt-6 rounded-2xl border border-[#d8dce7] bg-white p-5 shadow-sm">
        <h2
          id="solution-detail-title"
          className="text-xl font-semibold text-[#171a24]"
        >
          Example questions for {solution.shortLabel} teams
        </h2>
        <ul className="mt-3 space-y-2">
          {solution.exampleQuestions.map((question) => (
            <li
              key={question}
              className="rounded-md bg-[#f5f7fc] px-3 py-2 text-sm leading-6 text-[#4a5269]"
            >
              {question}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function SolutionDetailPage({ solution }: SolutionDetailPageProps) {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SolutionBreadcrumb solution={solution} />

      <HeroSection
        badge={`${solution.shortLabel} Solution`}
        title={solution.name}
        description={solution.summary}
        actions={[
          {
            label: "Request Demo",
            href: links.requestDemo,
            variant: "primary",
          },
          {
            label: "Back to Solutions",
            href: "/solutions",
            variant: "secondary",
          },
        ]}
      />

      <SolutionRoleNavigation activeSlug={solution.slug} />
      <SolutionDetailBody solution={solution} />

      <FaqSection
        title={`${solution.shortLabel} solution FAQ`}
        items={[
          {
            question: "Can we start with one team and expand later?",
            answer:
              "Yes. Most teams start with one department workflow, then expand to additional teams as usage and governance needs evolve.",
          },
          {
            question: "Are answers grounded in internal sources?",
            answer:
              "Rudix is designed to provide source-backed answers so teams can validate context before acting on recommendations.",
          },
        ]}
      />

      <FinalCtaBand
        title="Plan your rollout"
        description={`Explore how the ${solution.shortLabel} solution can fit your team, then align stakeholders on adoption milestones.`}
        primaryLabel="Request Demo"
        primaryHref={links.requestDemo}
        secondaryLabel="View Product"
        secondaryHref={links.product}
      />
    </>
  );
}
