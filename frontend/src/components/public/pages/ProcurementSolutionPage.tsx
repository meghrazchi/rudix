"use client";

import Image from "next/image";

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

function ProcurementBreadcrumb() {
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
          Procurement
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function ProcurementHeroSection({
  trialHref,
  demoHref,
}: {
  trialHref: string;
  demoHref: string;
}) {
  return (
    <section
      aria-labelledby="proc-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="z-10">
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold tracking-[0.05em] text-[#3323cc] uppercase">
            Procurement &amp; Vendor Review
          </span>
          <h1
            id="proc-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Evaluate vendors with AI-powered document review.
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            Accelerate your security and legal vetting process. Rudix's
            RAG-enabled platform ingests complex vendor documentation to provide
            instant, cited answers to your most critical compliance questions.
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={trialHref}
              className="rounded-lg bg-[#3525cd] px-8 py-4 font-semibold text-white shadow-lg transition hover:shadow-xl active:scale-95"
            >
              Start Review
            </PublicActionLink>
            <PublicActionLink
              href={demoHref}
              className="rounded-lg border border-[#c7c4d8] px-8 py-4 font-semibold text-[#0A0A0F] transition hover:bg-[#eeedf3] active:scale-95"
            >
              View Demo
            </PublicActionLink>
          </div>
        </div>

        <div className="relative">
          <div
            aria-hidden="true"
            className="absolute -top-10 -right-10 -z-10 h-64 w-64 rounded-full bg-[#c3c0ff]/30 blur-3xl"
          />
          <div
            aria-hidden="true"
            className="absolute -bottom-10 -left-10 -z-10 h-80 w-80 rounded-full bg-[#75db94]/20 blur-3xl"
          />
          <div className="rudix-landing-glass relative z-20 aspect-square overflow-hidden rounded-2xl shadow-2xl">
            <Image
              src="/images/solutions/procurement/vendor-dashboard.jpg"
              alt="Procurement analytics dashboard showing vendor evaluation data"
              fill
              className="object-cover opacity-90"
              sizes="(max-width: 1024px) 100vw, 50vw"
              priority
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-tr from-[#3525cd]/10 to-transparent"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function ProcurementProblemSection() {
  const problems = [
    {
      icon: "assignment_late",
      title: "Long security questionnaires",
      body: "Weeks spent manually parsing through spreadsheets and vendor responses just to verify basic security standards.",
    },
    {
      icon: "compare_arrows",
      title: "Manual contract comparison",
      body: "Struggling to identify nuanced differences in indemnification and liability clauses across dozens of vendor variants.",
    },
    {
      icon: "warning_amber",
      title: "Risk assessment friction",
      body: "Inconsistent risk profiling due to human error and the sheer volume of technical documentation to review.",
    },
  ];

  return (
    <section
      aria-labelledby="proc-problem-title"
      className="bg-[#f4f3f9] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="proc-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            The Procurement Bottleneck
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Manual vendor assessments are the primary source of friction in
            modern enterprise deployment cycles.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {problems.map((p) => (
            <li
              key={p.title}
              className="rounded-xl border border-[#c7c4d8] bg-white p-8 transition hover:border-[#3525cd]"
            >
              <Sym name={p.icon} className="mb-6 text-4xl text-[#3525cd]" />
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
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

function ProcurementDocumentSourcesSection() {
  const sources = [
    { icon: "description", label: "SOC2 Reports" },
    { icon: "fact_check", label: "RFP Responses" },
    { icon: "gavel", label: "Vendor Contracts" },
    { icon: "security", label: "Security Questionnaires" },
  ];

  const features = [
    "OCR for scanned documents",
    "Multi-format support (PDF, DOCX, XLSX)",
    "Automated metadata tagging",
  ];

  return (
    <section aria-labelledby="proc-doc-title" className="bg-white py-24">
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="order-2 grid grid-cols-2 gap-4 lg:order-1">
          {sources.map((s) => (
            <div
              key={s.label}
              className="rudix-landing-glass flex flex-col items-center justify-center rounded-lg p-6 text-center"
            >
              <Sym name={s.icon} className="mb-3 text-3xl text-[#3525cd]" />
              <span className="font-semibold text-[#0A0A0F]">{s.label}</span>
            </div>
          ))}
        </div>

        <div className="order-1 lg:order-2">
          <h2
            id="proc-doc-title"
            className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Unified Knowledge Ingestion
          </h2>
          <p className="mb-6 text-lg leading-7 text-[#464555]">
            Rudix connects directly to your procurement inbox or document
            repository. Our RAG engine extracts technical lineage from
            unstructured PDFs, spreadsheets, and legal documents.
          </p>
          <ul className="space-y-4">
            {features.map((f) => (
              <li
                key={f}
                className="flex items-center gap-3 text-base leading-6"
              >
                <Sym name="check_circle" className="shrink-0 text-[#108548]" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

// ── engine / how it works ─────────────────────────────────────────────────────

function ProcurementEngineSection() {
  return (
    <section
      aria-labelledby="proc-engine-title"
      className="bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="proc-engine-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-white"
          >
            The Rudix Engine for Procurement
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            From document upload to risk decision in minutes.
          </p>
        </div>

        <div className="grid h-auto grid-cols-1 gap-6 md:h-[600px] md:grid-cols-4 md:grid-rows-2">
          {/* Step 01 — large card */}
          <div className="group relative col-span-1 flex flex-col justify-end overflow-hidden rounded-2xl border border-white/10 bg-[#3525cd]/10 p-10 md:col-span-2 md:row-span-2">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-[#3525cd]/20 via-transparent to-transparent opacity-60"
            />
            {/* decorative grid pattern */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 opacity-10"
              style={{
                backgroundImage:
                  "radial-gradient(circle at 2px 2px, #c3c0ff 1px, transparent 0)",
                backgroundSize: "28px 28px",
              }}
            />
            <div className="relative z-10">
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                Step 01
              </span>
              <h3 className="mb-4 text-[30px] leading-[38px] font-semibold text-white">
                Deep Semantic Indexing
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                We don't just search keywords. Rudix understands the context of
                security controls and legal obligations across your entire
                vendor library.
              </p>
            </div>
          </div>

          {/* Step 02 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-8 md:col-span-2">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                Step 02
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                Automated Extraction
              </h3>
            </div>
            <p className="text-base leading-6 text-[#464555]">
              Instantly map vendor responses to your internal risk framework
              (ISO 27001, SOC2, HIPAA).
            </p>
          </div>

          {/* Step 03 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-8">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                Step 03
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                Flag Risk
              </h3>
            </div>
            <Sym name="report" className="text-4xl text-[#ba1a1a]" />
          </div>

          {/* Step 04 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-[#3525cd] bg-[#3525cd] p-8 text-white">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-white/60 uppercase">
                Step 04
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                Approve
              </h3>
            </div>
            <Sym name="verified" className="text-4xl text-white" />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function ProcurementExampleQueriesSection() {
  const examples = [
    {
      question:
        "Which vendor meets our data residency requirements for the EU?",
      answer:
        "Vendor A (CloudFlow) specifies in Section 4.2 of their DPA that data is stored in Frankfurt. Vendor B (DataMesh) lacks specific EU region commitments in their current SOC2 report.",
    },
    {
      question: "Summarize the security controls in this SOC2 report.",
      answer:
        "The SOC2 Type II for Vendor C covers Security and Availability. Key controls include AES-256 encryption at rest, quarterly penetration testing, and a 99.9% uptime SLA. No exceptions were noted in the auditor's report.",
    },
  ];

  return (
    <section
      aria-labelledby="proc-queries-title"
      className="overflow-hidden bg-white py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <h2
          id="proc-queries-title"
          className="mb-16 text-center text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
        >
          Ask Anything. Get Citations.
        </h2>
        <div className="mx-auto flex max-w-4xl flex-col gap-8">
          {examples.map((e) => (
            <div
              key={e.question}
              className="rounded-xl border-l-4 border-[#3525cd] bg-[#eeedf3] p-6 shadow-sm"
            >
              <div className="flex items-start gap-4">
                <Sym
                  name="help_center"
                  className="mt-1 shrink-0 text-[#3525cd]"
                />
                <div>
                  <p className="mb-4 text-lg leading-7 font-semibold text-[#0A0A0F]">
                    {e.question}
                  </p>
                  <div className="rounded-lg border border-[#c7c4d8]/30 bg-white p-4 text-base leading-6 text-[#464555]">
                    <span className="mb-2 block font-semibold text-[#3525cd]">
                      Rudix Analysis:
                    </span>
                    {e.answer}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function ProcurementFinalCtaSection({
  demoHref,
  trialHref,
}: {
  demoHref: string;
  trialHref: string;
}) {
  return (
    <section
      aria-labelledby="proc-cta-title"
      className="relative overflow-hidden bg-[#faf9ff] py-32"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[#3525cd]/5"
      />
      <div className="mx-auto max-w-[1440px] px-10 text-center">
        <div className="rudix-landing-glass mx-auto max-w-3xl rounded-3xl border border-[#3525cd]/20 p-12 lg:p-16">
          <h2
            id="proc-cta-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Stop Reviewing, Start Deciding.
          </h2>
          <p className="mb-10 text-lg leading-7 text-[#464555]">
            Join forward-thinking procurement teams using Rudix to slash vendor
            review times. Secure your supply chain with source-grounded
            intelligence.
          </p>
          <div className="flex flex-col justify-center gap-4 sm:flex-row">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-10 py-5 text-lg font-bold text-white shadow-lg transition hover:-translate-y-1 hover:shadow-xl active:scale-95"
            >
              Schedule a Demo
            </PublicActionLink>
            <PublicActionLink
              href={trialHref}
              className="rounded-xl bg-[#0A0A0F] px-10 py-5 text-lg font-bold text-[#faf9ff] transition hover:bg-black active:scale-95"
            >
              Get Started Free
            </PublicActionLink>
          </div>
          <p className="mt-8 text-[12px] font-semibold tracking-[0.05em] text-[#777587] uppercase">
            Rudix surfaces answers for review — it does not replace legal or
            procurement approval workflows.
          </p>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function ProcurementSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <ProcurementBreadcrumb />
      <ProcurementHeroSection
        trialHref={links.startTrial}
        demoHref={links.requestDemo}
      />
      <ProcurementProblemSection />
      <ProcurementDocumentSourcesSection />
      <ProcurementEngineSection />
      <ProcurementExampleQueriesSection />
      <ProcurementFinalCtaSection
        demoHref={links.requestDemo}
        trialHref={links.startTrial}
      />
    </>
  );
}
