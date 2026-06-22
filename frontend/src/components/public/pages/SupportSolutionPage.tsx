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

function SupportBreadcrumb() {
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
            {t("support.breadcrumb")}
          </li>
        </ol>
      </nav>
    </div>
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
  const t = useTranslations("public.support");

  return (
    <section
      aria-labelledby="support-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="absolute top-0 right-0 -z-10 h-full w-1/2 bg-gradient-to-l from-[#e2dfff]/20 to-transparent" />
      <div className="mx-auto grid max-w-[1440px] items-center gap-6 px-10 lg:grid-cols-2">
        <div className="z-10">
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold tracking-[0.05em] text-[#3323cc] uppercase">
            {t("hero.badge")}
          </span>
          <h1
            id="support-hero-title"
            className="mb-6 text-4xl leading-tight font-bold tracking-tight text-[#0A0A0F] lg:text-[48px] lg:leading-[56px]"
          >
            {t("hero.heading")}
          </h1>
          <p className="mb-10 max-w-xl text-lg leading-7 text-[#464555]">
            {t("hero.description")}
          </p>
          <div className="flex flex-wrap gap-4">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-8 py-4 text-sm font-semibold text-white shadow-lg transition hover:opacity-90 active:scale-95"
            >
              {t("hero.primaryCta")}
            </PublicActionLink>
            <PublicActionLink
              href={contactHref}
              className="flex items-center gap-2 rounded-xl border border-[#777587] px-8 py-4 text-sm font-semibold text-[#3525cd] transition hover:bg-[#eeedf3]"
            >
              <Sym name="play_circle" />
              {t("hero.secondaryCta")}
            </PublicActionLink>
          </div>
        </div>

        <div className="relative mt-12 lg:mt-0">
          <div className="rudix-landing-glass relative z-10 overflow-hidden rounded-2xl p-4 shadow-xl">
            <div className="rounded-xl border border-[#e3e2e8] bg-[#f4f3f9] p-5">
              <div className="mb-4 flex items-center gap-2">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
                <span className="text-[12px] font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  {t("hero.workspaceLabel")}
                </span>
              </div>
              <div className="mb-3 rounded-full border border-[#c7c4d8] bg-white px-4 py-2.5 text-sm text-[#464555] italic shadow-sm">
                &quot;{t("hero.workspaceQuestion")}&quot;
              </div>
              <div className="rounded-xl bg-[#1F1E24] p-4 font-mono text-[14px] leading-5 text-[#eeedf3]">
                <p className="mb-2 text-[#c3c0ff]">
                  {t("hero.workspaceSource")}
                </p>
                <p className="text-[#eeedf3]">
                  {t("hero.workspaceStep1")}
                  <br />
                  {t("hero.workspaceStep2")}
                  <br />
                  {t("hero.workspaceStep3")}
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-lg bg-white px-4 py-2">
                <span className="text-xs text-[#777587]">{t("hero.confidenceLabel")}</span>
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
                {t("hero.metricLabel")}
              </span>
            </div>
            <p className="text-xl font-bold text-white">
              −84%{" "}
              <span className="text-sm font-normal text-[#777587]">
                {t("hero.metricValue")}
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
  const t = useTranslations("public.support");
  const problems = [
    {
      icon: "search_off",
      title: t("problems.toolFatigueTitle"),
      body: t("problems.toolFatigueBody"),
    },
    {
      icon: "speed",
      title: t("problems.slowOnboardingTitle"),
      body: t("problems.slowOnboardingBody"),
    },
    {
      icon: "sync_problem",
      title: t("problems.inconsistentDataTitle"),
      body: t("problems.inconsistentDataBody"),
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
            {t("problems.heading")}
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            {t("problems.description")}
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
  const t = useTranslations("public.support");
  const sources = [
    { icon: "menu_book", label: t("documentSources.productDocumentation") },
    { icon: "build", label: t("documentSources.troubleshootingGuides") },
    { icon: "quiz", label: t("documentSources.faqs") },
    { icon: "new_releases", label: t("documentSources.releaseNotes") },
    { icon: "warning", label: t("documentSources.knownIssues") },
    { icon: "priority_high", label: t("documentSources.escalationRunbooks") },
  ];

  const features = [
    t("documentSources.feature0"),
    t("documentSources.feature1"),
    t("documentSources.feature2"),
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
                {t("documentSources.dataSourceLabel")}
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
            {t("documentSources.heading")}
          </h2>
          <p className="mb-8 text-lg leading-7 text-[#464555]">
            {t("documentSources.description")}
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
  const t = useTranslations("public.support");
  const steps = [
    {
      icon: "upload_file",
      label: t("howItWorks.step1Title"),
      desc: t("howItWorks.step1Body"),
      accent: "bg-[#3525cd] shadow-[0_0_24px_rgba(53,37,205,0.3)]",
      iconColor: "text-white",
    },
    {
      icon: "database",
      label: t("howItWorks.step2Title"),
      desc: t("howItWorks.step2Body"),
      accent: "border border-[#3525cd] text-[#3525cd] bg-[#eeedf3]",
      iconColor: "",
    },
    {
      icon: "chat",
      label: t("howItWorks.step3Title"),
      desc: t("howItWorks.step3Body"),
      accent: "border border-[#3525cd] text-[#3525cd] bg-[#eeedf3]",
      iconColor: "",
    },
    {
      icon: "verified",
      label: t("howItWorks.step4Title"),
      desc: t("howItWorks.step4Body"),
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
            {t("howItWorks.heading")}
          </h2>
          <p className="text-base leading-6 text-[#777587]">
            {t("howItWorks.description")}
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
  const t = useTranslations("public.support");
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
              {t("exampleQueries.heading")}
            </h2>
            <p className="text-base leading-6 text-[#464555]">
              {t("exampleQueries.description")}
            </p>
          </div>
          <div className="flex shrink-0 gap-1 rounded-full bg-[#e3e2e8] p-1.5">
            <span className="rounded-full bg-white px-5 py-2 text-[12px] font-semibold tracking-[0.05em] uppercase shadow-sm">
              {t("exampleQueries.agentView")}
            </span>
            <span className="px-5 py-2 text-[12px] font-semibold tracking-[0.05em] text-[#464555] uppercase">
              {t("exampleQueries.adminView")}
            </span>
          </div>
        </div>

        <div className="grid h-auto grid-cols-1 gap-6 md:h-[500px] md:grid-cols-12">
          <div className="rudix-landing-glass group relative col-span-1 flex flex-col justify-between overflow-hidden rounded-2xl p-8 md:col-span-8">
            <div>
              <div className="mb-6 flex items-center gap-2">
                <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
                <span className="text-[12px] font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  {t("exampleQueries.activeQuery")}
                </span>
              </div>
              <h3 className="mb-4 text-[24px] leading-8 font-semibold text-[#1a1b20]">
                &quot;{t("exampleQueries.mockQuestion")}&quot;
              </h3>
              <div className="rounded-xl bg-[#1F1E24] p-6 font-mono text-[14px] leading-5 text-[#eeedf3]">
                <p className="mb-2 text-[#c3c0ff]">
                  {t("exampleQueries.mockSource")}
                </p>
                <p>
                  {t("exampleQueries.mockStep1")}
                  <br />
                  {t("exampleQueries.mockStep2")}
                  <br />
                  {t("exampleQueries.mockStep3")}
                </p>
              </div>
            </div>
          </div>

          <div className="col-span-1 space-y-6 md:col-span-4">
            <div className="rudix-landing-glass rounded-2xl border-l-4 border-[#3525cd] p-6">
              <h4 className="mb-2 font-bold text-[#1a1b20]">
                &quot;{t("exampleQueries.q1")}&quot;
              </h4>
              <p className="text-sm leading-5 text-[#464555]">
                &quot;{t("exampleQueries.a1")}&quot;
              </p>
            </div>
            <div className="rudix-landing-glass rounded-2xl border-l-4 border-[#E24329] p-6">
              <h4 className="mb-2 font-bold text-[#1a1b20]">
                &quot;{t("exampleQueries.q2")}&quot;
              </h4>
              <p className="text-sm leading-5 text-[#464555]">
                &quot;{t("exampleQueries.a2")}&quot;
              </p>
            </div>
            <div className="rounded-2xl bg-[#3525cd] p-6 text-white">
              <div className="mb-3 flex items-center justify-between">
                <Sym name="auto_awesome" className="text-base" />
                <span className="text-[11px] font-bold tracking-widest uppercase opacity-80">
                  {t("exampleQueries.smartSuggestLabel")}
                </span>
              </div>
              <p className="font-bold">{t("exampleQueries.smartSuggest")}</p>
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
  const t = useTranslations("public.support");

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
              {t("cta.heading")}
            </h2>
            <p className="mx-auto mb-10 max-w-2xl text-lg leading-7 text-[#777587]">
              {t("cta.description")}
            </p>
            <div className="flex flex-wrap justify-center gap-4">
              <PublicActionLink
                href={demoHref}
                className="rounded-xl bg-[#3525cd] px-10 py-5 text-lg font-bold text-white transition hover:scale-105 active:scale-95"
              >
                {t("cta.primaryCta")}
              </PublicActionLink>
              <PublicActionLink
                href={contactHref}
                className="rounded-xl border border-white/20 bg-white/10 px-10 py-5 text-lg font-bold text-white backdrop-blur-md transition hover:bg-white/20"
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
