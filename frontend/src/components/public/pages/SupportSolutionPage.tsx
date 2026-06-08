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

function SupportBreadcrumb() {
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
          Support
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function SupportHeroSection({
  demoHref,
  contactHref,
}: {
  demoHref: string;
  contactHref: string;
}) {
  return (
    <section
      aria-labelledby="support-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="absolute top-0 right-0 -z-10 h-full w-1/2 bg-gradient-to-l from-[#e2dfff]/20 to-transparent" />
      <div className="mx-auto grid max-w-[1440px] items-center gap-6 px-10 lg:grid-cols-2">
        <div className="z-10">
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold tracking-[0.05em] text-[#3323cc] uppercase">
            Support Solutions
          </span>
          <h1
            id="support-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Help support agents answer faster.
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            Give support teams instant access to answers from product
            documentation, troubleshooting guides, FAQs, runbooks, and release
            notes.
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-8 py-4 text-sm font-semibold text-white shadow-lg transition hover:opacity-90 active:scale-95"
            >
              Speak to us about support
            </PublicActionLink>
            <PublicActionLink
              href={contactHref}
              className="flex items-center gap-2 rounded-xl border border-[#777587] px-8 py-4 text-sm font-semibold text-[#3525cd] transition hover:bg-[#eeedf3]"
            >
              <Sym name="play_circle" />
              View Demo
            </PublicActionLink>
          </div>
        </div>

        <div className="relative mt-12 lg:mt-0">
          <div className="rudix-landing-glass relative z-10 overflow-hidden rounded-2xl p-4 shadow-xl">
            <div className="rounded-xl border border-[#e3e2e8] bg-[#f4f3f9] p-5">
              <div className="mb-4 flex items-center gap-2">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
                <span className="text-[12px] font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  Support Workspace — Active
                </span>
              </div>
              <div className="mb-3 rounded-full border border-[#c7c4d8] bg-white px-4 py-2.5 text-sm text-[#464555] italic shadow-sm">
                &quot;How do I escalate a P1 incident under the SLA?&quot;
              </div>
              <div className="rounded-xl bg-[#1F1E24] p-4 font-mono text-[14px] leading-5 text-[#eeedf3]">
                <p className="mb-2 text-[#c3c0ff]">
                  # Source: Escalation_Playbook_v4.pdf
                </p>
                <p className="text-[#eeedf3]">
                  1. Acknowledge within 15 minutes via on-call channel...
                  <br />
                  2. Open a war-room call and notify the customer...
                  <br />
                  3. Escalate to Tier 2 if unresolved within 30 min.
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-lg bg-white px-4 py-2">
                <span className="text-xs text-[#777587]">Confidence</span>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[#e3e2e8]">
                    <div className="h-full w-[94%] rounded-full bg-[#108548]" />
                  </div>
                  <span className="text-xs font-semibold text-[#108548]">
                    94%
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="absolute -right-6 -bottom-6 z-20 rounded-xl bg-[#1F1E24] p-5 shadow-2xl">
            <div className="mb-2 flex items-center gap-2">
              <Sym name="query_stats" className="text-base text-[#c3c0ff]" />
              <span className="text-[11px] font-semibold tracking-widest text-[#777587] uppercase">
                Response Metric
              </span>
            </div>
            <p className="text-xl font-bold text-white">
              −84%{" "}
              <span className="text-sm font-normal text-[#777587]">
                Search Time
              </span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function SupportProblemSection() {
  const problems = [
    {
      icon: "search_off",
      title: "Tool Fatigue",
      body: "Agents search too many tools — Confluence, Notion, and Slack — wasting 30% of their shift just looking for answers.",
    },
    {
      icon: "speed",
      title: "Slow Onboarding",
      body: "New agents need faster onboarding to reach full productivity. Currently, training takes weeks of shadowing senior staff.",
    },
    {
      icon: "sync_problem",
      title: "Inconsistent Data",
      body: "Customers expect fast and consistent answers. Outdated docs lead to conflicting advice and lower CSAT scores.",
    },
  ];

  return (
    <section
      aria-labelledby="support-problem-title"
      className="bg-[#f4f3f9] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="support-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Support knowledge is often scattered.
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Siloed information leads to slower resolutions and agent burnout.
          </p>
        </div>
        <ul className="grid gap-6 md:grid-cols-3">
          {problems.map((p) => (
            <li key={p.title} className="rudix-landing-glass rounded-2xl p-8">
              <Sym name={p.icon} className="mb-4 text-[36px] text-[#3525cd]" />
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

function SupportDocumentSourcesSection() {
  const sources = [
    { icon: "menu_book", label: "Product Documentation" },
    { icon: "build", label: "Troubleshooting Guides" },
    { icon: "quiz", label: "FAQs" },
    { icon: "new_releases", label: "Release Notes" },
    { icon: "warning", label: "Known Issue Lists" },
    { icon: "priority_high", label: "Escalation Runbooks" },
  ];

  const features = [
    "Real-time sync with Confluence and ZenDesk",
    "Parsing of complex PDF diagrams and runbooks",
    "Version-controlled knowledge retrieval",
  ];

  return (
    <section
      aria-labelledby="support-doc-sources-title"
      className="bg-white py-24"
    >
      <div className="mx-auto grid max-w-[1440px] items-center gap-16 px-10 lg:grid-cols-2">
        <div className="order-2 grid grid-cols-2 gap-4 lg:order-1">
          {sources.map((s) => (
            <div
              key={s.label}
              className="group rounded-xl border border-[#c7c4d8] bg-[#eeedf3] p-6 transition hover:border-[#3525cd]"
            >
              <Sym
                name={s.icon}
                className="mb-4 text-[#464555] transition group-hover:text-[#3525cd]"
              />
              <p className="mb-1 text-[12px] font-semibold tracking-[0.05em] text-[#777587] uppercase">
                Data Source
              </p>
              <p className="font-bold text-[#1a1b20]">{s.label}</p>
            </div>
          ))}
        </div>

        <div className="order-1 lg:order-2">
          <h2
            id="support-doc-sources-title"
            className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            Connect all your support assets.
          </h2>
          <p className="mb-8 text-lg leading-7 text-[#464555]">
            Rudix indexes your existing technical knowledge base to create a
            high-fidelity retrieval engine specifically for your support agents.
          </p>
          <ul className="space-y-4">
            {features.map((f) => (
              <li
                key={f}
                className="flex items-start gap-3 text-base leading-6"
              >
                <Sym name="check_circle" className="mt-0.5 text-[#108548]" />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

// ── how it works ──────────────────────────────────────────────────────────────

function SupportHowItWorksSection() {
  const steps = [
    {
      icon: "upload_file",
      label: "1. Upload",
      desc: "Support uploads docs from multiple formats.",
      accent: "bg-[#3525cd] shadow-[0_0_24px_rgba(53,37,205,0.3)]",
      iconColor: "text-white",
    },
    {
      icon: "database",
      label: "2. Index",
      desc: "Rudix creates vector embeddings of your data.",
      accent: "border border-[#3525cd] text-[#3525cd] bg-[#eeedf3]",
      iconColor: "",
    },
    {
      icon: "chat",
      label: "3. Ask",
      desc: "Agents ask natural language questions.",
      accent: "border border-[#3525cd] text-[#3525cd] bg-[#eeedf3]",
      iconColor: "",
    },
    {
      icon: "verified",
      label: "4. Resolve",
      desc: "Answers with sources for instant resolution.",
      accent: "bg-[#108548] shadow-[0_0_24px_rgba(16,133,72,0.3)]",
      iconColor: "text-white",
    },
  ];

  return (
    <section
      aria-labelledby="support-flow-title"
      className="overflow-hidden bg-[#0A0A0F] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="support-flow-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#faf9ff]"
          >
            How it works
          </h2>
          <p className="text-base leading-6 text-[#777587]">
            A robust pipeline from raw documentation to verified agent answers.
          </p>
        </div>

        <div className="relative flex flex-col items-center justify-between gap-12 md:flex-row">
          <div className="absolute top-1/2 left-0 hidden w-full -translate-y-8 border-t border-dashed border-[#e2dfff]/30 md:block" />
          {steps.map((s) => (
            <div
              key={s.label}
              className="relative z-10 flex max-w-[240px] flex-col items-center text-center"
            >
              <div
                className={`mb-6 flex h-16 w-16 items-center justify-center rounded-full text-3xl ${s.accent}`}
              >
                <Sym
                  name={s.icon}
                  className={s.iconColor || "text-[#3525cd]"}
                />
              </div>
              <h3 className="mb-2 font-bold text-white">{s.label}</h3>
              <p className="text-sm leading-5 text-[#777587]">{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function SupportExampleQueriesSection() {
  return (
    <section
      aria-labelledby="support-queries-title"
      className="bg-[#faf9ff] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-12 flex flex-col items-end justify-between gap-6 md:flex-row">
          <div>
            <h2
              id="support-queries-title"
              className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              Precision retrieval in action.
            </h2>
            <p className="text-base leading-6 text-[#464555]">
              See how Rudix handles complex technical queries with ease.
            </p>
          </div>
          <div className="flex shrink-0 gap-1 rounded-full bg-[#e3e2e8] p-1.5">
            <span className="rounded-full bg-white px-5 py-2 text-[12px] font-semibold tracking-[0.05em] uppercase shadow-sm">
              Agent view
            </span>
            <span className="px-5 py-2 text-[12px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
              Admin view
            </span>
          </div>
        </div>

        <div className="grid h-auto grid-cols-1 gap-6 md:h-[500px] md:grid-cols-12">
          <div className="rudix-landing-glass group relative col-span-1 flex flex-col justify-between overflow-hidden rounded-2xl p-8 md:col-span-8">
            <div>
              <div className="mb-6 flex items-center gap-2">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
                <span className="text-[12px] font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  Active Query
                </span>
              </div>
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                &quot;How do I troubleshoot login failures for users on
                Enterprise Plan v2?&quot;
              </h3>
              <div className="rounded-xl bg-[#1F1E24] p-6 font-mono text-[14px] leading-5 text-[#eeedf3]">
                <p className="mb-2 text-[#c3c0ff]">
                  # Source: Auth_Runbook_v2.1.pdf
                </p>
                <p>
                  1. Verify the &apos;client_id&apos; matches the region...
                  <br />
                  2. Check for &apos;error_code: 403_STALE&apos; in the logs...
                  <br />
                  3. Ensure SSO provider metadata is rotated.
                </p>
              </div>
            </div>
          </div>

          <div className="col-span-1 space-y-6 md:col-span-4">
            <div className="rudix-landing-glass rounded-2xl border-l-4 border-[#3525cd] p-6">
              <h4 className="mb-2 font-bold text-[#1a1b20]">
                &quot;Which plan includes SSO?&quot;
              </h4>
              <p className="text-sm leading-5 text-[#464555]">
                &quot;SSO is available on Enterprise and Custom plans. See
                pricing.md for details.&quot;
              </p>
            </div>
            <div className="rudix-landing-glass rounded-2xl border-l-4 border-[#E24329] p-6">
              <h4 className="mb-2 font-bold text-[#1a1b20]">
                &quot;What changed in the latest release?&quot;
              </h4>
              <p className="text-sm leading-5 text-[#464555]">
                &quot;Release 4.2 introduced Webhooks and enhanced API rate
                limiting. See CHANGELOG.txt&quot;
              </p>
            </div>
            <div className="rounded-2xl bg-[#3525cd] p-6 text-white">
              <div className="mb-3 flex items-center justify-between">
                <Sym name="auto_awesome" className="text-base" />
                <span className="text-[11px] font-bold tracking-widest uppercase opacity-80">
                  Smart Suggest
                </span>
              </div>
              <p className="font-bold">Ask about API keys</p>
              <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/20">
                <div className="h-full w-2/3 rounded-full bg-white" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function SupportFinalCtaSection({
  demoHref,
  contactHref,
}: {
  demoHref: string;
  contactHref: string;
}) {
  return (
    <section
      aria-labelledby="support-cta-title"
      className="relative overflow-hidden py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="relative overflow-hidden rounded-3xl bg-[#0A0A0F] p-16 text-center">
          <div className="absolute -top-1/2 -left-1/4 h-full w-full rounded-full bg-[#3525cd]/20 blur-[120px]" />
          <div className="relative z-10">
            <h2
              id="support-cta-title"
              className="mb-6 text-4xl leading-tight font-bold tracking-tight text-white lg:text-[48px] lg:leading-[56px]"
            >
              Give your support team a document-backed copilot.
            </h2>
            <p className="mx-auto mb-10 max-w-2xl text-lg leading-7 text-[#777587]">
              Reduce ticket resolution time and increase CSAT by empowering your
              agents with the right information at the right time.
            </p>
            <div className="flex flex-wrap justify-center gap-4">
              <PublicActionLink
                href={demoHref}
                className="rounded-xl bg-[#3525cd] px-10 py-5 text-lg font-bold text-white transition hover:scale-105 active:scale-95"
              >
                Get Started
              </PublicActionLink>
              <PublicActionLink
                href={contactHref}
                className="rounded-xl border border-white/20 bg-white/10 px-10 py-5 text-lg font-bold text-white backdrop-blur-md transition hover:bg-white/20"
              >
                Request a Demo
              </PublicActionLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function SupportSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SupportBreadcrumb />
      <SupportHeroSection
        demoHref={links.requestDemo}
        contactHref={links.contact}
      />
      <SupportProblemSection />
      <SupportDocumentSourcesSection />
      <SupportHowItWorksSection />
      <SupportExampleQueriesSection />
      <SupportFinalCtaSection
        demoHref={links.startTrial}
        contactHref={links.requestDemo}
      />
    </>
  );
}
