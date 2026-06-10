"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  AudienceIcon,
  enterpriseUseCaseCards,
} from "@/components/public/pages/solutions/enterpriseUseCases";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function SolutionsHero() {
  const t = useTranslations("public.solutions");
  const links = resolvePublicSiteLinks();

  return (
    <section className="relative overflow-hidden py-16 lg:py-24">
      <div className="mx-auto w-full max-w-7xl px-4 lg:px-8">
        <div className="max-w-3xl">
          <span className="inline-flex rounded-full bg-[#e7e4ff] px-3 py-1 text-[11px] font-bold tracking-[0.11em] text-[#3f32d2] uppercase">
            {t("hero.badge")}
          </span>
          <h1 className="mt-5 text-4xl leading-tight font-black text-[#0f1118] lg:text-6xl">
            {t("hero.heading")}
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#5a6072] lg:text-base">
            {t("hero.description")}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <PublicActionLink
              href={links.product}
              className="rounded-lg bg-[#3525cd] px-5 py-3 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(53,37,205,0.25)] transition hover:bg-[#291ec0]"
            >
              {t("hero.explorePlatformCta")}
            </PublicActionLink>
            <PublicActionLink
              href={links.docs}
              className="rounded-lg border border-[#cfd4e2] bg-white px-5 py-3 text-sm font-semibold text-[#23283a] transition hover:bg-[#f4f6fc]"
            >
              {t("hero.viewApiDocsCta")}
            </PublicActionLink>
          </div>
        </div>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 hidden w-[42%] bg-[radial-gradient(circle_at_70%_40%,rgba(53,37,205,0.18),transparent_65%)] lg:block"
      />
    </section>
  );
}

export function SolutionCardsSection() {
  const t = useTranslations("public.solutions");

  return (
    <section
      aria-labelledby="solutions-cards-title"
      className="mx-auto w-full max-w-7xl px-4 py-10 lg:px-8 lg:py-14"
    >
      <div className="max-w-3xl">
        <h2
          id="solutions-cards-title"
          className="text-3xl font-black text-[#12141b] lg:text-5xl"
        >
          {t("cards.heading")}
        </h2>
        <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
          {t("cards.description")}
        </p>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
        {enterpriseUseCaseCards.map((card) => (
          <article
            key={card.id}
            className="rounded-xl border border-l-4 border-[#d8dce7] border-l-[#3525cd] bg-white/80 p-6 shadow-sm backdrop-blur-sm transition hover:-translate-y-0.5 hover:shadow-md"
          >
            {card.href ? (
              <PublicActionLink
                href={card.href}
                className="block rounded-sm focus-visible:ring-2 focus-visible:ring-[#3525cd] focus-visible:outline-none"
                ariaLabel={`${card.title} solution`}
              >
                <div className="mb-4 inline-flex text-[#3525cd]">
                  <AudienceIcon icon={card.icon} />
                </div>
                <h3 className="text-lg font-semibold text-[#2c2f3a]">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-8 text-[#5a6071]">
                  {card.description}
                </p>
              </PublicActionLink>
            ) : (
              <>
                <div className="mb-4 inline-flex text-[#3525cd]">
                  <AudienceIcon icon={card.icon} />
                </div>
                <h3 className="text-lg font-semibold text-[#2c2f3a]">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-8 text-[#5a6071]">
                  {card.description}
                </p>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export function CrossSolutionValueSection() {
  const t = useTranslations("public.solutions");

  const crossSolutionValues = [
    {
      title: t("crossValue.secureUploadTitle"),
      description: t("crossValue.secureUploadDesc"),
    },
    {
      title: t("crossValue.citationBackedTitle"),
      description: t("crossValue.citationBackedDesc"),
    },
    {
      title: t("crossValue.evaluationQualityTitle"),
      description: t("crossValue.evaluationQualityDesc"),
    },
    {
      title: t("crossValue.governanceTitle"),
      description: t("crossValue.governanceDesc"),
    },
  ];

  return (
    <section
      id="cross-solution-value"
      aria-labelledby="cross-solution-value-title"
      className="bg-[#f3f4f8]"
    >
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="max-w-3xl">
          <h2
            id="cross-solution-value-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            {t("crossValue.heading")}
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
            {t("crossValue.description")}
          </p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {crossSolutionValues.map((value) => (
            <article
              key={value.title}
              className="rounded-2xl border border-[#d7dce9] bg-white p-5 shadow-sm"
            >
              <h3 className="text-lg font-semibold text-[#1e2233]">
                {value.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-[#5a6073]">
                {value.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function QuestionMatrixSection() {
  const t = useTranslations("public.solutions");

  return (
    <section aria-labelledby="question-matrix-title" className="bg-[#eaecf3]">
      <div className="mx-auto w-full max-w-7xl px-4 py-14 lg:px-8 lg:py-20">
        <div className="mb-8 max-w-3xl">
          <h2
            id="question-matrix-title"
            className="text-3xl font-black text-[#12141b] lg:text-5xl"
          >
            {t("questionMatrix.heading")}
          </h2>
          <p className="mt-3 text-sm leading-7 text-[#5b6173] lg:text-base">
            {t("questionMatrix.description")}
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse overflow-hidden rounded-xl bg-white shadow-sm">
            <thead>
              <tr>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  {t("questionMatrix.complexity")}
                </th>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  {t("questionMatrix.sampleQuery")}
                </th>
                <th className="border-b border-[#d1d6e3] bg-[#e6e9f2] p-6 text-left text-sm font-semibold text-[#2d3246]">
                  {t("questionMatrix.retrievalStrategy")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e1e5ef]">
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#95f7b2] px-2 py-1 text-xs font-bold text-[#043520]">
                    {t("questionMatrix.singleHopLabel")}
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  {t("questionMatrix.singleHopQuery")}
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  {t("questionMatrix.singleHopStrategy")}
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#e5e1e9] px-2 py-1 text-xs font-bold text-[#2b2c35]">
                    {t("questionMatrix.multiHopLabel")}
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  {t("questionMatrix.multiHopQuery")}
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  {t("questionMatrix.multiHopStrategy")}
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#e2dfff] px-2 py-1 text-xs font-bold text-[#25147c]">
                    {t("questionMatrix.structuralLabel")}
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  {t("questionMatrix.structuralQuery")}
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  {t("questionMatrix.structuralStrategy")}
                </td>
              </tr>
              <tr>
                <td className="p-6">
                  <span className="rounded bg-[#ffdad6] px-2 py-1 text-xs font-bold text-[#8d1013]">
                    {t("questionMatrix.reasoningLabel")}
                  </span>
                </td>
                <td className="p-6 text-sm text-[#4f566b] italic">
                  {t("questionMatrix.reasoningQuery")}
                </td>
                <td className="p-6 font-mono text-sm text-[#3037db]">
                  {t("questionMatrix.reasoningStrategy")}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
