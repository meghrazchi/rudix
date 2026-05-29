"use client";

import { useEffect, useRef, useState } from "react";

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

function InternalKnowledgeBreadcrumb() {
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
          Internal Knowledge
        </li>
      </ol>
    </nav>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function InternalKnowledgeHeroSection({
  trialHref,
  demoHref,
}: {
  trialHref: string;
  demoHref: string;
}) {
  return (
    <section
      aria-labelledby="ik-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div>
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold uppercase tracking-[0.05em] text-[#3323cc]">
            Internal Knowledge Assistant
          </span>
          <h1
            id="ik-hero-title"
            className="mb-6 text-4xl font-bold leading-tight tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            Your team's knowledge,{" "}
            <span className="text-[#3525cd]">instantly accessible.</span>
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            Stop hunting through outdated PDFs and buried Slack threads. Rudix
            indexes your entire organizational brain to provide verified,
            instant answers to any internal query.
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={trialHref}
              className="rounded-xl bg-[#3525cd] px-8 py-4 text-lg font-semibold text-white shadow-lg transition hover:shadow-xl active:scale-95"
            >
              Get Started
            </PublicActionLink>
            <PublicActionLink
              href={demoHref}
              className="rounded-xl border border-[#777587] px-8 py-4 text-lg font-semibold text-[#1a1b20] transition hover:bg-[#f4f3f9] active:scale-95"
            >
              Watch Demo
            </PublicActionLink>
          </div>
        </div>

        <div className="relative">
          <div aria-hidden="true" className="absolute -top-10 -right-10 -z-10 h-64 w-64 animate-pulse rounded-full bg-[#3525cd]/10 blur-3xl" />
          <div aria-hidden="true" className="absolute -bottom-10 -left-10 -z-10 h-48 w-48 animate-pulse rounded-full bg-[#75db94]/20 blur-3xl [animation-delay:2s]" />

          <div className="rudix-animate-float rudix-landing-glass relative z-10 rounded-2xl border border-white/30 p-6 shadow-2xl">
            <div className="mb-6 flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-[#ba1a1a]" />
              <span className="h-3 w-3 rounded-full bg-[#E24329]" />
              <span className="h-3 w-3 rounded-full bg-[#108548]" />
            </div>

            <div className="space-y-4">
              {/* user message */}
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-tr-none bg-[#4f46e5] p-4 text-sm text-[#dad7ff]">
                  "What is our policy on remote work stipends for international
                  employees?"
                </div>
              </div>

              {/* AI response */}
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#3525cd] shadow-md">
                  <Sym name="smart_toy" className="text-sm text-white" />
                </div>
                <div className="max-w-[85%] rounded-2xl rounded-tl-none border border-[#c7c4d8]/30 bg-[#f4f3f9] p-4">
                  <p className="mb-3 text-sm text-[#1a1b20]">
                    Based on the{" "}
                    <strong>Global Employee Handbook (2024)</strong>:
                  </p>
                  <ul className="list-disc space-y-1.5 pl-4 text-xs text-[#464555]">
                    <li>Full-time remote workers are eligible for a $500 initial setup stipend.</li>
                    <li>An annual $200 recurring tech refresh budget applies.</li>
                    <li>International receipts must be converted to USD using the OANDA rate at date of purchase.</li>
                  </ul>
                  <div className="mt-4 flex items-center justify-between border-t border-[#c7c4d8]/50 pt-3">
                    <span className="flex items-center gap-1 text-[10px] text-[#3525cd]">
                      <Sym name="verified" className="text-[12px]" />
                      Source: SOP-HR-042.pdf
                    </span>
                    <div className="flex gap-2">
                      <Sym name="thumb_up" className="cursor-pointer text-sm text-[#777587] hover:text-[#3525cd]" />
                      <Sym name="thumb_down" className="cursor-pointer text-sm text-[#777587] hover:text-[#3525cd]" />
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

// ── problem ───────────────────────────────────────────────────────────────────

function InternalKnowledgeProblemSection() {
  const problems = [
    {
      icon: "cloud_off",
      iconBg: "bg-[#ffdad6] text-[#ba1a1a]",
      title: "Information Silos",
      body: "Critical context is trapped in private DMs, local drives, and individual heads. Rudix brings it into the collective light.",
    },
    {
      icon: "person_add",
      iconBg: "bg-[#e2dee6] text-[#47464d]",
      title: "Onboarding Friction",
      body: 'New hires spend weeks asking "where is this?" Rudix acts as a 24/7 mentor, giving instant answers on day one.',
    },
    {
      icon: "forum",
      iconBg: "bg-[#e2dfff] text-[#3323cc]",
      title: "Slack Overload",
      body: 'Prevent subject matter experts from answering the same "How do I…" questions repeatedly, freeing them for high-value work.',
    },
  ];

  return (
    <section aria-labelledby="ik-problem-title" className="bg-[#f4f3f9] py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="ik-problem-title"
            className="mb-4 text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
          >
            The high cost of hidden knowledge
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            Inefficiency grows as teams scale. Rudix solves the three core
            pillars of internal friction.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-8 md:grid-cols-3">
          {problems.map((p) => (
            <li
              key={p.title}
              className="group rounded-2xl border border-[#c7c4d8]/30 bg-white p-8 shadow-sm transition hover:shadow-md"
            >
              <div
                className={`mb-6 flex h-12 w-12 items-center justify-center rounded-xl transition group-hover:scale-110 ${p.iconBg}`}
              >
                <Sym name={p.icon} />
              </div>
              <h3 className="mb-3 text-[24px] font-semibold leading-8 text-[#1a1b20]">
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

// ── document support ──────────────────────────────────────────────────────────

function InternalKnowledgeDocumentSection() {
  const docTypes = [
    { icon: "description", label: "SOPs", desc: "Standard Operating Procedures for all departments." },
    { icon: "menu_book", label: "Handbooks", desc: "Culture, benefits, and administrative guides." },
    { icon: "play_circle", label: "Playbooks", desc: "Sales, marketing, and engineering strategies." },
    { icon: "school", label: "Manuals", desc: "Technical documentation and training kits." },
  ];

  const features = [
    "Preserves original citations and links",
    "Automatic re-indexing on file updates",
    "Strict data permission mirroring",
  ];

  return (
    <section aria-labelledby="ik-doc-title" className="bg-white py-24">
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-20 px-10 lg:grid-cols-2">
        <div className="order-2 grid grid-cols-2 gap-4 lg:order-1">
          {docTypes.map((d) => (
            <div
              key={d.label}
              className="rounded-2xl border border-[#c7c4d8]/50 bg-[#e8e7ed] p-6"
            >
              <Sym name={d.icon} className="mb-4 text-[#3525cd]" />
              <h4 className="mb-1 font-bold text-[#1a1b20]">{d.label}</h4>
              <p className="text-xs text-[#464555]">{d.desc}</p>
            </div>
          ))}
        </div>

        <div className="order-1 lg:order-2">
          <h2
            id="ik-doc-title"
            className="mb-6 text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
          >
            One Brain, Every Document
          </h2>
          <p className="mb-8 text-lg leading-7 text-[#464555]">
            Rudix isn't limited to simple text files. Our high-fidelity RAG
            engine ingests complex PDFs, Notion pages, Google Docs, and
            structured JSON to build a multi-modal knowledge graph.
          </p>
          <ul className="space-y-4">
            {features.map((f) => (
              <li key={f} className="flex items-center gap-3 text-base leading-6">
                <Sym name="check_circle" className="shrink-0 text-[#108548]" />
                <span className="font-semibold text-[#1a1b20]">{f}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

// ── how it works ──────────────────────────────────────────────────────────────

const CODE_CONTENT = `{
  "query": "What is the budget approval process?",
  "embeddings": "vector_f32[1536]",
  "retrieval": [
    "DOC_ID_091: Finance_Flow_v2.pdf",
    "DOC_ID_212: Manager_Onboarding.notion"
  ],
  "output": "Budget approvals >$5k require VP sign-off..."
}`;

function InternalKnowledgeHowItWorksSection() {
  const steps = [
    { n: "01", icon: "upload_file", label: "Upload SOPs", desc: "Drag and drop your unstructured documents." },
    { n: "02", icon: "database", label: "Vector Index", desc: "Automatic semantic embedding and storage." },
    { n: "03", icon: "chat_paste_go", label: "Ask Anything", desc: "Natural language queries via web or Slack." },
    { n: "04", icon: "fact_check", label: "Verify & Cite", desc: "Answer delivered with verifiable sources." },
  ];

  const cardRef = useRef<HTMLDivElement>(null);
  const indexRef = useRef(0);
  const [typedText, setTypedText] = useState("");
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setStarted(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setStarted(true);
          observer.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!started) return;
    indexRef.current = 0;
    setTypedText("");
    const id = setInterval(() => {
      indexRef.current += 1;
      setTypedText(CODE_CONTENT.slice(0, indexRef.current));
      if (indexRef.current >= CODE_CONTENT.length) clearInterval(id);
    }, 15);
    return () => clearInterval(id);
  }, [started]);

  return (
    <section aria-labelledby="ik-flow-title" className="overflow-hidden bg-[#0A0A0F] py-24 text-[#faf9ff]">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-20 text-center">
          <h2
            id="ik-flow-title"
            className="mb-4 text-[30px] font-semibold leading-[38px] text-white"
          >
            The Rudix Flow
          </h2>
          <p className="text-base leading-6 text-[#464555]">
            Enterprise-grade infrastructure, abstracted for simplicity.
          </p>
        </div>

        <div className="relative">
          {/* animated gradient connector */}
          <div
            aria-hidden="true"
            className="absolute top-10 left-0 hidden h-0.5 w-full overflow-hidden bg-gradient-to-r from-[#dad7ff]/20 via-[#3525cd]/50 to-[#dad7ff]/20 lg:block"
            style={{ filter: "drop-shadow(0 0 8px rgba(79,70,229,0.4))" }}
          >
            <div className="rudix-data-pulse-line" />
          </div>

          <ol className="relative z-10 grid grid-cols-1 gap-8 lg:grid-cols-4">
            {steps.map((s) => (
              <li key={s.n} className="group text-center">
                <div className="relative mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl border border-white/10 bg-white/10 transition duration-500 group-hover:scale-110 group-hover:border-[#3525cd] group-hover:shadow-[0_0_20px_rgba(79,70,229,0.3)]">
                  <Sym name={s.icon} className="text-3xl text-[#3525cd]" />
                  <span className="absolute -right-2 -bottom-2 rounded bg-[#3525cd] px-2 py-0.5 text-[10px] font-bold text-white shadow-lg">
                    {s.n}
                  </span>
                </div>
                <h3 className="mb-2 text-lg font-bold text-white transition group-hover:text-[#c3c0ff]">
                  {s.label}
                </h3>
                <p className="text-sm leading-5 text-[#464555]">{s.desc}</p>
              </li>
            ))}
          </ol>
        </div>

        {/* technical card with typing animation */}
        <div ref={cardRef} className="mt-20 rounded-2xl border border-white/10 bg-[#1F1E24] p-8 transition duration-700 hover:border-[#3525cd]/50">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
              <span className="font-mono text-xs text-[#c3c0ff]">
                RAG ENGINE STATUS: ACTIVE
              </span>
            </div>
            <span className="font-mono text-xs text-[#464555]">latency: 240ms</span>
          </div>
          <pre className="overflow-x-auto font-mono text-[13px] leading-5 text-[#e2dfff]">
            <code>{typedText || " "}</code>
            {typedText.length < CODE_CONTENT.length && (
              <span aria-hidden="true" className="rudix-cursor-blink text-[#e2dfff]" />
            )}
          </pre>
        </div>
      </div>
    </section>
  );
}

// ── example questions ─────────────────────────────────────────────────────────

function InternalKnowledgeExampleQueriesSection() {
  const questions = [
    "What is the budget approval process?",
    "Where is the brand style guide?",
    "How do I request temporary VPN access?",
    "What's our policy on working from abroad?",
  ];

  return (
    <section aria-labelledby="ik-queries-title" className="bg-white py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <h2
          id="ik-queries-title"
          className="mb-12 text-[30px] font-semibold leading-[38px] text-[#0A0A0F]"
        >
          Ask Rudix Anything
        </h2>
        <ul className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {questions.map((q) => (
            <li
              key={q}
              className="group flex cursor-default items-center justify-between rounded-xl border border-[#c7c4d8]/30 bg-[#eeedf3] p-6 transition hover:bg-[#e8e7ed]"
            >
              <span className="font-semibold text-[#0A0A0F]">"{q}"</span>
              <Sym
                name="arrow_forward"
                className="shrink-0 text-[#3525cd] transition group-hover:translate-x-1"
              />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── final cta ─────────────────────────────────────────────────────────────────

function InternalKnowledgeFinalCtaSection({
  demoHref,
  pricingHref,
}: {
  demoHref: string;
  pricingHref: string;
}) {
  return (
    <section aria-labelledby="ik-cta-title" className="relative overflow-hidden bg-[#faf9ff] py-24">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-1/2 -z-0 h-[400px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-[100%] bg-[#e2dfff]/30 blur-[120px]"
      />
      <div className="relative z-10 mx-auto max-w-4xl px-10">
        <div className="rounded-3xl bg-[#3525cd] p-12 text-center lg:p-20">
          <h2
            id="ik-cta-title"
            className="mb-6 text-4xl font-bold leading-tight tracking-tight text-white lg:text-[48px] lg:leading-[56px]"
          >
            Stop searching. Start knowing.
          </h2>
          <p className="mb-10 text-lg leading-7 text-[#dad7ff] opacity-90">
            Transform your internal documentation from a static library into a
            dynamic conversation. Deploy Rudix in under 30 minutes.
          </p>
          <div className="flex flex-col justify-center gap-4 sm:flex-row">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-white px-8 py-4 font-bold text-lg text-[#3525cd] transition hover:bg-[#e2dfff] active:scale-95"
            >
              Speak to us
            </PublicActionLink>
            <PublicActionLink
              href={pricingHref}
              className="rounded-xl border border-white/20 bg-white/10 px-8 py-4 font-bold text-lg text-white transition hover:bg-white/20 active:scale-95"
            >
              View Pricing
            </PublicActionLink>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function InternalKnowledgeSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <InternalKnowledgeBreadcrumb />
      <InternalKnowledgeHeroSection trialHref={links.startTrial} demoHref={links.requestDemo} />
      <InternalKnowledgeProblemSection />
      <InternalKnowledgeDocumentSection />
      <InternalKnowledgeHowItWorksSection />
      <InternalKnowledgeExampleQueriesSection />
      <InternalKnowledgeFinalCtaSection demoHref={links.requestDemo} pricingHref={links.pricing} />
    </>
  );
}
