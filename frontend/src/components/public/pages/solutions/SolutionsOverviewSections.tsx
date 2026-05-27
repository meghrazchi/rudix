import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  AudienceIcon,
  enterpriseUseCaseCards,
} from "@/components/public/pages/solutions/enterpriseUseCases";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

type CrossSolutionValue = {
  title: string;
  description: string;
};

const crossSolutionValues: CrossSolutionValue[] = [
  {
    title: "Secure upload and ingestion",
    description:
      "Bring departmental files into policy-aware workflows with traceable processing states.",
  },
  {
    title: "Citation-backed responses",
    description:
      "Ground answers in source references so teams can verify evidence and context quickly.",
  },
  {
    title: "Evaluation-driven quality",
    description:
      "Use repeatable evaluation runs to monitor retrieval and answer performance over time.",
  },
  {
    title: "Governance and auditability",
    description:
      "Apply role-scoped controls with operational visibility across document and answer workflows.",
  },
];

export function SolutionsHero() {
  const links = resolvePublicSiteLinks();

  return (
    <section className="relative overflow-hidden py-16 lg:py-24">
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="max-w-3xl">
          <span className="inline-flex rounded-full bg-[#e7e4ff] px-3 py-1 text-[11px] font-bold tracking-[0.11em] text-[#3f32d2] uppercase">
            Solutions ecosystem
          </span>
          <h1 className="mt-5 text-4xl leading-tight font-black text-[#0f1118] lg:text-6xl">
            AI document Q&A for every team.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#5a6072] lg:text-base">
            Rudix helps each department move from fragmented documents to
            searchable, citation-backed answers with workflow visibility,
            quality controls, and governance-ready operations.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <PublicActionLink
              href={links.product}
              className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(53,37,205,0.25)] transition hover:bg-[#291ec0]"
            >
              Explore Platform
            </PublicActionLink>
            <PublicActionLink
              href={links.docs}
              className="rounded-lg border border-[#cfd4e2] bg-white px-5 py-3 text-sm font-semibold text-[#23283a] transition hover:bg-[#f4f6fc]"
            >
              View API Docs
            </PublicActionLink>
          </div>
        </div>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 hidden w-[42%] bg-[radial-gradient(circle_at_70%_40%,rgba(53,37,205,0.18),transparent_65%)] lg:block"
      />
    </section>
  );
}

export function SolutionCardsSection() {
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
          Enterprise Use Cases
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
          Department-specific solution paths built on one shared Rudix
          foundation.
        </p>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
        {enterpriseUseCaseCards.map((card) => (
          <article
            key={card.id}
            className="rounded-xl border border-l-4 border-[#d8dce7] border-l-[#3525cd] bg-white/80 p-6 shadow-sm backdrop-blur-sm transition hover:-translate-y-0.5 hover:shadow-md"
          >
            {card.href ? (
              <PublicActionLink
                href={card.href}
                className="block rounded-sm focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                ariaLabel={`${card.title} solution`}
              >
                <div className="mb-4 inline-flex text-[#3525cd]">
                  <AudienceIcon icon={card.icon} />
                </div>
                <h3 className="text-lg font-semibold text-[#2c2f3a]">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-8 text-[#5a6071]">
                  {card.description}
                </p>
              </PublicActionLink>
            ) : (
              <>
                <div className="mb-4 inline-flex text-[#3525cd]">
                  <AudienceIcon icon={card.icon} />
                </div>
                <h3 className="text-lg font-semibold text-[#2c2f3a]">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-8 text-[#5a6071]">
                  {card.description}
                </p>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export function CrossSolutionValueSection() {
  return (
    <section
      id="cross-solution-value"
      aria-labelledby="cross-solution-value-title"
      className="bg-[#f3f4f8]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <h2
            id="cross-solution-value-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            Shared value across all solutions
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
            Every department benefits from the same secure, grounded, and
            auditable Rudix platform.
          </p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {crossSolutionValues.map((value) => (
            <article
              key={value.title}
              className="rounded-2xl border border-[#d7dce9] bg-white p-5 shadow-sm"
            >
              <h3 className="text-lg font-semibold text-[#1e2233]">
                {value.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-[#5a6073]">
                {value.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function QuestionMatrixSection() {
  return (
    <section aria-labelledby="question-matrix-title" className="bg-[#eaecf3]">
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="mb-8 max-w-3xl">
          <h2
            id="question-matrix-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            Example Question Matrix
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
            See how Rudix handles multi-hop and high-density queries.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse overflow-hidden rounded-xl bg-white shadow-sm">
            <thead>
              <tr>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  Complexity
                </th>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  Sample Query
                </th>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  Retrieval Strategy
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e1e5ef]">
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#95f7b2] px-2 py-1 text-xs font-bold text-[#043520]">
                    SINGLE-HOP
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  &quot;What is our policy on remote work in Germany?&quot;
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  Hybrid semantic + keyword
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#e5e1e9] px-2 py-1 text-xs font-bold text-[#2b2c35]">
                    MULTI-HOP
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  &quot;Compare our Q3 revenue growth with the projection in the
                  2022 annual report.&quot;
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  Cross-document chaining
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#e2dfff] px-2 py-1 text-xs font-bold text-[#25147c]">
                    STRUCTURAL
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  &quot;List all vendors with contracts expiring before Dec 31
                  in a table.&quot;
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  JSON/Table extraction agent
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#ffdad6] px-2 py-1 text-xs font-bold text-[#8d1013]">
                    REASONING
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  &quot;Does the new GDPR amendment conflict with our current
                  data storage flow?&quot;
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  Contextual LLM verification
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
