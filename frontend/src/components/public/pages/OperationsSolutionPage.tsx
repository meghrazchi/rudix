"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

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

function OperationsBreadcrumb() {
  const t = useTranslations("public");

  return (
    <nav
      aria-label="Breadcrumb"
      className="mx-auto w-full max-w-[1440px] px-10 pt-6"
    >
      <ol className="flex items-center gap-2 text-xs text-[#777587]">
        <li>
          <PublicActionLink href="/" className="hover:text-[#3525cd]">
            {t("home")}
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#c7c4d8]">
          /
        </li>
        <li>
          <PublicActionLink href="/solutions" className="hover:text-[#3525cd]">
            {t("breadcrumb.solutions")}
          </PublicActionLink>
        </li>
        <li aria-hidden="true" className="text-[#c7c4d8]">
          /
        </li>
        <li aria-current="page" className="font-semibold text-[#1a1b20]">
          {t("operations.breadcrumb")}
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function OperationsHeroSection({
  demoHref,
  docsHref,
}: {
  demoHref: string;
  docsHref: string;
}) {
  const t = useTranslations("public.operations");

  return (
    <section
      aria-labelledby="ops-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="relative z-10 mx-auto max-w-[1440px] px-10">
        <div className="max-w-3xl">
          <span className="mb-6 inline-block rounded-full bg-[#3525cd]/10 px-4 py-1.5 text-[12px] font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
            {t("hero.badge")}
          </span>
          <h1
            id="ops-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            {t("hero.heading")}
          </h1>
          <p className="mb-10 max-w-2xl text-lg leading-7 text-[#464555]">
            {t("hero.description")}
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-8 py-4 text-lg font-semibold text-white shadow-lg shadow-[#3525cd]/20 transition hover:opacity-90 active:scale-95"
            >
              {t("hero.primaryCta")}
            </PublicActionLink>
            <PublicActionLink
              href={docsHref}
              className="rounded-xl border border-[#c7c4d8] bg-[#faf9ff] px-8 py-4 text-lg font-semibold text-[#1a1b20] transition hover:bg-[#f4f3f9] active:scale-95"
            >
              {t("hero.secondaryCta")}
            </PublicActionLink>
          </div>
        </div>
      </div>

      {/* decorative diagram */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/4 right-[-10%] hidden w-5/12 opacity-20 lg:block"
      >
        <div className="-rotate-[4deg] rounded-2xl border border-[#c7c4d8]/30 bg-[#f4f3f9] p-8">
          <div className="mb-4 flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#3525cd] text-white">
              <Sym name="terminal" />
            </div>
            <div className="space-y-1">
              <div className="h-4 w-32 rounded bg-[#c7c4d8]" />
              <div className="h-3 w-48 rounded bg-[#c7c4d8]/40" />
            </div>
          </div>
          <div className="space-y-4">
            <div className="h-4 w-full rounded bg-[#c7c4d8]/20" />
            <div className="h-4 w-5/6 rounded bg-[#c7c4d8]/20" />
            <div className="h-4 w-4/6 rounded bg-[#c7c4d8]/20" />
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function OperationsProblemSection() {
  return (
    <section aria-labelledby="ops-problem-title" className="bg-white py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="ops-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            During incidents, searching documents wastes time.
          </h2>
          <p className="mx-auto max-w-2xl text-lg leading-7 text-[#464555]">
            Every second spent looking for a wiki page is a second of downtime.
            Modern ops teams need answers, not archives.
          </p>
        </div>

        <ul className="grid grid-cols-1 gap-6 md:grid-cols-12">
          <li className="relative overflow-hidden rounded-2xl border border-[#c7c4d8]/30 bg-[#f4f3f9] p-10 md:col-span-7">
            <div className="relative z-10">
              <Sym
                name="inventory_2"
                className="mb-6 text-4xl text-[#3525cd]"
              />
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                Runbooks scattered across wikis
              </h3>
              <p className="text-lg leading-7 text-[#464555]">
                Stop the &quot;Where is that PDF?&quot; panic. Rudix unifies
                knowledge from Confluence, Notion, and GitHub into a single
                high-availability retrieval engine.
              </p>
            </div>
            <Sym
              name="hub"
              className="pointer-events-none absolute -right-8 -bottom-8 text-[200px] text-[#464555] opacity-5 transition-opacity group-hover:opacity-10"
            />
          </li>

          <li className="relative overflow-hidden rounded-2xl border border-[#0A0A0F] bg-[#0A0A0F] p-10 text-[#faf9ff] md:col-span-5">
            <div className="relative z-10">
              <Sym name="timer" className="mb-6 text-4xl text-[#c3c0ff]" />
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#faf9ff]">
                Incident steps need to be followed quickly
              </h3>
              <p className="text-lg leading-7 text-[#464555]">
                When services are down, reading a 20-page SOP is impossible. Get
                exact, bulleted instructions in seconds, not minutes.
              </p>
            </div>
            <div className="absolute bottom-0 left-0 h-1 w-full bg-gradient-to-r from-[#3525cd] to-transparent" />
          </li>

          <li className="flex flex-col items-center gap-10 rounded-2xl border border-[#c7c4d8]/30 bg-white p-10 md:col-span-12 md:flex-row">
            <div className="flex-1">
              <Sym name="warning" className="mb-6 text-4xl text-[#ba1a1a]" />
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                Outdated procedures create risk
              </h3>
              <p className="text-lg leading-7 text-[#464555]">
                Deprecated commands in old runbooks lead to catastrophic
                mistakes. Rudix weights the newest documentation higher,
                ensuring teams always use current recovery logic.
              </p>
            </div>
            <div className="relative h-48 w-full flex-1 overflow-hidden rounded-xl">
              <Image
                src="/images/solutions/operations/terminal-ops.jpg"
                alt="Code terminal showing operations runbook and incident response procedures"
                fill
                className="object-cover opacity-60 grayscale"
                sizes="(max-width: 768px) 100vw, 40vw"
              />
            </div>
          </li>
        </ul>
      </div>
    </section>
  );
}

// ── document sources ──────────────────────────────────────────────────────────

function OperationsDocumentSourcesSection() {
  const sources = [
    { icon: "description", label: "Incident response runbooks" },
    { icon: "menu_book", label: "SOPs" },
    { icon: "build", label: "Troubleshooting guides" },
    { icon: "rocket_launch", label: "Deployment procedures" },
    { icon: "notification_important", label: "Escalation policies" },
    { icon: "settings_backup_restore", label: "System recovery guides" },
  ];

  return (
    <section
      aria-labelledby="ops-doc-sources-title"
      className="bg-[#faf9ff] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 flex flex-col items-end justify-between gap-8 md:flex-row">
          <div className="max-w-2xl">
            <h2
              id="ops-doc-sources-title"
              className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              Universal technical ingestion.
            </h2>
            <p className="text-lg leading-7 text-[#464555]">
              Rudix supports your existing operational stack. Just upload, and
              we&apos;ll index the technical nuance.
            </p>
          </div>
        </div>
        <ul className="grid grid-cols-2 gap-6 lg:grid-cols-3">
          {sources.map((s) => (
            <li
              key={s.label}
              className="flex items-center gap-4 rounded-xl border border-[#c7c4d8]/50 bg-[#eeedf3] p-6 transition hover:bg-[#e8e7ed]"
            >
              <Sym name={s.icon} className="shrink-0 text-[#3525cd]" />
              <span className="font-semibold text-[#1a1b20]">{s.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── how it works ──────────────────────────────────────────────────────────────

function OperationsHowItWorksSection() {
  const steps = [
    {
      icon: "upload_file",
      label: "Upload",
      desc: "Team uploads runbooks and procedures.",
    },
    {
      icon: "database",
      label: "Index",
      desc: "Rudix indexes technical context and dependencies.",
    },
    {
      icon: "question_answer",
      label: "Ask",
      desc: "Team asks questions during live incidents.",
    },
    {
      icon: "verified",
      label: "Solve",
      desc: "Immediate answer with precise citations.",
    },
  ];

  return (
    <section
      aria-labelledby="ops-flow-title"
      className="overflow-hidden bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-20 text-center">
          <h2
            id="ops-flow-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#faf9ff]"
          >
            How Rudix secures your uptime.
          </h2>
          <p className="text-lg leading-7 text-[#464555]">
            Automated RAG workflow designed for mission-critical reliability.
          </p>
        </div>

        <div className="relative">
          <ol className="relative z-10 grid grid-cols-1 gap-12 md:grid-cols-4">
            {steps.map((s) => (
              <li
                key={s.label}
                className="flex flex-col items-center text-center"
              >
                <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full border border-[#3525cd]/50 bg-[#3525cd]/20">
                  <Sym name={s.icon} className="text-3xl text-[#c3c0ff]" />
                </div>
                <h3 className="mb-2 text-[24px] leading-8 font-semibold text-[#faf9ff]">
                  {s.label}
                </h3>
                <p className="text-base leading-6 text-[#464555]">{s.desc}</p>
              </li>
            ))}
          </ol>

          {/* animated flow line */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute top-8 left-0 hidden w-full md:block"
          >
            <div className="workflow-connector h-0.5 w-full">
              <div className="workflow-connector__packet" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function OperationsExampleQueriesSection() {
  const questions = [
    {
      icon: "alternate_email",
      text: "What are the steps for a priority incident?",
    },
    {
      icon: "sync_problem",
      text: "How do we restart the failed indexing worker?",
    },
    {
      icon: "person_alert",
      text: "Who needs to be notified during an outage?",
    },
  ];

  return (
    <section aria-labelledby="ops-queries-title" className="bg-[#f4f3f9] py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="flex flex-col items-center gap-16 lg:flex-row">
          <div className="flex-1">
            <h2
              id="ops-queries-title"
              className="mb-6 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              Built for the high-pressure query.
            </h2>
            <p className="mb-8 text-lg leading-7 text-[#464555]">
              Ops teams don&apos;t have time to craft the perfect prompt. Ask
              naturally, get the technical truth.
            </p>
            <ul className="space-y-4">
              {questions.map((q) => (
                <li
                  key={q.text}
                  className="group flex cursor-pointer items-center gap-4 rounded-lg border border-[#c7c4d8]/50 bg-white p-4 transition hover:border-[#3525cd]"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-[#eeedf3] text-[#3525cd] transition group-hover:bg-[#3525cd] group-hover:text-white">
                    <Sym name={q.icon} className="text-sm" />
                  </div>
                  <span className="font-semibold text-[#1a1b20]">
                    &quot;{q.text}&quot;
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* chat interface mockup */}
          <div className="w-full flex-1">
            <div className="rounded-2xl bg-[#0A0A0F] p-1 shadow-2xl">
              <div className="rounded-xl border border-white/10 bg-[#0A0A0F] p-8">
                {/* user message */}
                <div className="mb-8 flex gap-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#3525cd]">
                    <Sym name="person" className="text-sm text-white" />
                  </div>
                  <div className="rounded-2xl bg-white/10 p-4 text-[#faf9ff]">
                    How do we restart the failed indexing worker?
                  </div>
                </div>

                {/* bot response */}
                <div className="flex gap-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#006f3a]">
                    <Sym
                      name="auto_awesome"
                      className="text-sm text-[#91f8ae]"
                    />
                  </div>
                  <div className="w-full space-y-4">
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
                      <p className="mb-4 font-semibold text-[#c3c0ff]">
                        According to the &apos;Infrastructure Recovery SOP
                        (v2.4)&apos;:
                      </p>
                      <ol className="list-inside list-decimal space-y-2 text-[#464555]">
                        <li>
                          Navigate to the{" "}
                          <code className="rounded bg-white/10 px-1 font-mono text-[13px] text-[#faf9ff]">
                            /ops/workers
                          </code>{" "}
                          directory.
                        </li>
                        <li>
                          Run{" "}
                          <code className="rounded bg-white/10 px-1 font-mono text-[13px] text-[#faf9ff]">
                            kubectl rollout restart deployment/indexing-worker
                          </code>
                          .
                        </li>
                        <li>
                          Verify health by checking the Prometheus dashboard for
                          200 OK status.
                        </li>
                      </ol>
                      <div className="mt-6 flex items-center gap-2 border-t border-white/10 pt-4 text-xs text-[#464555]">
                        <Sym name="link" className="text-sm" />
                        Citations: Infrastructure_SOP_v2.4.pdf (Page 12),
                        On-Call_Handbook.md
                      </div>
                    </div>
                  </div>
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

function OperationsFinalCtaSection({
  demoHref,
  contactHref,
}: {
  demoHref: string;
  contactHref: string;
}) {
  const t = useTranslations("public.operations");

  return (
    <section
      aria-labelledby="ops-cta-title"
      className="relative overflow-hidden bg-[#3525cd] py-32"
    >
      {/* dot grid overlay */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-10"
        style={{
          backgroundImage:
            "radial-gradient(circle at 2px 2px, white 1px, transparent 0)",
          backgroundSize: "40px 40px",
        }}
      />
      <div className="relative z-10 mx-auto max-w-[1440px] px-10 text-center">
        <h2
          id="ops-cta-title"
          className="mb-8 text-4xl leading-tight font-bold tracking-tight text-white lg:text-[48px] lg:leading-[56px]"
        >
          {t("cta.heading")}
        </h2>
        <p className="mx-auto mb-12 max-w-2xl text-lg leading-7 text-[#c3c0ff]">
          {t("cta.description")}
        </p>
        <div className="flex flex-col justify-center gap-4 sm:flex-row">
          <PublicActionLink
            href={demoHref}
            className="rounded-xl bg-white px-10 py-5 text-lg font-bold text-[#3525cd] transition hover:bg-[#e2dfff] active:scale-95"
          >
            {t("cta.primaryCta")}
          </PublicActionLink>
          <PublicActionLink
            href={contactHref}
            className="rounded-xl border border-white/30 bg-[#4f46e5] px-10 py-5 text-lg font-bold text-white transition hover:bg-[#3525cd]/80 active:scale-95"
          >
            {t("cta.secondaryCta")}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function OperationsSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <OperationsBreadcrumb />
      <OperationsHeroSection
        demoHref={links.requestDemo}
        docsHref={links.docs}
      />
      <OperationsProblemSection />
      <OperationsDocumentSourcesSection />
      <OperationsHowItWorksSection />
      <OperationsExampleQueriesSection />
      <OperationsFinalCtaSection
        demoHref={links.requestDemo}
        contactHref={links.requestDemo}
      />
    </>
  );
}
