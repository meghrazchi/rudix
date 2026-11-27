import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const ADMIN_LINKS = [
  { key: "usageAnalyticsCta", href: "/admin/usage", icon: "insights" },
  { key: "auditLogsCta", href: "/admin/audit-logs", icon: "history" },
  { key: "monitoringCta", href: "/admin/monitoring", icon: "monitor_heart" },
] as const;

const FEATURES = [
  { key: "soc2", icon: "policy" },
  { key: "usageAnalytics", icon: "query_stats" },
] as const;

const INTEGRATIONS = [
  { key: "apiFirst", icon: "api" },
  { key: "futureReady", icon: "sync_alt" },
  { key: "operatorVisibility", icon: "tune" },
] as const;

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: string;
  title: string;
  description: string;
}) {
  return (
    <li className="border-site-border bg-site-surface hover:border-site-accent/40 rounded-2xl border p-7 transition-colors">
      <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
        <SiteIcon name={icon} className="text-xl" />
      </span>
      <h3 className="text-site-ink mt-5 text-lg font-semibold">{title}</h3>
      <p className="text-site-ink-muted mt-2 text-sm leading-6">
        {description}
      </p>
    </li>
  );
}

export function ProductAdmin() {
  const t = useTranslations("public.product.admin");

  return (
    <SiteSection
      labelledBy="product-admin-title"
      className="bg-site-surface border-site-border border-y"
    >
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <SectionHeading
          id="product-admin-title"
          eyebrow={t("eyebrow")}
          title={t("heading")}
          description={t("description")}
        />
        <div className="flex flex-wrap gap-2">
          {ADMIN_LINKS.map((item) => (
            <PublicActionLink
              key={item.key}
              href={item.href}
              className="border-site-border bg-site-canvas text-site-ink hover:border-site-accent/40 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
            >
              <SiteIcon
                name={item.icon}
                className="text-site-accent-ink text-sm"
              />
              {t(item.key)}
            </PublicActionLink>
          ))}
        </div>
      </div>
      <ul className="mt-12 grid gap-4 md:grid-cols-2">
        {FEATURES.map((item) => (
          <FeatureCard
            key={item.key}
            icon={item.icon}
            title={t(`${item.key}Title`)}
            description={t(`${item.key}Desc`)}
          />
        ))}
      </ul>
    </SiteSection>
  );
}

export function ProductIntegration() {
  const t = useTranslations("public.product.integration");

  return (
    <SiteSection labelledBy="product-integration-title">
      <SectionHeading
        id="product-integration-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
      />
      <ul className="mt-12 grid gap-4 md:grid-cols-3">
        {INTEGRATIONS.map((item) => (
          <FeatureCard
            key={item.key}
            icon={item.icon}
            title={t(`${item.key}Title`)}
            description={t(`${item.key}Desc`)}
          />
        ))}
      </ul>
    </SiteSection>
  );
}
