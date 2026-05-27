import Image from "next/image";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const problemCards = [
  {
    icon: "search_off",
    title: "Manual searching",
    description:
      "Hours wasted digging through scattered PDFs, Sharepoint, and old wikis for a single truth.",
    accentClass: "bg-[#ffdad6] text-[#ba1a1a]",
  },
  {
    icon: "replay",
    title: "Repeated questions",
    description:
      'Subject matter experts answering the same "How do I..." questions over and over.',
    accentClass: "bg-[#e2dfff] text-[#3323cc]",
  },
  {
    icon: "warning",
    title: "Untrusted AI",
    description:
      "Generic LLMs hallucinating answers without citations or context-specific guardrails.",
    accentClass: "bg-[#91f8ae] text-[#00542a]",
  },
  {
    icon: "lan",
    title: "Knowledge silos",
    description:
      "Critical data trapped in departmental silos, unreachable for cross-functional teams.",
    accentClass: "bg-[#e2dee6] text-[#5f5d64]",
  },
];

const workflowSteps = [
  {
    title: "Ingestion & Indexing",
    description:
      "Rudix automatically parses PDFs, Word, and JSON, converting them into searchable high-dimensional vector embeddings.",
  },
  {
    title: "Semantic Retrieval",
    description:
      "When a user asks a question, our RAG engine retrieves the exact chunks needed to answer it, no more and no less.",
  },
  {
    title: "Grounded Generation",
    description:
      "The AI answers only based on retrieved data, providing direct links to sources for absolute transparency.",
  },
];

const useCaseCards = [
  {
    label: "Legal & Compliance",
    title: '"Does Section 4.2 allow for sub-licensing?"',
    description:
      "Review thousands of contracts in seconds with exact clause citations.",
  },
  {
    label: "Customer Support",
    title: '"What is the policy for international returns?"',
    description:
      "Empower agents with instant, accurate answers from latest handbooks.",
  },
  {
    label: "Product & Engineering",
    title: '"What are the API rate limits for Tier 2?"',
    description:
      "Surface technical specs and architectural limits directly to developers.",
  },
  {
    label: "Human Resources",
    title: '"How many days of bereavement leave is allowed?"',
    description: "Automate employee queries with policy-aligned responses.",
  },
  {
    label: "Sales Ops",
    title: '"Do we support SSO for Enterprise clients?"',
    description: "Get immediate answers for RFPs and security questionnaires.",
  },
];

const securityCards = [
  {
    icon: "shield",
    title: "Data Isolation",
    description:
      "Separate vector databases for every workspace. Your documents never mix with others.",
  },
  {
    icon: "history_edu",
    title: "Audit Logs",
    description:
      "Track every query, retrieval, and administrative action with detailed time-stamped logs.",
  },
  {
    icon: "lock",
    title: "End-to-End Encryption",
    description:
      "AES-256 at rest and TLS 1.3 in transit, with Bring Your Own Key support for enterprise.",
  },
];

