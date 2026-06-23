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

function SalesBreadcrumb() {
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
            {t("sales.breadcrumb")}
          </li>
        </ol>
      </nav>
    </div>
  );
}

// ── hero ──────────────────────────────────────────────────────────────────────

function SalesHeroSection({
  trialHref,
  demoHref,
}: {
  trialHref: string;
  demoHref: string;
}) {
  const t = useTranslations("public.sales");

  return (
    <section
      aria-labelledby="sales-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="z-10">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-[#e2dfff] px-3 py-1 text-[#3525cd]">
            <Sym name="verified" className="text-[18px]" />
            <span className="text-[12px] font-semibold tracking-[0.05em] uppercase">
              {t("hero.badge")}
            </span>
          </div>
          <h1
            id="sales-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            {t("hero.heading")}
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            {t("hero.description")}
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={trialHref}
              className="inline-flex items-center gap-3 rounded-xl bg-[#3525cd] px-8 py-4 text-[24px] font-semibold text-white shadow-lg shadow-[#3525cd]/20 transition hover:shadow-xl active:scale-95"
            >
              {t("hero.primaryCta")}
              <Sym name="arrow_forward" />
            </PublicActionLink>
            <PublicActionLink
              href={demoHref}
              className="rounded-xl border border-[#c7c4d8] bg-[#faf9ff] px-8 py-4 text-[24px] font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3] active:scale-95"
            >
              {t("hero.secondaryCta")}
            </PublicActionLink>
          </div>
        </div>

        <div className="relative">
          <div
            aria-hidden="true"
            className="absolute -top-20 -right-20 h-80 w-80 rounded-full bg-[#3525cd]/10 blur-[100px]"
          />
          <div
            aria-hidden="true"
            className="absolute -bottom-20 -left-20 h-64 w-64 rounded-full bg-[#00542a]/5 blur-[80px]"
          />

          <div className="rudix-landing-glass relative z-10 rounded-2xl border border-[#c7c4d8]/30 p-8 shadow-2xl">
            <div className="mb-6 flex items-center justify-between">
              <div className="flex gap-2">
                <span className="h-3 w-3 rounded-full bg-red-400" />
                <span className="h-3 w-3 rounded-full bg-yellow-400" />
                <span className="h-3 w-3 rounded-full bg-green-400" />
              </div>
              <span className="font-mono text-[12px] text-[#464555]">
                rudix-query-v4.2
              </span>
            </div>

            <div className="mb-6 rounded-xl bg-[#1F1E24] p-6">
              <div className="mb-4 flex items-center gap-3 text-[#c3c0ff]">
                <Sym name="search" />
                <span className="font-mono text-[13px]">
                  {t("hero.mockQuestion")}
                </span>
              </div>
              <div className="mb-4 h-px bg-white/10" />
              <p className="mb-4 text-sm leading-6 text-[#faf9ff]">
                {t("hero.mockAnswerTitle")}
                <br />
                1.{" "}
                <span className="text-[#c3c0ff]">
                  {t("hero.mockAnswer1Label")}
                </span>{" "}
                {t("hero.mockAnswer1Body")}
                <br />
                2.{" "}
                <span className="text-[#c3c0ff]">
                  {t("hero.mockAnswer2Label")}
                </span>{" "}
                {t("hero.mockAnswer2Body")}
                <br />
                3.{" "}
                <span className="text-[#c3c0ff]">
                  {t("hero.mockAnswer3Label")}
                </span>{" "}
                {t("hero.mockAnswer3Body")}
              </p>
              <div className="flex flex-wrap gap-2">
                <span className="rounded bg-white/10 px-2 py-1 font-mono text-[10px] text-[#faf9ff]">
                  {t("hero.mockTag1")}
                </span>
                <span className="rounded bg-white/10 px-2 py-1 font-mono text-[10px] text-[#faf9ff]">
                  {t("hero.mockTag2")}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-4 text-[12px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
              <span className="flex items-center gap-1">
                <Sym name="sync" className="text-[16px]" />{" "}
                {t("hero.mockStatus1")}
              </span>
              <span className="flex items-center gap-1">
                <Sym
                  name="check_circle"
                  className="text-[16px] text-[#108548]"
                />{" "}
                {t("hero.mockStatus2")}
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── problem ───────────────────────────────────────────────────────────────────

function SalesProblemSection() {
  const t = useTranslations("public.sales");

  const problems = [
    {
      icon: "search_off",
      iconBg: "bg-red-50 text-[#ba1a1a]",
      title: t("problems.lostCaseStudiesTitle"),
      body: t("problems.lostCaseStudiesBody"),
    },
    {
      icon: "history",
      iconBg: "bg-orange-50 text-[#E24329]",
      title: t("problems.outdatedPricingTitle"),
      body: t("problems.outdatedPricingBody"),
    },
    {
      icon: "swords",
      iconBg: "bg-[#3525cd]/5 text-[#3525cd]",
      title: t("problems.battlecardFrictionTitle"),
      body: t("problems.battlecardFrictionBody"),
    },
  ];

  return (
    <section aria-labelledby="sales-problem-title" className="bg-white py-24">
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="mb-16 text-center">
          <h2
            id="sales-problem-title"
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
              className="rounded-xl border border-[#c7c4d8]/30 bg-white p-8 shadow-sm transition hover:border-[#3525cd]/40"
            >
              <div
                className={`mb-6 flex h-12 w-12 items-center justify-center rounded-lg ${p.iconBg}`}
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

function SalesDocumentSourcesSection() {
  const t = useTranslations("public.sales");

  const sources = [
    { icon: "description", label: t("documentSources.productSpecs") },
    { icon: "auto_stories", label: t("documentSources.caseStudies") },
    { icon: "analytics", label: t("documentSources.rfpTemplates") },
    { icon: "payments", label: t("documentSources.pricingSheets") },
    { icon: "military_tech", label: t("documentSources.battlecards") },
    { icon: "handshake", label: t("documentSources.proposalDecks") },
  ];

  return (
    <section
      aria-labelledby="sales-doc-sources-title"
      className="overflow-hidden bg-[#faf9ff] py-24"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="flex flex-col items-center gap-16 lg:flex-row">
          <div className="lg:w-1/2">
            <h2
              id="sales-doc-sources-title"
              className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
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
                  className="flex items-center gap-3 rounded-lg border border-[#c7c4d8]/20 bg-[#eeedf3] p-4"
                >
                  <Sym name={s.icon} className="text-[#3525cd]" />
                  <span className="font-semibold text-[#1a1b20]">
                    {s.label}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="grid w-full grid-cols-2 gap-6 lg:w-1/2">
            <div className="space-y-6">
              <div className="relative h-48 overflow-hidden rounded-2xl shadow-lg">
                <Image
                  src="/images/solutions/sales/collateral.jpg"
                  alt="Professional sales collateral and technical product brochures"
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
              </div>
              <div className="relative h-64 overflow-hidden rounded-2xl shadow-lg">
                <Image
                  src="/images/solutions/sales/workspace.jpg"
                  alt="Sales representative working on a laptop with sales enablement tools"
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
              </div>
            </div>
            <div className="space-y-6 pt-12">
              <div className="relative h-64 overflow-hidden rounded-2xl shadow-lg">
                <Image
                  src="/images/solutions/sales/team-meeting.jpg"
                  alt="Enterprise account executives collaborating in a sales strategy meeting"
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
              </div>
              <div className="relative h-48 overflow-hidden rounded-2xl shadow-lg">
                <Image
                  src="/images/solutions/sales/pricing.jpg"
                  alt="Pricing sheet and contract documentation for enterprise sales"
                  fill
                  className="object-cover"
                  sizes="(max-width: 1024px) 50vw, 25vw"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── example queries ───────────────────────────────────────────────────────────

function SalesExampleQueriesSection() {
  const t = useTranslations("public.sales");

  return (
    <section
      aria-labelledby="sales-queries-title"
      className="bg-[#0A0A0F] py-24 text-[#faf9ff]"
    >
      <div className="mx-auto max-w-[1440px] px-10">
        <div className="grid items-center gap-16 lg:grid-cols-2">
          <div>
            <h2
              id="sales-queries-title"
              className="mb-6 text-4xl leading-tight font-bold tracking-tight lg:text-[48px] lg:leading-[56px]"
            >
              {t("queries.heading")}
            </h2>
            <p className="mb-10 text-lg leading-7 text-[#47464d]">
              {t("queries.description")}
            </p>
            <ul className="space-y-4">
              <li className="group cursor-default rounded-xl border border-white/10 bg-white/5 p-5 transition hover:bg-white/10">
                <p className="text-base leading-6 text-[#faf9ff] transition group-hover:text-[#c3c0ff]">
                  {t("queries.q1")}
                </p>
              </li>
              <li className="rounded-xl border border-[#3525cd]/50 bg-white/10 p-5">
                <p className="mb-4 text-base leading-6 text-[#c3c0ff]">
                  {t("queries.q2")}
                </p>
                <div className="border-l-2 border-[#c3c0ff] pl-4 text-sm text-[#faf9ff]/80 italic">
                  {t("queries.q2Answer")}
                </div>
              </li>
              <li className="group cursor-default rounded-xl border border-white/10 bg-white/5 p-5 transition hover:bg-white/10">
                <p className="text-base leading-6 text-[#faf9ff] transition group-hover:text-[#c3c0ff]">
                  {t("queries.q3")}
                </p>
              </li>
            </ul>
          </div>

          {/* animated diagram */}
          <div className="relative flex justify-center" aria-hidden="true">
            <div className="relative aspect-square w-full max-w-md">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="flex h-48 w-48 animate-pulse items-center justify-center rounded-full bg-[#3525cd]/20">
                  <div className="flex h-32 w-32 items-center justify-center rounded-full bg-[#3525cd]/40">
                    <Sym name="psychology" className="text-5xl text-white" />
                  </div>
                </div>
              </div>
              <div className="absolute top-0 left-0 rounded-lg border border-white/10 bg-white/5 p-4 backdrop-blur-md">
                <div className="flex items-center gap-2 text-sm">
                  <Sym name="folder_zip" className="text-base" />{" "}
                  {t("queries.knowledgeBase")}
                </div>
              </div>
              <div className="absolute right-0 bottom-10 rounded-lg border border-white/10 bg-white/5 p-4 backdrop-blur-md">
                <div className="flex items-center gap-2 text-sm">
                  <Sym name="record_voice_over" className="text-base" />{" "}
                  {t("queries.aeQuery")}
                </div>
              </div>
              <div className="absolute top-20 right-10 rounded-lg border border-white/10 bg-white/5 p-4 backdrop-blur-md">
                <div className="flex items-center gap-2 text-sm">
                  <Sym name="verified_user" className="text-base" />{" "}
                  {t("queries.securityDocs")}
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

function SalesFinalCtaSection({
  demoHref,
  pricingHref,
}: {
  demoHref: string;
  pricingHref: string;
}) {
  const t = useTranslations("public.sales");

  return (
    <section
      aria-labelledby="sales-cta-title"
      className="relative overflow-hidden bg-[#faf9ff] py-32"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-1/2 h-[400px] w-[800px] -translate-x-1/2 -translate-y-1/2 -rotate-12 rounded-[100%] bg-[#3525cd]/5 blur-[120px]"
      />
      <div className="relative z-10 mx-auto max-w-[1440px] px-10 text-center">
        <h2
          id="sales-cta-title"
          className="mb-8 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
        >
          {t("cta.heading")}
        </h2>
        <p className="mx-auto mb-12 max-w-2xl text-lg leading-7 text-[#464555]">
          {t("cta.description")}
        </p>
        <div className="flex flex-col justify-center gap-4 sm:flex-row">
          <PublicActionLink
            href={demoHref}
            className="rounded-xl bg-[#3525cd] px-10 py-5 text-[24px] font-semibold text-white shadow-lg transition hover:shadow-xl active:scale-95"
          >
            {t("cta.primaryCta")}
          </PublicActionLink>
          <PublicActionLink
            href={pricingHref}
            className="rounded-xl border border-[#c7c4d8] bg-white px-10 py-5 text-[24px] font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3] active:scale-95"
          >
            {t("cta.secondaryCta")}
          </PublicActionLink>
        </div>
      </div>
    </section>
  );
}

// ── page export ───────────────────────────────────────────────────────────────

export function SalesSolutionPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SalesBreadcrumb />
      <SalesHeroSection
        trialHref={links.startTrial}
        demoHref={links.requestDemo}
      />
      <SalesProblemSection />
      <SalesDocumentSourcesSection />
      <SalesExampleQueriesSection />
      <SalesFinalCtaSection
        demoHref={links.requestDemo}
        pricingHref={links.pricing}
      />
    </>
  );
}
