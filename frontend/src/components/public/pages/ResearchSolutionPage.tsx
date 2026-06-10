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
          {t("research.breadcrumb")}
        </li>
      </ol>
    </nav>
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
            The research friction point.
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Manual processing of technical reports is the bottleneck of modern
            enterprise strategy.
          </p>
        </div>

        <ul className="grid auto-rows-auto grid-cols-1 gap-6 md:grid-cols-12">
          <li className="rudix-landing-glass group relative overflow-hidden rounded-2xl p-10 md:col-span-8">
            <div className="relative z-10">
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                Information Overload
              </h3>
              <p className="max-w-lg text-base leading-6 text-[#464555]">
                Technical teams are drowning in 500+ page PDFs. Sifting through
                noise to find specific implementation risks shouldn&apos;t take
                days.
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
                Manual Summarization
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                Subjective, slow, and prone to human error when handling complex
                data points.
              </p>
            </div>
          </li>

          <li className="rudix-landing-glass flex flex-col gap-4 rounded-2xl p-10 md:col-span-4">
            <Sym name="link" className="text-4xl text-[#3525cd]" />
            <h3 className="text-[24px] leading-8 font-semibold text-[#1a1b20]">
              Lack of Citations
            </h3>
            <p className="text-base leading-6 text-[#464555]">
              Insights are useless without lineage. We solve the trust problem
              in generative AI.
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
                Technical Fragmentation
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                Data spread across siloed repositories makes cross-document
                synthesis nearly impossible for traditional tools.
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
  const sources = [
    {
      icon: "article",
      label: "Whitepapers",
      desc: "Technical specs and protocols",
    },
    {
      icon: "query_stats",
      label: "Market Research",
      desc: "Trends and TAM data",
    },
    {
      icon: "lab_profile",
      label: "Analyst Reports",
      desc: "Gartner, Forrester, etc.",
    },
    {
      icon: "science",
      label: "Technical Papers",
      desc: "Academic and R&D docs",
    },
    {
      icon: "account_tree",
      label: "Strategy Docs",
      desc: "Internal vision and roadmaps",
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
              Ingest everything. Analyze anything.
            </h2>
            <p className="text-base leading-6 text-[#464555]">
              Our high-fidelity parser handles high-density documents that break
              standard LLMs.
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
  const steps = [
    {
      n: "1",
      title: "Semantic Chunking",
      body: "Unlike basic tools, we preserve table structures and image captions for context-aware extraction.",
    },
    {
      n: "2",
      title: "Vector Indexing",
      body: "Multi-modal embeddings map data into high-dimensional space for ultra-accurate retrieval.",
    },
    {
      n: "3",
      title: "Verifiable Generation",
      body: "Every claim is linked back to a specific page and paragraph in the original source.",
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
              The High-Fidelity Retrieval Pipeline
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
                PDF Source
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
                Embeddings
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
                Vector DB
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
                Insights
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
                  Latency
                </p>
                <p className="font-mono text-[14px] text-[#3525cd]">124ms</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-[#0A0A0F] p-3">
                <p className="text-[10px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
                  Accuracy
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
  const examples = [
    {
      icon: "help",
      question: "What are the core market projections for 2025?",
      answer:
        "Synthesizes data across multiple market reports to provide a consensus view with outliers highlighted.",
    },
    {
      icon: "security",
      question: "Which sources discuss implementation risks?",
      answer:
        "Aggregates risk assessments from technical whitepapers, mapping potential failure modes in a single view.",
    },
    {
      icon: "compare",
      question: "How do these two analyst reports differ on cloud adoption?",
      answer:
        "Compares and contrasts claims across documents side by side, surfacing verbatim quotes from each source.",
    },
    {
      icon: "find_in_page",
      question: "Which papers mention the term 'model drift'?",
      answer:
        "Performs source discovery across your entire corpus, returning every matching passage with its citation.",
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
            Query your corpus.
          </h2>
          <p className="text-base leading-6 text-[#464555]">
            Stop searching. Start asking questions that matter.
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
