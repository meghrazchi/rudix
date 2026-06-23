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

function ResearchBreadcrumb() {
  const t = useTranslations("public");

  return (
    <div className="border-b border-[#e2e5ef] bg-[#f2f3f6]">
      <nav
        aria-label="Breadcrumb"
        className="mx-auto w-full max-w-[1440px] px-10 py-3"
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
            <PublicActionLink
              href="/solutions"
              className="hover:text-[#3525cd]"
            >
              {t("breadcrumb.solutions")}
            </PublicActionLink>
          </li>
          <li aria-hidden="true" className="text-[#c7c4d8]">
            /
          </li>
          <li aria-current="page" className="font-semibold text-[#1a1b20]">
            {t("research.breadcrumb")}
          </li>
        </ol>
      </nav>
    </div>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function ResearchHeroSection({
  demoHref,
  docsHref,
}: {
  demoHref: string;
  docsHref: string;
}) {
  const t = useTranslations("public.research");

  return (
    <section
      aria-labelledby="research-hero-title"
      className="rudix-research-dot-bg relative overflow-hidden pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div>
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-[#e2dfff] px-3 py-1 text-[#3323cc]">
            <Sym name="analytics" className="text-[18px]" />
            <span className="text-[12px] font-semibold tracking-[0.05em] uppercase">
              {t("hero.badge")}
            </span>
          </div>
          <h1
            id="research-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#1a1b20] lg:text-[48px] lg:leading-[56px]"
          >
            {t("hero.heading")}
          </h1>
          <p className="mb-8 max-w-xl text-lg leading-7 text-[#464555]">
            {t("hero.description")}
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={demoHref}
              className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-8 py-4 text-base font-semibold text-white transition hover:shadow-xl active:scale-95"
            >
              {t("hero.primaryCta")}
              <Sym name="arrow_forward" />
            </PublicActionLink>
            <PublicActionLink
              href={docsHref}
              className="rounded-xl border border-[#777587] px-8 py-4 text-base font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3] active:scale-95"
            >
              {t("hero.secondaryCta")}
            </PublicActionLink>
          </div>
        </div>

        <div className="relative">
          <div className="absolute -top-12 -right-12 -z-10 h-64 w-64 rounded-full bg-[#3525cd]/10 blur-3xl" />
          <div className="rudix-landing-glass relative z-10 rounded-2xl p-4 shadow-2xl">
            <div className="relative h-72 w-full overflow-hidden rounded-lg">
              <Image
                src="/images/solutions/research/analyst-dashboard.jpg"
                alt="Enterprise research analyst dashboard showing data visualizations and document insights"
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 50vw"
                priority
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function ResearchProblemSection() {
  const t = useTranslations("public.research");
  const cards = [
    { title: t("problems.overloadTitle"), body: t("problems.overloadBody") },
    { title: t("problems.manualTitle"), body: t("problems.manualBody") },
    { title: t("problems.citationsTitle"), body: t("problems.citationsBody") },
    {
      title: t("problems.fragmentationTitle"),
      body: t("problems.fragmentationBody"),
    },
  ];

  return (
    <section
      aria-labelledby="research-problem-title"
      className="bg-[#f4f3f9] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="research-problem-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            {t("problems.heading")}
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            {t("problems.description")}
          </p>
        </div>

        <ul className="grid auto-rows-auto grid-cols-1 gap-6 md:grid-cols-12">
          <li className="rudix-landing-glass group relative overflow-hidden rounded-2xl p-10 md:col-span-8">
            <div className="relative z-10">
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                {cards[0].title}
              </h3>
              <p className="max-w-lg text-base leading-6 text-[#464555]">
                {cards[0].body}
              </p>
            </div>
            <Sym
              name="cloud_off"
              className="pointer-events-none absolute top-0 right-0 p-8 text-[120px] text-[#464555] opacity-20 transition-opacity group-hover:opacity-40"
            />
          </li>

          <li className="flex flex-col justify-between rounded-2xl bg-[#0A0A0F] p-10 text-[#faf9ff] md:col-span-4">
            <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-lg bg-[#3525cd]">
              <Sym name="description" className="text-white" />
            </div>
            <div>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-[#faf9ff]">
                {cards[1].title}
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                {cards[1].body}
              </p>
            </div>
          </li>

          <li className="rudix-landing-glass flex flex-col gap-4 rounded-2xl p-10 md:col-span-4">
            <Sym name="link" className="text-4xl text-[#3525cd]" />
            <h3 className="text-[24px] leading-8 font-semibold text-[#1a1b20]">
              {cards[2].title}
            </h3>
            <p className="text-base leading-6 text-[#464555]">
              {cards[2].body}
            </p>
          </li>

          <li className="flex items-center gap-8 rounded-2xl bg-[#e3e2e8] p-10 md:col-span-8">
            <div
              aria-hidden="true"
              className="hidden h-32 w-32 shrink-0 items-center justify-center rounded-full border-4 border-dashed border-[#3525cd]/30 sm:flex"
            >
              <Sym
                name="troubleshoot"
                className="animate-pulse text-[#3525cd]"
              />
            </div>
            <div>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                {cards[3].title}
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                {cards[3].body}
              </p>
            </div>
          </li>
        </ul>
      </div>
    </section>
  );
}

// ── document types ────────────────────────────────────────────────────────────

function ResearchDocumentSourcesSection() {
  const t = useTranslations("public.research");
  const sources = [
    {
      icon: "article",
      label: t("documentSources.whitepapers"),
      desc: t("documentSources.whitepapersDesc"),
    },
    {
      icon: "query_stats",
      label: t("documentSources.marketResearch"),
      desc: t("documentSources.marketResearchDesc"),
    },
    {
      icon: "lab_profile",
      label: t("documentSources.analystReports"),
      desc: t("documentSources.analystReportsDesc"),
    },
    {
      icon: "science",
      label: t("documentSources.technicalPapers"),
      desc: t("documentSources.technicalPapersDesc"),
    },
    {
      icon: "account_tree",
      label: t("documentSources.strategyDocs"),
      desc: t("documentSources.strategyDocsDesc"),
    },
  ];

  return (
    <section
      aria-labelledby="research-doc-sources-title"
      className="bg-white py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 flex flex-col items-end justify-between gap-8 md:flex-row">
          <div className="max-w-xl">
            <h2
              id="research-doc-sources-title"
              className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
            >
              {t("documentSources.heading")}
            </h2>
            <p className="text-base leading-6 text-[#464555]">
              {t("documentSources.description")}
            </p>
          </div>
        </div>
        <ul className="grid grid-cols-2 gap-6 md:grid-cols-3 lg:grid-cols-5">
          {sources.map((s) => (
            <li
              key={s.label}
              className="group rounded-xl border border-[#c7c4d8] p-6 transition hover:border-[#3525cd]"
            >
              <Sym
                name={s.icon}
                className="mb-4 text-[#464555] transition group-hover:text-[#3525cd]"
              />
              <p className="mb-1 font-semibold text-[#1a1b20]">{s.label}</p>
              <p className="text-sm text-[#464555]">{s.desc}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── pipeline / how it works ───────────────────────────────────────────────────

function ResearchPipelineSection() {
  const t = useTranslations("public.research");
  const steps = [
    {
      n: "1",
      title: t("pipeline.step1Title"),
      body: t("pipeline.step1Body"),
    },
    {
      n: "2",
      title: t("pipeline.step2Title"),
      body: t("pipeline.step2Body"),
    },
    {
      n: "3",
      title: t("pipeline.step3Title"),
      body: t("pipeline.step3Body"),
    },
  ];

  return (
    <section
      aria-labelledby="research-pipeline-title"
      className="overflow-hidden bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="grid grid-cols-1 items-center gap-20 lg:grid-cols-2">
          <div>
            <h2
              id="research-pipeline-title"
              className="mb-8 text-[30px] leading-[38px] font-semibold text-[#faf9ff]"
            >
              {t("pipeline.heading")}
            </h2>
            <ol className="space-y-12">
              {steps.map((s) => (
                <li key={s.n} className="flex gap-6">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#3525cd] font-bold text-[#3525cd]">
                    {s.n}
                  </div>
                  <div>
                    <h3 className="mb-2 text-[24px] leading-8 font-semibold text-[#faf9ff]">
                      {s.title}
                    </h3>
                    <p className="text-base leading-6 text-[#464555]">
                      {s.body}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="relative rounded-3xl border border-white/10 bg-[#1F1E24] p-8">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 rounded-3xl bg-[#3525cd]/5 blur-3xl"
            />
            <svg
              className="h-auto w-full"
              viewBox="0 0 400 300"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect
                x="20"
                y="120"
                width="80"
                height="40"
                rx="4"
                fill="#3525cd"
              />
              <text
                x="60"
                y="145"
                textAnchor="middle"
                fill="white"
                fontSize="10"
              >
                {t("pipeline.svgSource")}
              </text>
              <rect
                x="160"
                y="20"
                width="80"
                height="40"
                rx="4"
                fill="#3525cd"
              />
              <text
                x="200"
                y="45"
                textAnchor="middle"
                fill="white"
                fontSize="10"
              >
                {t("pipeline.svgEmbeddings")}
              </text>
              <rect
                x="160"
                y="220"
                width="80"
                height="40"
                rx="4"
                fill="#3525cd"
              />
              <text
                x="200"
                y="245"
                textAnchor="middle"
                fill="white"
                fontSize="10"
              >
                {t("pipeline.svgVectorDb")}
              </text>
              <rect
                x="300"
                y="120"
                width="80"
                height="40"
                rx="4"
                fill="#3525cd"
              />
              <text
                x="340"
                y="145"
                textAnchor="middle"
                fill="white"
                fontSize="10"
              >
                {t("pipeline.svgInsights")}
              </text>
              <path
                className="rudix-svg-flow-line"
                d="M100 140 H130 V40 H160"
                stroke="#3525cd"
                strokeWidth="2"
              />
              <path
                className="rudix-svg-flow-line"
                d="M100 140 H130 V240 H160"
                stroke="#3525cd"
                strokeWidth="2"
              />
              <path
                className="rudix-svg-flow-line"
                d="M240 40 H270 V140 H300"
                stroke="#3525cd"
                strokeWidth="2"
              />
              <path
                className="rudix-svg-flow-line"
                d="M240 240 H270 V140 H300"
                stroke="#3525cd"
                strokeWidth="2"
              />
            </svg>
            <div className="mt-8 grid grid-cols-2 gap-4">
              <div className="rounded-lg border border-white/10 bg-[#0A0A0F] p-3">
                <p className="text-[10px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
                  {t("pipeline.metricLatency")}
                </p>
                <p className="font-mono text-[14px] text-[#3525cd]">124ms</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-[#0A0A0F] p-3">
                <p className="text-[10px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
                  {t("pipeline.metricAccuracy")}
                </p>
                <p className="font-mono text-[14px] text-[#108548]">99.8%</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function ResearchExampleQueriesSection() {
  const t = useTranslations("public.research");
  const examples = [
    {
      icon: "help",
      question: t("exampleQueries.q1"),
      answer: t("exampleQueries.a1"),
    },
    {
      icon: "security",
      question: t("exampleQueries.q2"),
      answer: t("exampleQueries.a2"),
    },
    {
      icon: "compare",
      question: t("exampleQueries.q3"),
      answer: t("exampleQueries.a3"),
    },
    {
      icon: "find_in_page",
      question: t("exampleQueries.q4"),
      answer: t("exampleQueries.a4"),
    },
  ];

  return (
    <section
      aria-labelledby="research-queries-title"
      className="bg-white py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="research-queries-title"
            className="mb-4 text-[30px] leading-[38px] font-semibold text-[#0A0A0F]"
          >
            {t("exampleQueries.heading")}
          </h2>
          <p className="text-base leading-6 text-[#464555]">
            {t("exampleQueries.description")}
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-8 md:grid-cols-2">
          {examples.map((e) => (
            <li
              key={e.question}
              className="rudix-landing-glass flex items-start gap-4 rounded-2xl p-8 transition hover:border-[#3525cd]"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#e2dfff]">
                <Sym name={e.icon} className="text-[#3525cd]" />
              </div>
              <div>
                <p className="mb-2 text-[24px] leading-8 font-semibold text-[#3525cd]">
                  {e.question}
                </p>
                <p className="text-base leading-6 text-[#464555]">{e.answer}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function ResearchFinalCtaSection({
  demoHref,
  contactHref,
}: {
  demoHref: string;
  contactHref: string;
}) {
  const t = useTranslations("public.research");

  return (
    <section aria-labelledby="research-cta-title" className="mb-24 py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="relative overflow-hidden rounded-[40px] bg-[#3525cd] p-12 text-center text-white md:p-24">
          <div
            aria-hidden="true"
            className="rudix-research-dot-bg pointer-events-none absolute inset-0 opacity-10"
          />
          <div className="relative z-10 mx-auto max-w-2xl">
            <h2
              id="research-cta-title"
              className="mb-8 text-4xl leading-tight font-bold tracking-tight lg:text-[48px] lg:leading-[56px]"
            >
              {t("cta.heading")}
            </h2>
            <p className="mb-12 text-lg leading-7 opacity-90">
              {t("cta.description")}
            </p>
            <div className="flex flex-col justify-center gap-6 sm:flex-row">
              <PublicActionLink
                href={demoHref}
                className="rounded-2xl bg-white px-10 py-5 font-bold text-[#3525cd] transition hover:scale-105 active:scale-95"
              >
                {t("cta.primaryCta")}
              </PublicActionLink>
              <PublicActionLink
                href={contactHref}
                className="rounded-2xl border-2 border-white px-10 py-5 font-bold text-white transition hover:bg-white/10 active:scale-95"
              >
                {t("cta.secondaryCta")}
              </PublicActionLink>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function ResearchSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <ResearchBreadcrumb />
      <ResearchHeroSection demoHref={links.requestDemo} docsHref={links.docs} />
      <ResearchProblemSection />
      <ResearchDocumentSourcesSection />
      <ResearchPipelineSection />
      <ResearchExampleQueriesSection />
      <ResearchFinalCtaSection
        demoHref={links.startTrial}
        contactHref={links.requestDemo}
      />
    </>
  );
}
