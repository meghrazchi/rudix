"use client";

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

function LegalBreadcrumb() {
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
            {t("legal.breadcrumb")}
          </li>
        </ol>
      </nav>
    </div>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function LegalHeroSection({ demoHref }: { demoHref: string }) {
  const t = useTranslations("public.legal");

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
              {t("hero.badge")}
            </span>
          </div>
          <h1
            id="legal-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#1a1b20] lg:text-[48px] lg:leading-[56px]"
          >
            {t("hero.heading")}
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            {t("hero.description")}
          </p>
          <PublicActionLink
            href={demoHref}
            className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-8 py-4 text-lg font-bold text-white shadow-lg shadow-[#3525cd]/20 transition hover:opacity-90 active:scale-95"
          >
            {t("hero.primaryCta")}
            <Sym name="arrow_forward" />
          </PublicActionLink>
        </div>

        <div className="relative lg:block">
          <div className="rudix-landing-glass relative rounded-2xl border border-[#c7c4d8]/50 p-6 shadow-[0_0_20px_rgba(53,37,205,0.1)]">
            <div className="mb-4 flex items-center gap-4 rounded-lg border border-white/10 bg-[#0A0A0F] p-4">
              <Sym name="search" className="text-[#c3c0ff]" />
              <span className="text-sm text-[#c3c0ff]/60 italic">
                {t("hero.queryExample")}
              </span>
            </div>
            <div className="rounded-lg bg-[#eeedf3] p-4">
              <p className="mb-3 text-base leading-relaxed text-[#1a1b20]">
                {t("hero.answerText")}
              </p>
              <div className="flex flex-wrap gap-2">
                <span className="rounded border-l-2 border-[#3525cd] bg-[#3525cd]/5 px-2 py-1 text-[12px] font-semibold text-[#3525cd]">
                  {t("hero.citation1")}
                </span>
                <span className="rounded border-l-2 border-[#3525cd] bg-[#3525cd]/5 px-2 py-1 text-[12px] font-semibold text-[#3525cd]">
                  {t("hero.citation2")}
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
  const t = useTranslations("public.legal");

  const problems = [
    {
      icon: "description",
      iconBg: "bg-[#ba1a1a]/10 text-[#ba1a1a]",
      title: t("problems.longContractsTitle"),
      body: t("problems.longContractsBody"),
    },
    {
      icon: "repeat",
      iconBg: "bg-[#3525cd]/10 text-[#3525cd]",
      title: t("problems.repeatedQuestionsTitle"),
      body: t("problems.repeatedQuestionsBody"),
    },
    {
      icon: "event_busy",
      iconBg: "bg-[#E24329]/10 text-[#E24329]",
      title: t("problems.missedDeadlinesTitle"),
      body: t("problems.missedDeadlinesBody"),
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
            {t("problems.heading")}
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            {t("problems.description")}
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
  const t = useTranslations("public.legal");

  const sources = [
    { icon: "groups", label: t("documentSources.customerContracts") },
    { icon: "shopping_cart", label: t("documentSources.vendorAgreements") },
    { icon: "lock", label: t("documentSources.ndas") },
    { icon: "gavel", label: t("documentSources.dpas") },
    { icon: "verified_user", label: t("documentSources.termsOfService") },
    { icon: "library_books", label: t("documentSources.legalGuidance") },
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
              {t("documentSources.heading")}
            </h2>
            <p className="mb-8 text-lg leading-7 text-[#464555]">
              {t("documentSources.description")}
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
                  {t("documentSources.instantIngestion")}
                </h4>
                <p className="text-[#c3c0ff]/70">
                  {t("documentSources.ingestionDesc")}
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
  const t = useTranslations("public.legal");

  const questions = [t("questions.q1"), t("questions.q2"), t("questions.q3")];

  return (
    <section
      aria-labelledby="legal-questions-title"
      className="bg-[#0A0A0F] py-24 text-white"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-12 flex flex-col items-end justify-between gap-6 md:flex-row">
          <div>
            <span className="mb-4 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
              {t("questions.sectionLabel")}
            </span>
            <h2
              id="legal-questions-title"
              className="text-[30px] leading-[38px] font-semibold text-white"
            >
              {t("questions.heading")}
            </h2>
          </div>
          <p className="max-w-sm text-base leading-6 text-[#c3c0ff]/60">
            {t("questions.description")}
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
  const t = useTranslations("public.legal");

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
              {t("citations.heading")}
            </h2>
            <p className="mb-8 text-lg leading-7 text-[#464555]">
              {t("citations.description")}
            </p>
            <ul className="mb-8 space-y-4">
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>{t("citations.deepLinkingLabel")}</strong>{" "}
                  {t("citations.deepLinkingDetail")}
                </div>
              </li>
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>{t("citations.auditTrailsLabel")}</strong>{" "}
                  {t("citations.auditTrailsDetail")}
                </div>
              </li>
              <li className="flex items-start gap-4 text-base leading-6">
                <Sym
                  name="check_circle"
                  className="mt-0.5 shrink-0 text-[#108548]"
                />
                <div>
                  <strong>{t("citations.accessControlsLabel")}</strong>{" "}
                  {t("citations.accessControlsDetail")}
                </div>
              </li>
            </ul>

            <div className="rounded-xl border border-[#c7c4d8] bg-[#f4f3f9] p-5">
              <div className="mb-2 flex items-center gap-2 text-[#777587]">
                <Sym name="info" className="text-base" />
                <span className="text-[12px] font-semibold tracking-[0.05em] uppercase">
                  {t("citations.responsibleUseLabel")}
                </span>
              </div>
              <p className="text-sm leading-5 text-[#464555]">
                {t("citations.responsibleUseText")}
              </p>
              <PublicActionLink
                href={securityHref}
                className="mt-3 inline-flex items-center gap-1 text-[13px] font-semibold text-[#3525cd] hover:underline"
              >
                {t("citations.securityCta")}{" "}
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
  const t = useTranslations("public.legal");

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
              {t("cta.heading")}
            </h2>
            <p className="mb-10 text-xl leading-7 opacity-90">
              {t("cta.description")}
            </p>
            <div className="flex flex-col justify-center gap-4 sm:flex-row">
              <PublicActionLink
                href={trialHref}
                className="rounded-xl bg-white px-10 py-5 text-lg font-bold text-[#3525cd] transition hover:shadow-xl active:scale-95"
              >
                {t("cta.primaryCta")}
              </PublicActionLink>
              <PublicActionLink
                href={demoHref}
                className="rounded-xl border-2 border-white/30 bg-transparent px-10 py-5 text-lg font-bold text-white transition hover:bg-white/10 active:scale-95"
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
