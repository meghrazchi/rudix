import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const PILLARS = [
  { key: "documentPrivacy", icon: "lock" },
  { key: "orgIsolation", icon: "domain" },
  { key: "accessControl", icon: "admin_panel_settings" },
  { key: "auditLogs", icon: "history_edu" },
  { key: "safeUploads", icon: "upload_file" },
  { key: "encryption", icon: "encrypted" },
  { key: "observability", icon: "monitoring" },
] as const;

export function SecurityPillars() {
  const t = useTranslations("public.security.pillars");

  return (
    <SiteSection labelledBy="security-pillars-title" className="pt-0 lg:pt-0">
      <SectionHeading
        id="security-pillars-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />
      <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {PILLARS.map((pillar, index) => {
          const wide = index === PILLARS.length - 1;
          return (
            <li
              key={pillar.key}
              className={`border-site-border bg-site-surface hover:border-site-accent/40 flex rounded-2xl border p-6 transition-colors ${
                wide
                  ? "flex-col gap-5 md:col-span-2 md:flex-row md:items-center md:justify-between lg:col-span-3"
                  : "flex-col"
              }`}
            >
              <div className={wide ? "flex items-start gap-4" : ""}>
                <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
                  <SiteIcon name={pillar.icon} className="text-xl" />
                </span>
                <div className={wide ? "" : "mt-5"}>
                  <h3 className="text-site-ink text-base font-semibold">
                    {t(`${pillar.key}Title`)}
                  </h3>
                  <p className="text-site-ink-muted mt-2 text-sm leading-6">
                    {t(`${pillar.key}Desc`)}
                  </p>
                </div>
              </div>
              <div
                className={
                  wide ? "shrink-0" : "border-site-border mt-auto border-t pt-4"
                }
              >
                <span
                  className={`bg-site-muted text-site-ink-muted inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                    wide ? "" : "mt-5"
                  }`}
                >
                  {t(`${pillar.key}Callout`)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </SiteSection>
  );
}
