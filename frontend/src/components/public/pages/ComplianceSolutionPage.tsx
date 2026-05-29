"use client";

import Image from "next/image";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

function Sym({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>
      {name}
    </span>
  );
}

// ── breadcrumb ────────────────────────────────────────────────────────────────

function ComplianceBreadcrumb() {
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
        <li aria-hidden="true" className="text-[#c7c4d8]">/</li>
        <li>
          <PublicActionLink href="/solutions" className="hover:text-[#3525cd]">
            Solutions
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#c7c4d8]">/</li>
        <li aria-current="page" className="font-semibold text-[#1a1b20]">
          Compliance
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function ComplianceHeroSection({ demoHref }: { demoHref: string }) {
  return (
    <section
      aria-labelledby="compliance-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_right,rgba(53,37,205,0.05),transparent_50%)]" />
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="space-y-8">
          <span className="inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-[#3323cc]">
            Solution: Compliance
          </span>
          <h1
            id="compliance-hero-title"
            className="max-w-xl text-4xl font-bold leading-tight tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Find audit evidence faster.
          </h1>
          <p className="max-w-lg text-lg leading-7 text-[#464555]">
            Use Rudix to retrieve cited answers from policies, procedures,
            security documents, audit evidence, and compliance files.
          </p>
          <div className="flex flex-wrap gap-4 pt-4">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-8 py-4 text-[24px] font-semibold leading-8 text-white shadow-lg transition hover:opacity-90 active:scale-95"
            >
              Speak to us about compliance
            </PublicActionLink>
          </div>
        </div>

        <div className="group relative">
          <div className="absolute -inset-4 -z-10 rounded-full bg-[#3525cd]/10 opacity-50 blur-3xl transition-opacity group-hover:opacity-75" />
          <div className="rudix-landing-glass relative rounded-xl border border-[#c7c4d8]/50 p-8 shadow-2xl">
            <div className="mb-6 flex items-center justify-between border-b border-[#c7c4d8] pb-4">
              <div className="flex items-center gap-3">
                <Sym name="shield" className="text-[#3525cd]" />
                <span className="text-[12px] font-semibold uppercase tracking-[0.05em] text-[#464555]">
                  Compliance Engine
                </span>
              </div>
              <div className="flex gap-2">
                <span className="h-3 w-3 rounded-full bg-[#ba1a1a]/20" />
                <span className="h-3 w-3 rounded-full bg-[#00542a]/20" />
                <span className="h-3 w-3 rounded-full bg-[#3525cd]/20" />
              </div>
            </div>
            <div className="space-y-4 font-mono text-[14px] leading-5">
              <div className="flex items-start gap-4 rounded-lg border border-[#c7c4d8]/20 bg-[#eeedf3] p-3">
                <Sym name="search" className="mt-1 shrink-0 text-[#3525cd]" />
                <p className="italic text-[#464555]">
                  "What supports our access review process?"
                </p>
              </div>
              <div className="rounded-lg border border-[#3525cd]/30 bg-[#0A0A0F] p-4 text-[#faf9ff]">
                <p className="mb-2">Retrieving evidence...</p>
                <div className="mb-4 h-1 overflow-hidden rounded-full bg-[#e3e2e8]">
                  <div className="h-full w-2/3 rounded-full bg-[#3525cd]" />
                </div>
                <div className="space-y-2 opacity-90">
                  <p className="text-[#c3c0ff]">Matches found in:</p>
                  <ul className="list-inside list-disc text-[#e2dfff]">
                    <li>SOC2_Evidence_Q4.pdf (p.12)</li>
                    <li>Access_Policy_v2.docx (Sec 4.1)</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function ComplianceProblemSection() {
  const problems = [
    {
      icon: "folder_off",
      iconBg: "bg-[#ffdad6]/30 text-[#ba1a1a]",
      title: "Evidence Fragmentation",
      body: "Scattered documentation across disparate cloud drives, emails, and local servers makes comprehensive audits nearly impossible to manage.",
    },
    {
      icon: "link",
      iconBg: "bg-[#3525cd]/10 text-[#3525cd]",
      title: "Traceability Gaps",
      body: "Policy answers frequently lack direct links to original source documents, leaving compliance officers to manually re-verify every claim.",
    },
    {
      icon: "timer",
      iconBg: "bg-[#E24329]/10 text-[#E24329]",
      title: "Manual Collection Drain",
      body: "Auditors spend 60% of their time collecting evidence instead of analyzing it. Manual retrieval is slow, error-prone, and expensive.",
    },
  ];

  return (
    <section aria-labelledby="compliance-problem-title" className="bg-[#f4f3f9] py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 space-y-4 text-center">
          <h2
            id="compliance-problem-title"
            className="text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
          >
            Audit evidence is difficult to find when it is spread across files.
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Manual collection drains resources and risks non-compliance. Rudix
            centralizes the discovery process with precision.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-8 md:grid-cols-3">
          {problems.map((p) => (
            <li
              key={p.title}
              className="rounded-xl border border-[#c7c4d8] bg-white p-8 shadow-sm transition hover:shadow-md"
            >
              <div
                className={`mb-6 flex h-12 w-12 items-center justify-center rounded-lg ${p.iconBg}`}
              >
                <Sym name={p.icon} />
              </div>
              <h3 className="mb-4 text-[24px] font-semibold leading-8 text-[#1a1b20]">
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

function ComplianceDocumentSourcesSection() {
  const sources = [
    { icon: "gpp_good", label: "Security Policies" },
    { icon: "fact_check", label: "Audit Evidence" },
    { icon: "warning", label: "Risk Assessments" },
    { icon: "group", label: "Access Reviews" },
    { icon: "emergency", label: "Incident Response" },
  ];

  return (
    <section aria-labelledby="compliance-doc-sources-title" className="bg-white py-24">
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div>
          <h2
            id="compliance-doc-sources-title"
            className="mb-6 text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
          >
            Upload everything. Find anything.
          </h2>
          <p className="mb-12 text-lg leading-7 text-[#464555]">
            Rudix ingests your entire compliance ecosystem, maintaining full
            context and structural integrity across diverse file formats.
          </p>
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {sources.map((s) => (
              <li
                key={s.label}
                className="flex items-center gap-3 rounded-lg border border-[#c7c4d8] bg-[#faf9ff] p-4"
              >
                <Sym name={s.icon} className="text-[#3525cd]" />
                <span className="text-base leading-6 text-[#1a1b20]">{s.label}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="relative h-48 overflow-hidden rounded-xl shadow-lg">
            <Image
              src="/images/solutions/compliance/documents.jpg"
              alt="Contract documents on a desk — compliance and audit preparation"
              fill
              className="object-cover"
              sizes="(max-width: 768px) 50vw, 25vw"
            />
          </div>
          <div className="relative h-64 translate-y-8 overflow-hidden rounded-xl shadow-lg">
            <Image
              src="/images/solutions/compliance/audit-workspace.jpg"
              alt="Professional auditor reviewing data analytics on a laptop"
              fill
              className="object-cover"
              sizes="(max-width: 768px) 50vw, 25vw"
            />
          </div>
          <div className="relative h-64 -translate-y-16 overflow-hidden rounded-xl shadow-lg">
            <Image
              src="/images/solutions/compliance/data-center.jpg"
              alt="Enterprise data center server racks — secure infrastructure"
              fill
              className="object-cover"
              sizes="(max-width: 768px) 50vw, 25vw"
            />
          </div>
          <div className="relative h-48 -translate-y-8 overflow-hidden rounded-xl shadow-lg">
            <Image
              src="/images/solutions/compliance/data-visualization.jpg"
              alt="Abstract data visualization representing connected compliance systems"
              fill
              className="object-cover"
              sizes="(max-width: 768px) 50vw, 25vw"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example questions ─────────────────────────────────────────────────────────

function ComplianceExampleQuestionsSection() {
  const examples = [
    {
      icon: "question_mark",
      question: "Where is the data retention policy?",
      answer:
        "Rudix identifies specific paragraphs in Global_Privacy_v4.pdf and cross-references internal SOPs.",
    },
    {
      icon: "verified",
      question: "What evidence supports access reviews?",
      answer:
        "Instantly pulls Q1–Q4 log exports and the IAM approval procedure cited in your latest audit plan.",
    },
    {
      icon: "enhanced_encryption",
      question: "Which policy mentions encryption requirements?",
      answer:
        "Scans all security controls and highlights ISO 27001 Annex A clauses mapped to internal technical standards.",
    },
  ];

  return (
    <section
      aria-labelledby="compliance-questions-title"
      className="relative overflow-hidden bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="absolute top-0 right-0 h-full w-1/2 bg-[radial-gradient(circle_at_center,rgba(53,37,205,0.15),transparent_70%)]" />
      <div className="relative z-10 mx-auto max-w-[1440px] px-10">
        <div className="mb-16">
          <h2
            id="compliance-questions-title"
            className="mb-4 text-[30px] font-semibold leading-[38px] text-white"
          >
            Interrogate your evidence.
          </h2>
          <p className="max-w-xl text-lg leading-7 text-[#e3e2e8]">
            Ask natural language questions and get cited answers instantly from
            your compliance library.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {examples.map((e) => (
            <li
              key={e.question}
              className="group rounded-xl border border-white/10 bg-white/5 p-8 backdrop-blur-sm transition hover:border-[#3525cd]"
            >
              <Sym name={e.icon} className="mb-6 block text-[#c3c0ff]" />
              <p className="mb-4 text-lg font-semibold italic leading-7">
                "{e.question}"
              </p>
              <div className="mb-6 h-px w-12 bg-white/10 transition-all group-hover:w-full" />
              <p className="text-base leading-6 text-[#e3e2e8]">{e.answer}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── trust / governance ────────────────────────────────────────────────────────

function ComplianceTrustSection({ securityHref }: { securityHref: string }) {
  const features = [
    {
      icon: "menu_book",
      title: "Audit-friendly source references",
      body: "Every answer includes deep-links to the exact page and paragraph of the source document.",
    },
    {
      icon: "lock_person",
      title: "Permission-filtered retrieval",
      body: "Users can only retrieve information from documents they are explicitly authorized to view in your IAM system.",
    },
    {
      icon: "receipt_long",
      title: "Admin activity logs",
      body: "Complete immutable history of every query, response, and document access for internal governance.",
    },
  ];

  const activityItems = [
    {
      action: "Audit log retrieval",
      doc: "SOC2_v2",
      user: "j_smith@enterprise.com",
      time: "2m ago",
      badge: "Verified",
      badgeBg: "bg-[#91f8ae] text-[#00210d]",
    },
    {
      action: "Source download",
      doc: "ISO_Annex_A",
      user: "k_chen@corp.com",
      time: "15m ago",
      badge: "Verified",
      badgeBg: "bg-[#91f8ae] text-[#00210d]",
    },
    {
      action: "New document indexed",
      doc: "Q4_Evidence_01",
      user: "System",
      time: "1h ago",
      badge: "Indexed",
      badgeBg: "bg-[#e2dfff] text-[#0f0069]",
      dim: true,
    },
  ];

  return (
    <section aria-labelledby="compliance-trust-title" className="bg-white py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="relative overflow-hidden rounded-3xl border border-[#c7c4d8] bg-[#eeedf3] p-12 lg:p-16">
          <div className="absolute -right-24 -bottom-24 h-96 w-96 rounded-full bg-[#3525cd]/5 blur-3xl" />
          <div className="grid grid-cols-1 items-center gap-16 lg:grid-cols-2">
            <div className="space-y-12">
              <div>
                <h2
                  id="compliance-trust-title"
                  className="mb-4 text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
                >
                  Built for enterprise-grade trust.
                </h2>
                <p className="text-lg leading-7 text-[#464555]">
                  Compliance isn't just about finding data — it's about
                  verifying it securely and maintaining a perfect trail.
                </p>
              </div>

              <div className="space-y-8">
                {features.map((f) => (
                  <div key={f.title} className="flex gap-6">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-[#c7c4d8] bg-white shadow-sm">
                      <Sym name={f.icon} className="text-[#3525cd]" />
                    </div>
                    <div>
                      <h3 className="mb-2 text-[24px] font-semibold leading-8 text-[#1a1b20]">
                        {f.title}
                      </h3>
                      <p className="text-base leading-6 text-[#464555]">{f.body}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-xl border border-[#c7c4d8] bg-[#f4f3f9] p-5">
                <div className="mb-2 flex items-center gap-2 text-[#777587]">
                  <Sym name="info" className="text-base" />
                  <span className="text-[12px] font-semibold uppercase tracking-[0.05em]">
                    Compliance disclaimer
                  </span>
                </div>
                <p className="text-sm leading-5 text-[#464555]">
                  Rudix supports evidence discovery and policy research. It does
                  not issue certifications or replace auditor review. All
                  retrieved evidence should be validated by your compliance team
                  before submission to any regulatory body.
                </p>
                <PublicActionLink
                  href={securityHref}
                  className="mt-3 inline-flex items-center gap-1 text-[13px] font-semibold text-[#3525cd] hover:underline"
                >
                  Security &amp; Compliance
                  <Sym name="arrow_forward" className="text-sm" />
                </PublicActionLink>
              </div>
            </div>

            <div className="relative">
              <div className="space-y-6 rounded-2xl border border-[#c7c4d8] bg-white p-8 shadow-xl">
                <div className="mb-2 flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#3525cd]/10">
                    <Sym name="history" className="text-[20px] text-[#3525cd]" />
                  </div>
                  <span className="text-[12px] font-semibold uppercase tracking-[0.05em] text-[#464555]">
                    Activity Stream
                  </span>
                </div>

                <ul className="space-y-4">
                  {activityItems.map((item) => (
                    <li
                      key={item.doc}
                      className={`flex items-center justify-between rounded-lg border border-[#c7c4d8]/30 bg-[#f4f3f9] p-4 transition ${item.dim ? "opacity-60" : ""}`}
                    >
                      <div className="space-y-1">
                        <p className="text-base leading-6 text-[#1a1b20]">
                          {item.action}:{" "}
                          <span className="font-bold">{item.doc}</span>
                        </p>
                        <p className="text-xs text-[#464555]">
                          {item.user === "System"
                            ? `System • ${item.time}`
                            : `User: ${item.user} • ${item.time}`}
                        </p>
                      </div>
                      <span
                        className={`rounded px-2 py-1 text-[10px] font-bold ${item.badgeBg}`}
                      >
                        {item.badge.toUpperCase()}
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="flex justify-center border-t border-[#c7c4d8] pt-4">
                  <span className="text-[12px] font-semibold uppercase tracking-[0.05em] text-[#3525cd]">
                    View Full Audit Trail
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function ComplianceFinalCtaSection({
  demoHref,
  docsHref,
}: {
  demoHref: string;
  docsHref: string;
}) {
  return (
    <section
      aria-labelledby="compliance-cta-title"
      className="relative overflow-hidden py-32"
    >
      <div className="absolute inset-0 -z-10 bg-[#3525cd]/5" />
      <div className="mx-auto max-w-4xl px-10 text-center">
        <h2
          id="compliance-cta-title"
          className="mb-8 text-4xl font-bold leading-tight tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
        >
          Make compliance evidence easier to find.
        </h2>
        <p className="mb-12 text-lg leading-7 text-[#464555]">
          Join forward-thinking enterprise teams who have cut their audit
          preparation time with Rudix high-fidelity retrieval.
        </p>
        <div className="flex flex-col justify-center gap-4 sm:flex-row">
          <PublicActionLink
            href={demoHref}
            className="rounded-xl bg-[#3525cd] px-10 py-5 text-[24px] font-semibold leading-8 text-white shadow-lg transition hover:shadow-xl active:scale-95"
          >
            Speak to us
          </PublicActionLink>
          <PublicActionLink
            href={docsHref}
            className="rounded-xl border border-[#3525cd] bg-white px-10 py-5 text-[24px] font-semibold leading-8 text-[#3525cd] transition hover:bg-[#e2dfff]/30 active:scale-95"
          >
            View Documentation
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function ComplianceSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <ComplianceBreadcrumb />
      <ComplianceHeroSection demoHref={links.requestDemo} />
      <ComplianceProblemSection />
      <ComplianceDocumentSourcesSection />
      <ComplianceExampleQuestionsSection />
      <ComplianceTrustSection securityHref={links.security} />
      <ComplianceFinalCtaSection demoHref={links.requestDemo} docsHref={links.docs} />
    </>
  );
}
