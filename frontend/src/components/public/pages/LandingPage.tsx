"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function LandingPage() {
  const t = useTranslations("public.landing");
  const links = resolvePublicSiteLinks();

  const problemCards = [
    {
      icon: "search_off",
      title: t("problems.manualSearchingTitle"),
      description: t("problems.manualSearchingDesc"),
      accentClass: "bg-[#ffdad6] text-[#ba1a1a]",
    },
    {
      icon: "replay",
      title: t("problems.repeatedQuestionsTitle"),
      description: t("problems.repeatedQuestionsDesc"),
      accentClass: "bg-[#e2dfff] text-[#3323cc]",
    },
    {
      icon: "warning",
      title: t("problems.untrustedAITitle"),
      description: t("problems.untrustedAIDesc"),
      accentClass: "bg-[#91f8ae] text-[#00542a]",
    },
    {
      icon: "lan",
      title: t("problems.knowledgeSilosTitle"),
      description: t("problems.knowledgeSilosDesc"),
      accentClass: "bg-[#e2dee6] text-[#5f5d64]",
    },
  ];

  const workflowSteps = [
    {
      title: t("workflow.ingestionTitle"),
      description: t("workflow.ingestionDesc"),
    },
    {
      title: t("workflow.retrievalTitle"),
      description: t("workflow.retrievalDesc"),
    },
    {
      title: t("workflow.generationTitle"),
      description: t("workflow.generationDesc"),
    },
  ];

  const useCaseCards = [
    {
      label: t("useCases.legalLabel"),
      title: t("useCases.legalTitle"),
      description: t("useCases.legalDesc"),
    },
    {
      label: t("useCases.supportLabel"),
      title: t("useCases.supportTitle"),
      description: t("useCases.supportDesc"),
    },
    {
      label: t("useCases.engineeringLabel"),
      title: t("useCases.engineeringTitle"),
      description: t("useCases.engineeringDesc"),
    },
    {
      label: t("useCases.hrLabel"),
      title: t("useCases.hrTitle"),
      description: t("useCases.hrDesc"),
    },
    {
      label: t("useCases.salesOpsLabel"),
      title: t("useCases.salesOpsTitle"),
      description: t("useCases.salesOpsDesc"),
    },
  ];

  const securityCards = [
    {
      icon: "shield",
      title: t("security.dataIsolationTitle"),
      description: t("security.dataIsolationDesc"),
    },
    {
      icon: "history_edu",
      title: t("security.auditLogsTitle"),
      description: t("security.auditLogsDesc"),
    },
    {
      icon: "lock",
      title: t("security.encryptionTitle"),
      description: t("security.encryptionDesc"),
    },
  ];

  return (
    <div className="bg-[#faf9ff] text-[#1a1b20]">
      <section className="relative overflow-hidden px-4 py-16 lg:px-8 lg:py-24">
        <div className="mx-auto grid w-full max-w-7xl gap-12 lg:grid-cols-12 lg:items-center">
          <div className="space-y-8 lg:col-span-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#c3c0ff] bg-[#e2dfff]/50 px-4 py-1.5 text-[#3323cc]">
              <span
                className="material-symbols-outlined text-sm"
                aria-hidden="true"
              >
                verified
              </span>
              <span className="text-xs font-semibold tracking-[0.05em] uppercase">
                {t("hero.badge")}
              </span>
            </div>
            <h1 className="text-4xl leading-tight font-black tracking-[-0.02em] text-[#1a1b20] md:text-5xl lg:text-6xl">
              {t("hero.title")}
              <br />
              <span className="text-[#3525cd]">{t("hero.titleHighlight")}</span>
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-[#464555]">
              {t("hero.description")}
            </p>
            <div className="flex flex-wrap gap-4">
              <PublicActionLink
                href={links.requestDemo}
                className="inline-flex items-center gap-2 rounded-xl bg-[#3525cd] px-8 py-4 text-base font-semibold text-white transition hover:bg-[#2d20ac]"
              >
                {t("hero.primaryCta")}
                <span
                  className="material-symbols-outlined text-base"
                  aria-hidden="true"
                >
                  arrow_forward
                </span>
              </PublicActionLink>
              <PublicActionLink
                href={links.docs}
                className="rounded-xl border border-[#777587] px-8 py-4 text-base font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3]"
              >
                {t("hero.secondaryCta")}
              </PublicActionLink>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 pt-3">
              {[
                t("hero.trustSoc2"),
                t("hero.trustGdpr"),
                t("hero.trustPrivateCloud"),
              ].map((label) => (
                <p
                  key={label}
                  className="inline-flex items-center gap-2 text-xs font-semibold tracking-[0.05em] text-[#464555] uppercase"
                >
                  <span
                    className="material-symbols-outlined text-base text-[#108548]"
                    aria-hidden="true"
                  >
                    check_circle
                  </span>
                  {label}
                </p>
              ))}
            </div>
          </div>
          <div className="relative lg:col-span-6">
            <div className="rudix-landing-glass rounded-3xl p-2 shadow-2xl">
              <Image
                src="/images/chat-sample-2.png"
                alt={t("hero.imageAlt")}
                width={1200}
                height={780}
                className="h-auto w-full rounded-2xl"
                priority
              />
            </div>
            <div className="absolute -top-10 -right-8 -z-10 h-56 w-56 rounded-full bg-[#c3c0ff] blur-[88px]" />
            <div className="absolute -bottom-10 -left-8 -z-10 h-48 w-48 rounded-full bg-[#91f8ae] blur-[80px]" />
          </div>
        </div>
      </section>

      <section className="bg-white px-4 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto w-full max-w-7xl">
          <div className="mx-auto max-w-3xl space-y-4 text-center">
            <h2 className="text-3xl leading-tight font-bold text-[#1a1b20] lg:text-4xl">
              {t("problems.heading")}
            </h2>
            <p className="text-lg text-[#464555]">
              {t("problems.description")}
            </p>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            {problemCards.map((card) => (
              <article
                key={card.title}
                className="rounded-2xl border border-[#c7c4d8] bg-[#faf9ff] p-7 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg"
              >
                <div
                  className={`mb-5 inline-flex h-12 w-12 items-center justify-center rounded-xl ${card.accentClass}`}
                >
                  <span
                    className="material-symbols-outlined"
                    aria-hidden="true"
                  >
                    {card.icon}
                  </span>
                </div>
                <h3 className="text-xl font-semibold text-[#1a1b20]">
                  {card.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-[#464555]">
                  {card.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden px-4 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-12 lg:flex-row lg:items-center lg:gap-16">
          <div className="space-y-8 lg:w-1/2">
            <h2 className="text-3xl font-black text-[#1a1b20] md:text-4xl lg:text-5xl">
              {t("workflow.heading")}
            </h2>
            <div className="space-y-7">
              {workflowSteps.map((step, index) => (
                <div key={step.title} className="flex gap-5">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#3525cd] text-sm font-bold text-white">
                    {index + 1}
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-[#1a1b20]">
                      {step.title}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-[#464555]">
                      {step.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="w-full lg:w-1/2">
            <div className="rounded-3xl bg-[#0a0a0f] p-8 shadow-2xl">
              <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-xl font-semibold text-white">
                  {t("workflow.pipelineExplorer")}
                </h3>
                <p className="rounded bg-[#10854833] px-3 py-1 text-[11px] font-semibold tracking-[0.06em] text-[#8af1a8] uppercase">
                  {t("workflow.liveStatus")}
                </p>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between rounded-xl border border-[#ffffff1f] bg-[#ffffff14] px-4 py-3 text-white">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#c3c0ff]"
                      aria-hidden="true"
                    >
                      upload_file
                    </span>
                    <span className="font-mono text-sm">Document.PDF</span>
                  </div>
                  <span className="text-[11px] text-[#f1f0f699] uppercase">
                    {t("workflow.input")}
                  </span>
                </div>
                <div className="rudix-landing-flow-line rudix-landing-flow-line--active mx-auto h-7 w-px bg-[#777587]" />
                <div className="flex items-center justify-between rounded-xl border border-[#4f46e57f] bg-[#3525cd33] px-4 py-3 text-white shadow-[0_0_20px_rgba(79,70,229,0.2)]">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#c3c0ff]"
                      aria-hidden="true"
                    >
                      psychology
                    </span>
                    <span className="font-mono text-sm">
                      RAG_Retrieval_Logic
                    </span>
                  </div>
                  <span className="text-[11px] text-[#c3c0ff] uppercase">
                    {t("workflow.active")}
                  </span>
                </div>
                <div className="mx-auto h-7 w-px bg-[#777587]" />
                <div className="flex items-center justify-between rounded-xl border border-[#ffffff1f] bg-[#ffffff14] px-4 py-3 text-white">
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined text-[#91f8ae]"
                      aria-hidden="true"
                    >
                      output
                    </span>
                    <span className="font-mono text-sm">Grounded_Response</span>
                  </div>
                  <span className="text-[11px] text-[#f1f0f699] uppercase">
                    {t("workflow.output")}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section
        id="solutions"
        className="bg-[#f4f3f9] px-4 py-20 lg:px-8 lg:py-24"
      >
        <div className="mx-auto w-full max-w-7xl">
          <div className="space-y-4">
            <h2 className="text-3xl font-bold text-[#1a1b20] lg:text-4xl">
              {t("useCases.heading")}
            </h2>
            <p className="text-lg text-[#464555]">
              {t("useCases.description")}
            </p>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-5">
            {useCaseCards.map((item) => (
              <article
                key={item.label}
                className="rounded-2xl border border-[#c7c4d8] bg-white p-6 transition hover:border-[#3525cd]"
              >
                <p className="text-xs font-semibold tracking-[0.05em] text-[#3525cd] uppercase">
                  {item.label}
                </p>
                <h3 className="mt-4 text-sm leading-6 font-semibold text-[#1a1b20]">
                  {item.title}
                </h3>
                <p className="mt-3 text-sm leading-6 text-[#464555]">
                  {item.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section
        id="security"
        className="relative overflow-hidden bg-[#0a0a0f] px-4 py-20 text-white lg:px-8 lg:py-24"
      >
        <div className="mx-auto grid w-full max-w-7xl gap-12 lg:grid-cols-2 lg:items-center lg:gap-20">
          <div>
            <h2 className="text-3xl leading-tight font-black lg:text-5xl">
              {t("security.heading")}
            </h2>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-[#c3c0ff]">
              {t("security.description")}
            </p>
            <div className="mt-10 space-y-7">
              {securityCards.map((item) => (
                <article key={item.title} className="flex items-start gap-4">
                  <div className="rounded-lg bg-[#ffffff17] p-3 text-[#c3c0ff]">
                    <span
                      className="material-symbols-outlined"
                      aria-hidden="true"
                    >
                      {item.icon}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-white">
                      {item.title}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-[#f1f0f6b3]">
                      {item.description}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </div>
          <div className="rounded-3xl border border-[#ffffff1f] bg-[#ffffff0d] p-8">
            <Image
              src="/images/pipeline-rag-sample.png"
              alt={t("security.imageAlt")}
              width={1200}
              height={780}
              className="h-auto w-full rounded-2xl opacity-90"
            />
          </div>
        </div>
      </section>

      <section
        id="pricing"
        className="border-t border-[#c7c4d8] bg-[#faf9ff] px-4 py-20 lg:px-8 lg:py-24"
      >
        <div className="mx-auto w-full max-w-4xl text-center">
          <h2 className="text-3xl leading-tight font-black text-[#1a1b20] lg:text-5xl">
            {t("cta.heading")}
          </h2>
          <p className="mx-auto mt-5 max-w-3xl text-lg leading-8 text-[#464555]">
            {t("cta.description")}
          </p>
          <div className="mt-10 flex flex-col justify-center gap-4 sm:flex-row">
            <PublicActionLink
              href={links.requestDemo}
              className="rounded-xl bg-[#3525cd] px-10 py-4 text-lg font-semibold text-white transition hover:bg-[#2d20ac]"
            >
              {t("cta.primaryCta")}
            </PublicActionLink>
            <PublicActionLink
              href={links.docs}
              className="rounded-xl border border-[#777587] px-10 py-4 text-lg font-semibold text-[#1a1b20] transition hover:bg-[#eeedf3]"
            >
              {t("cta.secondaryCta")}
            </PublicActionLink>
          </div>
        </div>
      </section>
    </div>
  );
}