export function LandingPage() {
  const links = resolvePublicSiteLinks();
  return (
    <div className="bg-[#faf9ff] text-[#1a1b20]">
      <section className="relative overflow-hidden px-4 py-16 lg:px-8 lg:py-24">
        <div className="mx-auto grid w-full max-w-7xl gap-12 lg:grid-cols-12 lg:items-center">
          <div className="space-y-8 lg:col-span-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#c3c0ff] bg-[#e2dfff]/50 px-4 py-1.5 text-[#3323cc]">
              <span
                className="material-symbols-outlined text-sm"
                aria-hidden="true"
              >
                verified
              </span>
              <span className="text-xs font-semibold tracking-[0.05em] uppercase">
                Enterprise Ready RAG Infrastructure
              </span>
            </div>
            <h1 className="text-4xl leading-tight font-black tracking-[-0.02em] text-[#1a1b20] md:text-5xl lg:text-6xl">
              Ask your documents.
              <br />
              <span className="text-[#3525cd]">Get the answers you need.</span>
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-[#464555]">
              Turn PDFs, DOCX, and complex technical manuals into precise AI
              assistants with full citations and infrastructure-level
              visibility.
            </p>
            <div className="flex flex-wrap gap-4">
              <PublicActionLink
                href={links.requestDemo}
                className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-8 py-4 text-base font-semibold text-white transition hover:bg-[#2d20ac]"
              >
                Speak to us
                <span
                  className="material-symbols-outlined text-base"
                  aria-hidden="true"
                >
                  arrow_forward
                </span>
              </PublicActionLink>
              <PublicActionLink
                href={links.startTrial}
                className="rounded-xl border border-[#777587] px-8 py-4 text-base font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3]"
              >
                Try the demo
              </PublicActionLink>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 pt-3">
              {["SOC 2 Compliant", "GDPR Ready", "Private Cloud"].map(
                (label) => (
                  <p
                    key={label}
                    className="inline-flex items-center gap-2 text-xs font-semibold tracking-[0.05em] text-[#464555] uppercase"
                  >
                    <span
                      className="material-symbols-outlined text-base text-[#108548]"
                      aria-hidden="true"
                    >
                      check_circle
                    </span>
                    {label}
                  </p>
                ),
              )}
            </div>
          </div>
          <div className="relative lg:col-span-6">
            <div className="rudix-landing-glass rounded-3xl p-2 shadow-2xl">
              <Image
                src="/images/chat-sample-2.png"
                alt="Rudix product interface showing document retrieval and grounded answers"
                width={1200}
                height={780}
                className="h-auto w-full rounded-2xl"
                priority
              />
            </div>
            <div className="absolute -top-10 -right-8 -z-10 h-56 w-56 rounded-full bg-[#c3c0ff] blur-[88px]" />
            <div className="absolute -bottom-10 -left-8 -z-10 h-48 w-48 rounded-full bg-[#91f8ae] blur-[80px]" />
          </div>
        </div>
      </section>

      <section className="bg-white px-4 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto w-full max-w-7xl">
          <div className="mx-auto max-w-3xl space-y-4 text-center">
            <h2 className="text-3xl leading-tight font-bold text-[#1a1b20] lg:text-4xl">
              Your team has the answers. They are just buried.
            </h2>
            <p className="text-lg text-[#464555]">
              Siloed knowledge and messy documentation are the hidden taxes on
              your productivity.
            </p>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            {problemCards.map((card) => (
              <article
                key={card.title}
                className="rounded-2xl border border-[#c7c4d8] bg-[#faf9ff] p-7 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg"
              >
                <div
                  className={`mb-5 inline-flex h-12 w-12 items-center justify-center rounded-xl ${card.accentClass}`}
                >
                  <span
                    className="material-symbols-outlined"
                    aria-hidden="true"
                  >
                    {card.icon}
                  </span>
                </div>
                <h3 className="text-xl font-semibold text-[#1a1b20]">
                  {card.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-[#464555]">
                  {card.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden px-4 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-12 lg:flex-row lg:items-center lg:gap-16">
          <div className="space-y-8 lg:w-1/2">
            <h2 className="text-3xl font-black text-[#1a1b20] md:text-4xl lg:text-5xl">
              Upload. Ask. Verify.
            </h2>
            <div className="space-y-7">
              {workflowSteps.map((step, index) => (
                <div key={step.title} className="flex gap-5">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#3525cd] text-sm font-bold text-white">
                    {index + 1}
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-[#1a1b20]">
                      {step.title}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-[#464555]">
                      {step.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="w-full lg:w-1/2">
            <div className="rounded-3xl bg-[#0a0a0f] p-8 shadow-2xl">
              <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-xl font-semibold text-white">
                  Pipeline Explorer
                </h3>
                <p className="rounded bg-[#10854833] px-3 py-1 text-[11px] font-semibold tracking-[0.06em] text-[#8af1a8] uppercase">
                  Live status: running
                </p>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between rounded-xl border border-[#ffffff1f] bg-[#ffffff14] px-4 py-3 text-white">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#c3c0ff]"
                      aria-hidden="true"
                    >
                      upload_file
                    </span>
                    <span className="font-mono text-sm">Document.PDF</span>
                  </div>
                  <span className="text-[11px] text-[#f1f0f699] uppercase">
                    Input
                  </span>
                </div>
                <div className="rudix-landing-flow-line rudix-landing-flow-line--active mx-auto h-7 w-px bg-[#777587]" />
                <div className="flex items-center justify-between rounded-xl border border-[#4f46e57f] bg-[#3525cd33] px-4 py-3 text-white shadow-[0_0_20px_rgba(79,70,229,0.2)]">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#c3c0ff]"
                      aria-hidden="true"
                    >
                      psychology
                    </span>
                    <span className="font-mono text-sm">
                      RAG_Retrieval_Logic
                    </span>
                  </div>
                  <span className="text-[11px] text-[#c3c0ff] uppercase">
                    Active
                  </span>
                </div>
                <div className="mx-auto h-7 w-px bg-[#777587]" />
                <div className="flex items-center justify-between rounded-xl border border-[#ffffff1f] bg-[#ffffff14] px-4 py-3 text-white">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#91f8ae]"
                      aria-hidden="true"
                    >
                      output
                    </span>
                    <span className="font-mono text-sm">Grounded_Response</span>
                  </div>
                  <span className="text-[11px] text-[#f1f0f699] uppercase">
                    Output
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section
        id="solutions"
        className="bg-[#f4f3f9] px-4 py-20 lg:px-8 lg:py-24"
      >
        <div className="mx-auto w-full max-w-7xl">
          <div className="space-y-4">
            <h2 className="text-3xl font-bold text-[#1a1b20] lg:text-4xl">
              Built for every team.
            </h2>
            <p className="text-lg text-[#464555]">
              Specific solutions for complex enterprise knowledge.
            </p>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-5">
            {useCaseCards.map((item) => (
              <article
                key={item.title}
                className="rounded-2xl border border-[#c7c4d8] bg-white p-6 transition hover:border-[#3525cd]"
              >
                <p className="text-xs font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  {item.label}
                </p>
                <h3 className="mt-4 text-sm leading-6 font-semibold text-[#1a1b20]">
                  {item.title}
                </h3>
                <p className="mt-3 text-sm leading-6 text-[#464555]">
                  {item.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section
        id="security"
        className="relative overflow-hidden bg-[#0a0a0f] px-4 py-20 text-white lg:px-8 lg:py-24"
      >
        <div className="mx-auto grid w-full max-w-7xl gap-12 lg:grid-cols-2 lg:items-center lg:gap-20">
          <div>
            <h2 className="text-3xl leading-tight font-black lg:text-5xl">
              Designed for private document workflows.
            </h2>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-[#c3c0ff]">
              We do not just secure your data. We architect it for total
              isolation and auditability.
            </p>
            <div className="mt-10 space-y-7">
              {securityCards.map((item) => (
                <article key={item.title} className="flex items-start gap-4">
                  <div className="rounded-lg bg-[#ffffff17] p-3 text-[#c3c0ff]">
                    <span
                      className="material-symbols-outlined"
                      aria-hidden="true"
                    >
                      {item.icon}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-white">
                      {item.title}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-[#f1f0f6b3]">
                      {item.description}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </div>
          <div className="rounded-3xl border border-[#ffffff1f] bg-[#ffffff0d] p-8">
            <Image
              src="/images/pipeline-rag-sample.png"
              alt="Secure enterprise workflow visualization"
              width={1200}
              height={780}
              className="h-auto w-full rounded-2xl opacity-90"
            />
          </div>
        </div>
      </section>

      <section
        id="pricing"
        className="border-t border-[#c7c4d8] bg-[#faf9ff] px-4 py-20 lg:px-8 lg:py-24"
      >
        <div className="mx-auto w-full max-w-4xl text-center">
          <h2 className="text-3xl leading-tight font-black text-[#1a1b20] lg:text-5xl">
            Ready to turn your documents into an AI assistant?
          </h2>
          <p className="mx-auto mt-5 max-w-3xl text-lg leading-8 text-[#464555]">
            Join forward-thinking engineering teams using Rudix for knowledge
            excellence.
          </p>
          <div className="mt-10 flex flex-col justify-center gap-4 sm:flex-row">
            <PublicActionLink
              href={links.requestDemo}
              className="rounded-xl bg-[#3525cd] px-10 py-4 text-lg font-semibold text-white transition hover:bg-[#2d20ac]"
            >
              Speak to us
            </PublicActionLink>
            <PublicActionLink
              href={links.docs}
              className="rounded-xl border border-[#777587] px-10 py-4 text-lg font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3]"
            >
              View documentation
            </PublicActionLink>
          </div>
        </div>
      </section>
    </div>
  );
}
