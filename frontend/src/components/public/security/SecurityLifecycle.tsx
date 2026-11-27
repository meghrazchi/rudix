import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const STEPS = [
  "validate",
  "store",
  "parse",
  "chunk",
  "embed",
  "index",
  "answer",
  "delete",
  "reindex",
] as const;

const ACCESS = [
  { key: "authSession", icon: "passkey" },
  { key: "roleAccess", icon: "group" },
  { key: "adminGovernance", icon: "tune" },
  { key: "routeBoundaries", icon: "alt_route" },
] as const;

export function SecurityLifecycle() {
  const t = useTranslations("public.security.documentHandling");

  return (
    <SiteSection
      labelledBy="security-lifecycle-title"
      className="bg-site-surface border-site-border border-y"
    >
      <SectionHeading
        id="security-lifecycle-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
        align="center"
      />
      <ol className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className="border-site-border bg-site-canvas flex gap-4 rounded-2xl border p-5"
          >
            <span className="text-site-accent-ink font-mono text-xs font-semibold">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              <h3 className="text-site-ink text-sm font-semibold">
                {t(`${step}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-1 text-sm leading-6">
                {t(`${step}Desc`)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </SiteSection>
  );
}

export function SecurityAccess() {
  const t = useTranslations("public.security.accessGovernance");

  return (
    <SiteSection labelledBy="security-access-title">
      <SectionHeading
        id="security-access-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />
      <ul className="mt-12 grid gap-4 md:grid-cols-2">
        {ACCESS.map((item) => (
          <li
            key={item.key}
            className="border-site-border bg-site-surface flex gap-4 rounded-2xl border p-6"
          >
            <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
              <SiteIcon name={item.icon} className="text-xl" />
            </span>
            <div>
              <h3 className="text-site-ink text-base font-semibold">
                {t(`${item.key}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t(`${item.key}Desc`)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </SiteSection>
  );
}
