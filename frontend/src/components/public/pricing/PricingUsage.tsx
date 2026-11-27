import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const NOTES = [
  { key: "documents", icon: "folder_managed" },
  { key: "questions", icon: "forum" },
  { key: "storage", icon: "database" },
] as const;

export function PricingUsage() {
  const t = useTranslations("public.pricing.usageLimits");

  return (
    <SiteSection
      labelledBy="usage-limits-title"
      className="bg-site-surface border-site-border border-y"
    >
      <SectionHeading
        id="usage-limits-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />
      <ul className="mt-12 grid gap-4 md:grid-cols-3">
        {NOTES.map((note) => (
          <li
            key={note.key}
            className="border-site-border bg-site-canvas rounded-2xl border p-6"
          >
            <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
              <SiteIcon name={note.icon} className="text-xl" />
            </span>
            <h3 className="text-site-ink mt-5 text-base font-semibold">
              {t(`${note.key}Title`)}
            </h3>
            <p className="text-site-ink-muted mt-2 text-sm leading-6">
              {t(`${note.key}Detail`)}
            </p>
          </li>
        ))}
      </ul>
    </SiteSection>
  );
}
