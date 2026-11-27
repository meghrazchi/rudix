import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const USE_CASES = [
  { key: "legal", icon: "gavel" },
  { key: "support", icon: "support_agent" },
  { key: "engineering", icon: "code" },
  { key: "hr", icon: "badge" },
  { key: "salesOps", icon: "trending_up" },
] as const;

export function LandingUseCases() {
  const t = useTranslations("public.landing.useCases");

  return (
    <SiteSection id="solutions" labelledBy="landing-use-cases-title">
      <SectionHeading
        id="landing-use-cases-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />
      <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-6">
        {USE_CASES.map((item, index) => (
          <li
            key={item.key}
            className={`border-site-border bg-site-surface hover:border-site-accent/40 flex flex-col rounded-2xl border p-6 transition-colors ${
              index < 3 ? "lg:col-span-2" : "lg:col-span-3"
            }`}
          >
            <span className="bg-site-muted text-site-ink-muted inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium">
              <SiteIcon name={item.icon} className="text-sm" />
              {t(`${item.key}Label`)}
            </span>
            <p className="text-site-ink mt-5 text-base leading-7 font-medium">
              {t(`${item.key}Title`)}
            </p>
            <p className="text-site-ink-muted border-site-border mt-auto flex items-start gap-2 border-t pt-4 text-sm leading-6">
              <SiteIcon
                name="check"
                className="text-site-success mt-1 text-base"
              />
              {t(`${item.key}Desc`)}
            </p>
          </li>
        ))}
      </ul>
    </SiteSection>
  );
}
