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

function ClientPortalBreadcrumb() {
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
            {t("clientPortal.breadcrumb")}
          </li>
        </ol>
      </nav>
    </div>
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
  const t = useTranslations("public.clientPortal");

  return (
    <section
      aria-labelledby="cp-hero-title"
      className="relative overflow-hidden bg-[#faf9ff] pt-24 pb-32"
    >
      <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-16 px-10 lg:grid-cols-2">
        <div className="z-10">
          <span className="mb-6 inline-block rounded-full bg-[#e2dfff] px-3 py-1 text-[12px] font-semibold tracking-[0.05em] text-[#3323cc] uppercase">
            {t("hero.badge")}
          </span>
          <h1
            id="cp-hero-title"
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
              className="rounded-lg bg-[#3525cd] px-8 py-4 font-semibold text-white shadow-lg transition hover:shadow-xl active:scale-95"
            >
              {t("hero.primaryCta")}
            </PublicActionLink>
            <PublicActionLink
              href={demoHref}
              className="rounded-lg border border-[#c7c4d8] px-8 py-4 font-semibold text-[#0A0A0F] transition hover:bg-[#eeedf3] active:scale-95"
            >
              {t("hero.secondaryCta")}
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
                {t("hero.mockPanelLabel")}
              </span>
            </div>
            <div className="space-y-5 font-mono text-sm">
              <div>
                <p className="mb-1 text-[10px] tracking-widest text-[#c3c0ff] uppercase">
                  {t("hero.mockCustomerLabel")}
                </p>
                <p className="text-white">
                  &ldquo;{t("hero.mockQuestion")}&rdquo;
                </p>
              </div>
              <div className="border-t border-white/10 pt-5">
                <p className="mb-2 text-[10px] tracking-widest text-[#75db94] uppercase">
                  {t("hero.mockAnswerLabel")}
                </p>
                <p className="text-[#e3e2e8]">{t("hero.mockAnswer")}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="rounded bg-[#3525cd]/20 px-2 py-0.5 text-[10px] text-[#c3c0ff]">
                    {t("hero.mockTag1")}
                  </span>
                  <span className="rounded bg-[#3525cd]/20 px-2 py-0.5 text-[10px] text-[#c3c0ff]">
                    {t("hero.mockTag2")}
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
  const t = useTranslations("public.clientPortal");
  const problems = [
    {
      icon: "forum",
      title: t("problems.repeatedQuestionsTitle"),
      body: t("problems.repeatedQuestionsBody"),
    },
    {
      icon: "folder_off",
      title: t("problems.scatteredDocsTitle"),
      body: t("problems.scatteredDocsBody"),
    },
    {
      icon: "transfer_within_a_station",
      title: t("problems.handoffsTitle"),
      body: t("problems.handoffsBody"),
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
  const t = useTranslations("public.clientPortal");
  const sources = [
    { icon: "rocket_launch", label: t("documentSources.onboardingGuides") },
    {
      icon: "integration_instructions",
      label: t("documentSources.apiDocumentation"),
    },
    { icon: "build", label: t("documentSources.implementationGuides") },
    { icon: "support_agent", label: t("documentSources.knowledgeBase") },
    { icon: "menu_book", label: t("documentSources.productGuides") },
    { icon: "handshake", label: t("documentSources.enablementMaterials") },
  ];

  const features = [
    t("documentSources.feature0"),
    t("documentSources.feature1"),
    t("documentSources.feature2"),
    t("documentSources.feature3"),
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
            {t("documentSources.heading")}
          </h2>
          <p className="mb-6 text-lg leading-7 text-[#464555]">
            {t("documentSources.description")}
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
  const t = useTranslations("public.clientPortal");
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
            {t("workflow.heading")}
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            {t("workflow.description")}
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
                {t("workflow.step01Label")}
              </span>
              <h3 className="mb-4 text-[30px] leading-[38px] font-semibold text-white">
                {t("workflow.step01Title")}
              </h3>
              <p className="text-base leading-6 text-[#464555]">
                {t("workflow.step01Body")}
              </p>
            </div>
          </div>

          {/* Step 02 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-8 md:col-span-2">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                {t("workflow.step02Label")}
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                {t("workflow.step02Title")}
              </h3>
            </div>
            <p className="text-base leading-6 text-[#464555]">
              {t("workflow.step02Body")}
            </p>
          </div>

          {/* Step 03 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-8">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-[#c3c0ff] uppercase">
                {t("workflow.step03Label")}
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                {t("workflow.step03Title")}
              </h3>
            </div>
            <Sym name="question_answer" className="text-4xl text-[#c3c0ff]" />
          </div>

          {/* Step 04 */}
          <div className="col-span-1 flex flex-col justify-between rounded-2xl border border-[#3525cd] bg-[#3525cd] p-8 text-white">
            <div>
              <span className="mb-2 block text-[12px] font-semibold tracking-[0.05em] text-white/60 uppercase">
                {t("workflow.step04Label")}
              </span>
              <h3 className="mb-2 text-[24px] leading-8 font-semibold text-white">
                {t("workflow.step04Title")}
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
  const t = useTranslations("public.clientPortal");
  const useCases = [
    {
      icon: "rocket_launch",
      title: t("useCases.customerOnboardingTitle"),
      body: t("useCases.customerOnboardingBody"),
    },
    {
      icon: "build",
      title: t("useCases.implementationDocsTitle"),
      body: t("useCases.implementationDocsBody"),
    },
    {
      icon: "handshake",
      title: t("useCases.partnerEnablementTitle"),
      body: t("useCases.partnerEnablementBody"),
    },
    {
      icon: "support_agent",
      title: t("useCases.supportKnowledgeTitle"),
      body: t("useCases.supportKnowledgeBody"),
    },
    {
      icon: "swap_horiz",
      title: t("useCases.accountHandoffTitle"),
      body: t("useCases.accountHandoffBody"),
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
            {t("useCases.heading")}
          </h2>
          <p className="mx-auto max-w-2xl text-base leading-6 text-[#464555]">
            {t("useCases.description")}
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
  const t = useTranslations("public.clientPortal");
  const examples = [
    {
      question: t("exampleQueries.q1"),
      answer: t("exampleQueries.a1"),
      sources: [t("exampleQueries.source1a"), t("exampleQueries.source1b")],
    },
    {
      question: t("exampleQueries.q2"),
      answer: t("exampleQueries.a2"),
      sources: [t("exampleQueries.source2a"), t("exampleQueries.source2b")],
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
          {t("exampleQueries.heading")}
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
                      {t("exampleQueries.answerLabel")}
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
  const t = useTranslations("public.clientPortal");
  const related = [
    { label: t("related.support"), href: "/solutions/support" },
    { label: t("related.sales"), href: "/solutions/sales" },
    {
      label: t("related.internalKnowledge"),
      href: "/solutions/internal-knowledge",
    },
    { label: t("related.security"), href: "/security" },
  ];

  return (
    <section aria-labelledby="cp-related-title" className="bg-[#f4f3f9] py-16">
      <div className="mx-auto max-w-[1440px] px-10">
        <h2
          id="cp-related-title"
          className="mb-8 text-center text-[24px] leading-8 font-semibold text-[#1a1b20]"
        >
          {t("related.heading")}
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
  const t = useTranslations("public.clientPortal");

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
            {t("cta.heading")}
          </h2>
          <p className="mb-10 text-lg leading-7 text-[#464555]">
            {t("cta.description")}
          </p>
          <div className="flex flex-col justify-center gap-4 sm:flex-row">
            <PublicActionLink
              href={demoHref}
              className="rounded-xl bg-[#3525cd] px-10 py-5 text-lg font-bold text-white shadow-lg transition hover:-translate-y-1 hover:shadow-xl active:scale-95"
            >
              {t("cta.primaryCta")}
            </PublicActionLink>
            <PublicActionLink
              href={trialHref}
              className="rounded-xl bg-[#0A0A0F] px-10 py-5 text-lg font-bold text-[#faf9ff] transition hover:bg-black active:scale-95"
            >
              {t("cta.secondaryCta")}
            </PublicActionLink>
          </div>
          <p className="mt-8 text-[12px] font-semibold tracking-[0.05em] text-[#777587] uppercase">
            {t("cta.disclaimer")}
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
