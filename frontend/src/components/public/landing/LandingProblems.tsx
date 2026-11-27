import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/landing/primitives";

const PROBLEMS = [
  { icon: "find_in_page", key: "manualSearching" },
  { icon: "forum", key: "repeatedQuestions" },
  { icon: "gpp_maybe", key: "untrustedAI" },
  { icon: "account_tree", key: "knowledgeSilos" },
] as const;

export function LandingProblems() {
  const t = useTranslations("public.landing.problems");

  return (
    <SiteSection labelledBy="landing-problems-title">
      <SectionHeading
        id="landing-problems-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />
      <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PROBLEMS.map((item) => (
          <li
            key={item.key}
            className="border-site-border bg-site-surface hover:border-site-accent/40 rounded-2xl border p-6 transition-colors"
          >
            <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
              <SiteIcon name={item.icon} className="text-xl" />
            </span>
            <h3 className="text-site-ink mt-5 text-base font-semibold">
              {t(`${item.key}Title`)}
            </h3>
            <p className="text-site-ink-muted mt-2 text-sm leading-6">
              {t(`${item.key}Desc`)}
            </p>
          </li>
        ))}
      </ul>
    </SiteSection>
  );
}
