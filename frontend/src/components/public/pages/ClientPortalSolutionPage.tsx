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

function ClientPortalBreadcrumb() {
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
          Client Portal
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function ClientPortalHeroSection({
  trialHref,
  demoHref,
}: {
  trialHref: string;
  demoHref: string;
}) {
  return (
    <section
      aria-labelledby="cp-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="z-10">
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold tracking-[0.05em] text-[#3323cc] uppercase">
            Client Knowledge Portal
          </span>
          <h1
            id="cp-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Give clients instant answers from your approved documentation.
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            Deploy a scoped AI Q&A layer over your client-facing docs. Reduce
            repetitive support questions, accelerate onboarding, and give
            customers citation-backed answers — without overloading your team.
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={trialHref}
              className="rounded-lg bg-[#3525cd] px-8 py-4 font-semibold text-white shadow-lg transition hover:shadow-xl active:scale-95"
            >
              Start Free Trial
            </PublicActionLink>
            <PublicActionLink
              href={demoHref}
              className="rounded-lg border border-[#c7c4d8] px-8 py-4 font-semibold text-[#0A0A0F] transition hover:bg-[#eeedf3] active:scale-95"
            >
              Request Demo
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
          <div className="relative z-20 rounded-2xl bg-[#0A0A0F] p-8 shadow-2xl">
            <div className="mb-6 flex items-center gap-3">
              <div className="h-3 w-3 rounded-full bg-[#ba1a1a]" />
              <div className="h-3 w-3 rounded-full bg-[#E24329]" />
              <div className="h-3 w-3 rounded-full bg-[#108548]" />
              <span className="ml-auto font-mono text-[10px] tracking-widest text-[#777587] uppercase">
                Portal Q&A
              </span>
            </div>
            <div className="space-y-5 font-mono text-sm">
              <div>
                <p className="mb-1 text-[10px] tracking-widest text-[#c3c0ff] uppercase">
                  Customer
                </p>
                <p className="text-white">
                  &ldquo;How do I set up SSO for my team?&rdquo;
                </p>
              </div>
              <div className="border-t border-white/10 pt-5">
                <p className="mb-2 text-[10px] tracking-widest text-[#75db94] uppercase">
                  Rudix
                </p>
                <p className="text-[#e3e2e8]">
                  Navigate to Settings &rarr; Security and upload your IdP
                  metadata file. Okta and Azure AD are fully supported.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded bg-[#3525cd]/20 px-2 py-0.5 text-[10px] text-[#c3c0ff]">
                    Setup Guide v3.1
                  </span>
                  <span className="rounded bg-[#3525cd]/20 px-2 py-0.5 text-[10px] text-[#c3c0ff]">
                    Admin Docs
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

// ── problem ───────────────────────────────────────────────────────────────────

function ClientPortalProblemSection() {
  const problems = [
    {
      icon: "forum",
      title: "Repeated client questions",
      body: "Support and account teams field the same onboarding and implementation questions daily — questions already answered in your documentation.",
    },
    {
      icon: "folder_off",
      title: "Scattered onboarding docs",
      body: "Customers can't find what they need across PDFs, wikis, and portals, slowing implementation timelines and frustrating new accounts.",
    },
    {
      icon: "transfer_within_a_station",
      title: "Slow implementation handoffs",
      body: "Without a shared, searchable knowledge layer, every account handoff starts from scratch and strains customer success bandwidth.",
    },
  ];

  return (
    <section aria-labelledby="cp-problem-title" className="bg-[#f4f3f9] py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="cp-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            The Client Knowledge Gap
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Customers expect fast, accurate answers. Without a trusted knowledge
            layer, your support and account teams absorb the cost.
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

function ClientPortalDocumentSourcesSection() {
  const sources = [
    { icon: "rocket_launch", label: "Onboarding Guides" },
    { icon: "integration_instructions", label: "API Documentation" },
    { icon: "build", label: "Implementation Guides" },
    { icon: "support_agent", label: "Knowledge Base" },
    { icon: "menu_book", label: "Product Guides" },
    { icon: "handshake", label: "Enablement Materials" },
  ];

  const features = [
    "Approve and scope which docs are client-visible",
    "Index across PDF, DOCX, and Markdown formats",
    "Citation-backed answers from approved sources only",
    "Access boundaries between customer segments",
  ];

  return (
    <section aria-labelledby="cp-doc-title" className="bg-white py-24">
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="order-2 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:order-1 lg:grid-cols-2">
          {sources.map((s) => (
            <div
              key={s.label}
              className="rudix-landing-glass flex flex-col items-center justify-center rounded-lg p-6 text-center"
            >
              <Sym name={s.icon} className="mb-3 text-3xl text-[#3525cd]" />
              <span className="text-sm font-semibold text-[#0A0A0F]">
                {s.label}
              </span>
            </div>
          ))}
        </div>

        <div className="order-1 lg:order-2">
          <h2
            id="cp-doc-title"
            className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Approved sources, scoped access.
          </h2>
          <p className="mb-6 text-lg leading-7 text-[#464555]">
            Rudix indexes only the documents you approve for client visibility.
            Every answer cites the exact source so customers and your team can
            verify every response — with no content surfaced from outside your
            approved documentation set.
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

// ── workflow / how it works ───────────────────────────────────────────────────

function ClientPortalWorkflowSection() {
  return (
    <section
      aria-labelledby="cp-workflow-title"
      className="bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="cp-workflow-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-white"
          >
            From document approval to client Q&A
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            A controlled workflow that puts your team in charge of what clients
            can ask — and what answers they receive.
          </p>
        </div>

        <div className="grid h-auto grid-cols-1 gap-6 md:h-[600px] md:grid-cols-4 md:grid-rows-2">
          {/* Step 01 — large card */}
          <div className="group relative col-span-1 flex flex-col justify-end overflow-hidden rounded-2xl border border-white/10 bg-[#3525cd]/10 p-10 md:col-span-2 md:row-span-2">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-[#3525cd]/20 via-transparent to-transparent opacity-60"
            />
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
                Approve Client-Facing Docs
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                Your team selects and uploads the documentation clients are
                allowed to query — onboarding guides, implementation docs,
                product manuals, and support knowledge. Nothing outside the
                approved set is ever surfaced.
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
                Index & Scope Access
              </h3>
            </div>
            <p className="text-base leading-6 text-[#464555]">
              Rudix semantically indexes approved content and applies access
              boundaries — different customer segments can query different
              document sets without overlap.
            </p>
          </div>

          {/* Step 03 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-8">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                Step 03
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                Expose Q&A
              </h3>
            </div>
            <Sym name="question_answer" className="text-4xl text-[#c3c0ff]" />
          </div>

          {/* Step 04 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-[#3525cd] bg-[#3525cd] p-8 text-white">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-white/60 uppercase">
                Step 04
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                Verify & Improve
              </h3>
            </div>
            <Sym name="fact_check" className="text-4xl text-white" />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── use cases ─────────────────────────────────────────────────────────────────

function ClientPortalUseCasesSection() {
  const useCases = [
    {
      icon: "rocket_launch",
      title: "Customer Onboarding",
      body: "New customers self-serve setup and configuration questions, reducing time-to-value and cutting onboarding call volume.",
    },
    {
      icon: "build",
      title: "Implementation Docs",
      body: "Technical buyers and integration teams query configuration guides with cited answers — no waiting for an SE to respond.",
    },
    {
      icon: "handshake",
      title: "Partner Enablement",
      body: "Channel and solution partners get accurate product answers without direct access to your internal knowledge base.",
    },
    {
      icon: "support_agent",
      title: "Support Knowledge",
      body: "Customers resolve common support questions on their own, cutting Tier-1 ticket volume and escalation overhead.",
    },
    {
      icon: "swap_horiz",
      title: "Account Handoff",
      body: "When accounts move between CSM owners, a shared knowledge layer ensures continuity and reduces ramp time.",
    },
  ];

  return (
    <section aria-labelledby="cp-usecases-title" className="bg-[#f4f3f9] py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="cp-usecases-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Built for every client touchpoint
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            From first login to long-term account management, Rudix supports the
            moments where clients need answers fast.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {useCases.map((u) => (
            <li
              key={u.title}
              className="rounded-xl border border-[#c7c4d8] bg-white p-8 transition hover:border-[#3525cd]"
            >
              <Sym name={u.icon} className="mb-4 text-4xl text-[#3525cd]" />
              <h3 className="mb-3 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                {u.title}
              </h3>
              <p className="text-base leading-6 text-[#464555]">{u.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function ClientPortalExampleQueriesSection() {
  const examples = [
    {
      question: "How do I configure SAML-based SSO for my organization?",
      answer:
        "Navigate to Settings → Security → SSO and upload your IdP metadata XML file. Supported providers include Okta, Azure AD, and Google Workspace. Full configuration steps are in Admin Setup Guide, Section 3.2.",
      sources: ["Admin Setup Guide v3.2", "Security Configuration Docs"],
    },
    {
      question: "What data is retained after I close my account?",
      answer:
        "Per the Data Retention Policy (Section 5), account data is purged within 30 days of account closure. Audit logs are retained for 90 days as required for compliance. No customer data is shared with third parties after deletion.",
      sources: ["Data Retention Policy", "Privacy FAQ"],
    },
  ];

  return (
    <section
      aria-labelledby="cp-queries-title"
      className="overflow-hidden bg-white py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <h2
          id="cp-queries-title"
          className="mb-16 text-center text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
        >
          Cited answers. Every time.
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
                      Rudix Answer:
                    </span>
                    <p className="mb-4">{e.answer}</p>
                    <div className="flex flex-wrap gap-2">
                      {e.sources.map((s) => (
                        <span
                          key={s}
                          className="rounded border border-[#c7c4d8] bg-[#f4f3f9] px-2 py-0.5 text-[10px] font-bold uppercase"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
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

// ── related solutions ─────────────────────────────────────────────────────────

function ClientPortalRelatedSolutionsSection() {
  const related = [
    { label: "Support", href: "/solutions/support" },
    { label: "Sales", href: "/solutions/sales" },
    { label: "Internal Knowledge", href: "/solutions/internal-knowledge" },
    { label: "Security", href: "/security" },
  ];

  return (
    <section aria-labelledby="cp-related-title" className="bg-[#f4f3f9] py-16">
      <div className="mx-auto max-w-[1440px] px-10">
        <h2
          id="cp-related-title"
          className="mb-8 text-center text-[24px] leading-8 font-semibold text-[#1a1b20]"
        >
          Explore related solutions
        </h2>
        <ul className="flex flex-wrap justify-center gap-4">
          {related.map((r) => (
            <li key={r.label}>
              <PublicActionLink
                href={r.href}
                className="rounded-full border border-[#c7c4d8] bg-white px-6 py-3 font-semibold text-[#3525cd] transition hover:border-[#3525cd] hover:bg-[#e2dfff] active:scale-95"
              >
                {r.label}
              </PublicActionLink>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function ClientPortalFinalCtaSection({
  demoHref,
  trialHref,
}: {
  demoHref: string;
  trialHref: string;
}) {
  return (
    <section
      aria-labelledby="cp-cta-title"
      className="relative overflow-hidden bg-[#faf9ff] py-32"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[#3525cd]/5"
      />
      <div className="mx-auto max-w-[1440px] px-10 text-center">
        <div className="rudix-landing-glass mx-auto max-w-3xl rounded-3xl border border-[#3525cd]/20 p-12 lg:p-16">
          <h2
            id="cp-cta-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Your clients deserve better answers.
          </h2>
          <p className="mb-10 text-lg leading-7 text-[#464555]">
            Deploy a scoped, citation-backed knowledge layer your customers can
            trust — without overloading your support team or overpromising
            capabilities that aren&apos;t ready yet.
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
            Rudix surfaces answers from approved documents — it does not replace
            a full external client portal or manage client identity and access.
          </p>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function ClientPortalSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <ClientPortalBreadcrumb />
      <ClientPortalHeroSection
        trialHref={links.startTrial}
        demoHref={links.requestDemo}
      />
      <ClientPortalProblemSection />
      <ClientPortalDocumentSourcesSection />
      <ClientPortalWorkflowSection />
      <ClientPortalUseCasesSection />
      <ClientPortalExampleQueriesSection />
      <ClientPortalRelatedSolutionsSection />
      <ClientPortalFinalCtaSection
        demoHref={links.requestDemo}
        trialHref={links.startTrial}
      />
    </>
  );
}
