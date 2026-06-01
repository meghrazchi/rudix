"use client";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

function Sym({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined ${className}`}
    >
      {name}
    </span>
  );
}

// ── breadcrumb ────────────────────────────────────────────────────────────────

function LegalBreadcrumb() {
  return (
    <nav
      aria-label="Breadcrumb"
      className="mx-auto w-full max-w-[1440px] px-10 pt-6"
    >
      <ol className="flex items-center gap-2 text-xs text-[#777587]">
        <li>
          <PublicActionLink href="/" className="hover:text-[#3525cd]">
            Home
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#c7c4d8]">
          /
        </li>
        <li>
          <PublicActionLink href="/solutions" className="hover:text-[#3525cd]">
            Solutions
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#c7c4d8]">
          /
        </li>
        <li aria-current="page" className="font-semibold text-[#1a1b20]">
          Legal
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function LegalHeroSection({ demoHref }: { demoHref: string }) {
  return (
    <section
      aria-labelledby="legal-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="absolute -top-32 -right-32 -z-10 h-64 w-64 rounded-full bg-[#3525cd]/5 blur-3xl" />
      <div className="mx-auto grid max-w-[1440px] items-center gap-12 px-10 lg:grid-cols-2">
        <div className="relative z-10">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-[#3525cd]/10 px-3 py-1 text-[#3525cd]">
            <Sym name="gavel" className="text-[18px]" />
            <span className="text-[12px] font-semibold tracking-[0.05em] uppercase">
              Legal Intelligence
            </span>
          </div>
          <h1
            id="legal-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#1a1b20] lg:text-[48px] lg:leading-[56px]"
          >
            Ask contracts and policies with source-backed answers.
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            Search contracts, legal policies, vendor agreements, renewal terms,
            obligations, and deadlines with citations. Built for
            enterprise-grade compliance.
          </p>
          <PublicActionLink
            href={demoHref}
            className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-8 py-4 text-lg font-bold text-white shadow-lg shadow-[#3525cd]/20 transition hover:opacity-90 active:scale-95"
          >
            Speak to us about legal workflows
            <Sym name="arrow_forward" />
          </PublicActionLink>
        </div>

        <div className="relative lg:block">
          <div className="rudix-landing-glass relative rounded-2xl border border-[#c7c4d8]/50 p-6 shadow-[0_0_20px_rgba(53,37,205,0.1)]">
            <div className="mb-4 flex items-center gap-4 rounded-lg border border-white/10 bg-[#0A0A0F] p-4">
              <Sym name="search" className="text-[#c3c0ff]" />
              <span className="text-sm text-[#c3c0ff]/60 italic">
                &quot;When is the termination notice for the AWS contract?&quot;
              </span>
            </div>
            <div className="rounded-lg bg-[#eeedf3] p-4">
              <p className="mb-3 text-base leading-relaxed text-[#1a1b20]">
                The AWS Master Service Agreement requires a{" "}
                <strong className="text-[#3525cd]">
                  90-day written notice
                </strong>{" "}
                prior to the end of the current term for non-renewal.
              </p>
              <div className="flex flex-wrap gap-2">
                <span className="rounded border-l-2 border-[#3525cd] bg-[#3525cd]/5 px-2 py-1 text-[12px] font-semibold text-[#3525cd]">
                  AWS_MSA_2023.pdf · p. 14
                </span>
                <span className="rounded border-l-2 border-[#3525cd] bg-[#3525cd]/5 px-2 py-1 text-[12px] font-semibold text-[#3525cd]">
                  Section 12.2 (Termination)
                </span>
              </div>
            </div>
          </div>
          <div className="absolute -right-8 -bottom-8 -z-10 h-full w-full rounded-3xl bg-[#3525cd]/5" />
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function LegalProblemSection() {
  const problems = [
    {
      icon: "description",
      iconBg: "bg-[#ba1a1a]/10 text-[#ba1a1a]",
      title: "Long Contracts",
      body: "Navigating 100+ page agreements to find a single liability sub-clause takes hours of expensive legal time.",
    },
    {
      icon: "repeat",
      iconBg: "bg-[#3525cd]/10 text-[#3525cd]",
      title: "Repeated Questions",
      body: "Sales and procurement teams ask the same Standard Terms questions daily, clogging legal support queues.",
    },
    {
      icon: "event_busy",
      iconBg: "bg-[#E24329]/10 text-[#E24329]",
      title: "Missed Deadlines",
      body: "Auto-renewal dates buried in legacy PDFs are easily missed, leading to unwanted multi-year commitments.",
    },
  ];

  return (
    <section
      aria-labelledby="legal-problem-title"
      className="bg-[#f4f3f9] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="legal-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Contracts are too important to search manually.
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Manual legal reviews slow down deals and increase operational risk.
            Rudix eliminates the friction.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {problems.map((p) => (
            <li
              key={p.title}
              className="rounded-2xl border border-[#c7c4d8] bg-white p-8 transition hover:shadow-md"
            >
              <div
                className={`mb-6 flex h-12 w-12 items-center justify-center rounded-xl ${p.iconBg}`}
              >
                <Sym name={p.icon} />
              </div>
              <h3 className="mb-3 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                {p.title}
              </h3>
              <p className="text-base leading-6 text-[#464555]">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── document sources ──────────────────────────────────────────────────────────

function LegalDocumentSourcesSection() {
  const sources = [
    { icon: "groups", label: "Customer contracts" },
    { icon: "shopping_cart", label: "Vendor agreements" },
    { icon: "lock", label: "NDAs" },
    { icon: "gavel", label: "DPAs" },
    { icon: "verified_user", label: "Terms of service" },
    { icon: "library_books", label: "Legal guidance" },
  ];

  return (
    <section
      aria-labelledby="legal-doc-sources-title"
      className="bg-white py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="flex flex-col items-center gap-16 lg:flex-row">
          <div className="lg:w-1/2">
            <h2
              id="legal-doc-sources-title"
              className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              Built for every legal asset.
            </h2>
            <p className="mb-8 text-lg leading-7 text-[#464555]">
              Rudix supports complex document hierarchies and cross-references
              between master agreements and local statements of work.
            </p>
            <ul className="grid grid-cols-2 gap-4">
              {sources.map((s) => (
                <li
                  key={s.label}
                  className="flex items-center gap-3 rounded-lg border border-[#c7c4d8] bg-[#e8e7ed] p-4"
                >
                  <Sym name={s.icon} className="text-[#3525cd]" />
                  <span className="font-semibold text-[#1a1b20]">
                    {s.label}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:w-1/2">
            <div className="relative overflow-hidden rounded-3xl bg-[#0A0A0F] p-10">
              <div className="absolute inset-0 bg-gradient-to-br from-[#3525cd]/20 to-transparent" />
              <div className="relative z-10 text-center">
                <div className="mb-8 flex justify-center -space-x-4">
                  <div className="flex h-20 w-16 -rotate-12 items-center justify-center rounded-lg border border-white/20 bg-white/10 backdrop-blur">
                    <Sym name="description" className="text-white/40" />
                  </div>
                  <div className="z-10 flex h-20 w-16 items-center justify-center rounded-lg border border-white/30 bg-white/20 backdrop-blur">
                    <Sym name="description" className="text-white/60" />
                  </div>
                  <div className="z-20 flex h-20 w-16 rotate-12 items-center justify-center rounded-lg border border-[#3525cd]/50 bg-[#3525cd]/40 backdrop-blur">
                    <Sym name="description" className="text-white" />
                  </div>
                </div>
                <h4 className="mb-2 text-[24px] font-semibold text-white">
                  Instant Ingestion
                </h4>
                <p className="text-[#c3c0ff]/70">
                  Secure, encrypted processing of all legal formats.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example questions ─────────────────────────────────────────────────────────

function LegalExampleQuestionsSection() {
  const questions = [
    "What is the termination notice period?",
    "Does this contract renew automatically?",
    "Is there a limitation of liability clause?",
  ];

  return (
    <section
      aria-labelledby="legal-questions-title"
      className="bg-[#0A0A0F] py-24 text-white"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-12 flex flex-col items-end justify-between gap-6 md:flex-row">
          <div>
            <span className="mb-4 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
              Use Cases
            </span>
            <h2
              id="legal-questions-title"
              className="text-[30px] leading-[38px] font-semibold text-white"
            >
              Ask your data anything.
            </h2>
          </div>
          <p className="max-w-sm text-base leading-6 text-[#c3c0ff]/60">
            From simple lookups to complex risk analysis, Rudix provides instant
            clarity.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {questions.map((q) => (
            <li
              key={q}
              className="group flex flex-col rounded-2xl border border-white/10 bg-white/5 p-8 transition hover:bg-white/10"
            >
              <Sym
                name="chat_bubble"
                className="mb-4 text-[#c3c0ff] transition group-hover:translate-x-1"
              />
              <p className="text-lg leading-7 font-semibold">&quot;{q}&quot;</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── citations ─────────────────────────────────────────────────────────────────

function LegalCitationsSection({ securityHref }: { securityHref: string }) {
  return (
    <section
      aria-labelledby="legal-citations-title"
      className="overflow-hidden py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="grid items-center gap-20 lg:grid-cols-2">
          <div className="relative">
            <div className="relative z-10 rounded-3xl border border-[#c7c4d8] bg-[#e3e2e8] p-8">
              <div className="mb-6 flex items-center justify-between">
                <div className="flex gap-2">
                  <span className="h-3 w-3 rounded-full bg-[#ba1a1a]/40" />
                  <span className="h-3 w-3 rounded-full bg-[#E24329]/40" />
                  <span className="h-3 w-3 rounded-full bg-[#108548]/40" />
                </div>
                <span className="text-[12px] font-semibold tracking-[0.05em] text-[#777587]/50 uppercase">
                  Contract_Viewer_v2
                </span>
              </div>
              <div className="space-y-6">
                <div className="border-l-2 border-[#3525cd] pl-4">
                  <p className="mb-1 font-mono text-[14px] text-[#3525cd]">
                    Snippet from: MSA_Enterprise_Final.pdf
                  </p>
                  <p className="text-sm leading-5 text-[#464555] italic">
                    &quot;…either party may terminate this Agreement upon ninety
                    (90) days prior written notice if the other party materially
                    breaches any term…&quot;
                  </p>
                </div>
                <div className="border-l-2 border-[#3525cd] pl-4 opacity-40">
                  <p className="mb-1 font-mono text-[14px] text-[#3525cd]">
                    Snippet from: Addendum_C.pdf
                  </p>
                  <p className="text-sm leading-5 text-[#464555] italic">
                    &quot;…notwithstanding Section 12, the pricing tier remains
                    fixed for the duration of the initial term…&quot;
                  </p>
                </div>
              </div>
            </div>
            <div className="absolute -right-6 -bottom-6 -z-10 h-full w-full rounded-3xl bg-[#3525cd]/5" />
          </div>

          <div>
            <h2
              id="legal-citations-title"
              className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              Trust the source.
            </h2>
            <p className="mb-8 text-lg leading-7 text-[#464555]">
              Every answer from Rudix includes specific source snippets,
              document names, and page numbers. We never hallucinate terms — we
              only retrieve facts.
            </p>
            <ul className="mb-8 space-y-4">
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>Deep linking:</strong> Click a citation to jump
                  directly to the paragraph in the original document.
                </div>
              </li>
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>Audit trails:</strong> Full history of who asked what
                  and which documents were referenced.
                </div>
              </li>
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>Access controls:</strong> Role-scoped workspaces keep
                  privileged documents separate.
                </div>
              </li>
            </ul>

            <div className="rounded-xl border border-[#c7c4d8] bg-[#f4f3f9] p-5">
              <div className="mb-2 flex items-center gap-2 text-[#777587]">
                <Sym name="info" className="text-base" />
                <span className="text-[12px] font-semibold tracking-[0.05em] uppercase">
                  Responsible use
                </span>
              </div>
              <p className="text-sm leading-5 text-[#464555]">
                Rudix supports legal research and document workflows. It does
                not replace attorney review or constitute legal advice. All
                retrieved information should be verified by qualified legal
                counsel before reliance.
              </p>
              <PublicActionLink
                href={securityHref}
                className="mt-3 inline-flex items-center gap-1 text-[13px] font-semibold text-[#3525cd] hover:underline"
              >
                Security &amp; Compliance{" "}
                <Sym name="arrow_forward" className="text-sm" />
              </PublicActionLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function LegalFinalCtaSection({
  demoHref,
  trialHref,
}: {
  demoHref: string;
  trialHref: string;
}) {
  return (
    <section aria-labelledby="legal-cta-title" className="mb-24 py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="relative overflow-hidden rounded-[2rem] bg-[#4f46e5] p-12 text-center text-[#dad7ff] lg:p-20">
          <div className="absolute top-0 right-0 h-96 w-96 translate-x-1/2 -translate-y-1/2 rounded-full bg-white/10 blur-[100px]" />
          <div className="absolute bottom-0 left-0 h-96 w-96 -translate-x-1/2 translate-y-1/2 rounded-full bg-[#0A0A0F]/20 blur-[100px]" />
          <div className="relative z-10 mx-auto max-w-3xl">
            <h2
              id="legal-cta-title"
              className="mb-8 text-4xl leading-tight font-bold tracking-tight lg:text-[48px] lg:leading-[56px]"
            >
              Find contract answers faster.
            </h2>
            <p className="mb-10 text-xl leading-7 opacity-90">
              Join top legal teams using Rudix to automate contract intelligence
              and reduce legal risk.
            </p>
            <div className="flex flex-col justify-center gap-4 sm:flex-row">
              <PublicActionLink
                href={trialHref}
                className="rounded-xl bg-white px-10 py-5 text-lg font-bold text-[#3525cd] transition hover:shadow-xl active:scale-95"
              >
                Start Free Trial
              </PublicActionLink>
              <PublicActionLink
                href={demoHref}
                className="rounded-xl border-2 border-white/30 bg-transparent px-10 py-5 text-lg font-bold text-white transition hover:bg-white/10 active:scale-95"
              >
                Book a Demo
              </PublicActionLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function LegalSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <LegalBreadcrumb />
      <LegalHeroSection demoHref={links.requestDemo} />
      <LegalProblemSection />
      <LegalDocumentSourcesSection />
      <LegalExampleQuestionsSection />
      <LegalCitationsSection securityHref={links.security} />
      <LegalFinalCtaSection
        demoHref={links.requestDemo}
        trialHref={links.startTrial}
      />
    </>
  );
}
