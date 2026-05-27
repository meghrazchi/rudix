import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  accessAndGovernanceCards,
  complianceReadinessItems,
  documentLifecycleStages,
  retentionAndDeletionItems,
  sampleAuditEvents,
  securityPillars,
  type SecurityPillarIcon,
} from "@/components/public/pages/security/securityData";

function SecurityIcon({ icon }: { icon: SecurityPillarIcon }) {
  if (icon === "privacy") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <path
          d="M12 4.5 6.5 7v4.8c0 3.5 2 6.7 5.5 8.2 3.5-1.5 5.5-4.7 5.5-8.2V7L12 4.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path d="M9.2 11.5h5.6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "isolation") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <path d="M4 12h16M12 4v16" stroke="currentColor" strokeWidth="1.8" />
        <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    );
  }

  if (icon === "access") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <rect
          x="4.5"
          y="10"
          width="15"
          height="9"
          rx="2"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M8 10V7.8a4 4 0 0 1 8 0V10"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "audit") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <rect
          x="5"
          y="4.5"
          width="14"
          height="15"
          rx="2"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M8.5 9h7M8.5 12h7M8.5 15h4"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "upload") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <path
          d="M6 14.5v3a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-3"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="m12 5 3.2 3.3M12 5 8.8 8.3M12 5v9"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  if (icon === "encryption") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-6 w-6"
        fill="none"
      >
        <path
          d="M12 4.5 6.5 7v4.8c0 3.5 2 6.7 5.5 8.2 3.5-1.5 5.5-4.7 5.5-8.2V7L12 4.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
        />
        <path
          d="M10 11.6h4M12 10v3.2"
          stroke="currentColor"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6" fill="none">
      <path
        d="M5 12h5l2-6 2 12 2-6h3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function SecurityHeroSection({
  securityReviewHref,
  architectureHref,
}: {
  securityReviewHref: string;
  architectureHref: string;
}) {
  return (
    <section className="relative overflow-hidden border-b border-[#d8dce7] bg-[radial-gradient(circle_at_top,rgba(56,43,225,0.11),transparent_58%)] py-18 lg:py-24">
      <div className="mx-auto w-full max-w-7xl px-4 text-center lg:px-8">
        <span className="inline-flex rounded-full bg-[#e4e1ff] px-3 py-1 text-[11px] font-bold tracking-[0.12em] text-[#3b2fcb] uppercase">
          Security and trust
        </span>
        <h1 className="mx-auto mt-5 max-w-4xl text-4xl leading-tight font-black text-[#10131c] lg:text-6xl">
          Security-first document AI for trusted enterprise knowledge
        </h1>
        <p className="mx-auto mt-4 max-w-3xl text-sm leading-7 text-[#596077] lg:text-base">
          Rudix helps teams run document workflows with privacy, organization
          isolation, and traceable governance controls from ingestion to cited
          answers.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <PublicActionLink
            href={securityReviewHref}
            className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_14px_30px_rgba(53,37,205,0.26)] transition hover:bg-[#2a1fc1]"
          >
            Request Security Review
          </PublicActionLink>
          <PublicActionLink
            href={architectureHref}
            className="rounded-lg border border-[#cfd5e6] bg-white px-5 py-3 text-sm font-semibold text-[#21283d] transition hover:bg-[#f4f6fd]"
          >
            Review Architecture
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

export function SecurityPillarsSection() {
  return (
    <section
      aria-labelledby="security-pillars-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="max-w-3xl">
        <h2
          id="security-pillars-title"
          className="text-3xl font-black text-[#12151f] lg:text-5xl"
        >
          Core security pillars
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6277] lg:text-base">
          Security controls are embedded across document handling, access, and
          operational workflows.
        </p>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {securityPillars.map((pillar) => (
          <article
            key={pillar.title}
            className="flex h-full flex-col rounded-2xl border border-[#d8dce8] bg-white p-6 shadow-sm"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[#e6e2ff] text-[#3525cd]">
              <SecurityIcon icon={pillar.icon} />
            </div>
            <h3 className="mt-4 text-xl font-semibold text-[#1a1f2f]">
              {pillar.title}
            </h3>
            <p className="mt-2 flex-1 text-sm leading-7 text-[#5a6073]">
              {pillar.description}
            </p>
            <p className="mt-4 border-t border-[#e2e6f0] pt-3 text-[11px] font-bold tracking-[0.12em] text-[#3a31cd] uppercase">
              {pillar.callout}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function DocumentHandlingSection() {
  return (
    <section
      aria-labelledby="document-handling-title"
      className="border-y border-[#d9dce7] bg-[#f4f5f9]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-4xl">
          <h2
            id="document-handling-title"
            className="text-3xl font-black text-[#12151f] lg:text-5xl"
          >
            Document handling lifecycle
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5b6277] lg:text-base">
            Rudix processes documents through a controlled lifecycle:
            validation, object storage, parsing, chunking, embeddings, vector
            indexing, citation-backed answers, and deletion or re-index
            operations.
          </p>
        </div>

        <ol className="mt-8 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {documentLifecycleStages.map((stage, index) => (
            <li
              key={stage.title}
              className="rounded-xl border border-[#d5daea] bg-white p-4 shadow-sm"
            >
              <p className="text-[11px] font-bold tracking-[0.12em] text-[#555d77] uppercase">
                Step {index + 1}
              </p>
              <h3 className="mt-2 text-lg font-semibold text-[#1d2234]">
                {stage.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-[#596074]">
                {stage.description}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function AccessGovernanceSection() {
  return (
    <section
      aria-labelledby="access-governance-title"
      className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20"
    >
      <div className="max-w-3xl">
        <h2
          id="access-governance-title"
          className="text-3xl font-black text-[#12151f] lg:text-5xl"
        >
          Access, session safety, and governance
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6277] lg:text-base">
          Authentication, authorization, and route boundaries are designed to
          keep public content separate from private workspace operations.
        </p>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        {accessAndGovernanceCards.map((card) => (
          <article
            key={card.title}
            className="rounded-2xl border border-[#d8dce8] bg-white p-5 shadow-sm"
          >
            <h3 className="text-xl font-semibold text-[#1a1f30]">
              {card.title}
            </h3>
            <p className="mt-2 text-sm leading-7 text-[#5a6073]">
              {card.description}
            </p>
          </article>
        ))}
      </div>

      <div className="mt-8 overflow-x-auto rounded-2xl border border-[#d2d7e6] bg-white shadow-sm">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                Timestamp
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                Actor
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                Action
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                Resource
              </th>
              <th className="border-b border-[#d8dce8] bg-[#eceef5] px-4 py-3 text-xs font-bold tracking-[0.1em] text-[#4f556d] uppercase">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e3e7f0]">
            {sampleAuditEvents.map((event) => (
              <tr
                key={`${event.timestamp}-${event.action}`}
                className="bg-white"
              >
                <td className="px-4 py-3 font-mono text-xs text-[#636b84]">
                  {event.timestamp}
                </td>
                <td className="px-4 py-3 text-sm font-semibold text-[#232a3f]">
                  {event.actor}
                </td>
                <td className="px-4 py-3 text-xs font-bold text-[#3a35cd] uppercase">
                  {event.action}
                </td>
                <td className="px-4 py-3 text-sm text-[#4f566f]">
                  {event.resource}
                </td>
                <td
                  className={`px-4 py-3 text-sm font-semibold ${
                    event.status === "Rejected"
                      ? "text-[#b22b2e]"
                      : "text-[#168049]"
                  }`}
                >
                  {event.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ComplianceAndRetentionSection({
  securityContactHref,
}: {
  securityContactHref: string;
}) {
  return (
    <section
      aria-labelledby="compliance-readiness-title"
      className="bg-[#13151d] text-white"
    >
      <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-14 lg:grid-cols-2 lg:px-8 lg:py-20">
        <article className="rounded-2xl border border-white/12 bg-white/5 p-6">
          <h2
            id="compliance-readiness-title"
            className="text-2xl font-black lg:text-3xl"
          >
            Compliance readiness with careful claims
          </h2>
          <ul className="mt-4 space-y-3 text-sm leading-7 text-[#c4cbdd]">
            {complianceReadinessItems.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="mt-2 inline-block h-1.5 w-1.5 rounded-full bg-[#9e9eff]" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </article>

        <article className="rounded-2xl border border-white/12 bg-white/5 p-6">
          <h2 className="text-2xl font-black lg:text-3xl">
            Data retention and deletion posture
          </h2>
          <ul className="mt-4 space-y-3 text-sm leading-7 text-[#c4cbdd]">
            {retentionAndDeletionItems.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="mt-2 inline-block h-1.5 w-1.5 rounded-full bg-[#9e9eff]" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <PublicActionLink
            href={securityContactHref}
            className="mt-6 inline-flex rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2a1fc1]"
          >
            Contact Security Team
          </PublicActionLink>
        </article>
      </div>
    </section>
  );
}
