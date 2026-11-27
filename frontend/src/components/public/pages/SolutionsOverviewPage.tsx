"use client";

import { useTranslations } from "next-intl";

import { PublicActionLink } from "@/components/public/PublicActionLink";
import {
  PrimaryLink,
  SecondaryLink,
  SiteBreadcrumb,
  SiteCtaPanel,
  SiteSplitHero,
  StepGrid,
} from "@/components/public/site/SiteBlocks";
import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

const AUDIENCES = [
  {
    key: "knowledge",
    icon: "menu_book",
    href: "/solutions/internal-knowledge",
  },
  { key: "hr", icon: "badge", href: "/solutions/hr" },
  { key: "support", icon: "support_agent", href: "/solutions/support" },
  { key: "legal", icon: "gavel", href: "/solutions/legal" },
  { key: "compliance", icon: "policy", href: "/solutions/compliance" },
  {
    key: "operations",
    icon: "settings_suggest",
    href: "/solutions/operations",
  },
  { key: "sales", icon: "trending_up", href: "/solutions/sales" },
  { key: "procurement", icon: "inventory_2", href: "/solutions/procurement" },
  { key: "research", icon: "science", href: "/solutions/research" },
  { key: "portal", icon: "handshake", href: "/solutions/client-portal" },
] as const;

const VALUES = [
  { key: "secureUpload", icon: "cloud_upload" },
  { key: "citationBacked", icon: "format_quote" },
  { key: "evaluationQuality", icon: "fact_check" },
  { key: "governance", icon: "shield_person" },
] as const;

const MATRIX = ["singleHop", "multiHop", "structural", "reasoning"] as const;

const WORKFLOW = ["collect", "prepare", "answer", "improve"] as const;

/** Solutions overview (minimal modern redesign). */
export function SolutionsOverviewPage() {
  const tp = useTranslations("public");
  const t = useTranslations("public.solutions");
  const links = resolvePublicSiteLinks();

  return (
    <div className="bg-site-canvas text-site-ink">
      <SiteBreadcrumb
        items={[
          { label: tp("home"), href: "/" },
          { label: tp("breadcrumb.solutions") },
        ]}
      />

      <SiteSplitHero
        id="solutions-hero-title"
        badge={t("hero.badge")}
        title={t("hero.heading")}
        description={t("hero.description")}
        actions={
          <>
            <PrimaryLink
              href={links.product}
              label={t("hero.explorePlatformCta")}
            />
            <SecondaryLink href={links.docs} label={t("hero.viewApiDocsCta")} />
          </>
        }
      />

      <SiteSection labelledBy="solutions-cards-title" className="pt-0 lg:pt-0">
        <SectionHeading
          id="solutions-cards-title"
          title={t("cards.heading")}
          description={t("cards.description")}
        />
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {AUDIENCES.map((item) => {
            const title = t(`cards.items.${item.key}.title`);
            return (
              <li key={item.key}>
                <PublicActionLink
                  href={item.href}
                  ariaLabel={`${title} solution`}
                  className="group border-site-border bg-site-surface hover:border-site-accent/50 flex h-full flex-col rounded-2xl border p-6 transition-colors"
                >
                  <span className="bg-site-accent-soft text-site-accent-ink flex h-10 w-10 items-center justify-center rounded-xl">
                    <SiteIcon name={item.icon} className="text-xl" />
                  </span>
                  <h3 className="text-site-ink mt-5 text-base font-semibold">
                    {title}
                  </h3>
                  <p className="text-site-ink-muted mt-2 text-sm leading-6">
                    {t(`cards.items.${item.key}.description`)}
                  </p>
                  <SiteIcon
                    name="arrow_forward"
                    className="rtl-mirror text-site-accent-ink mt-auto pt-5 text-lg transition-transform group-hover:translate-x-1 rtl:group-hover:-translate-x-1"
                  />
                </PublicActionLink>
              </li>
            );
          })}
        </ul>
      </SiteSection>

      <SiteSection
        labelledBy="solutions-value-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="solutions-value-title"
          title={t("crossValue.heading")}
          description={t("crossValue.description")}
          align="center"
        />
        <ul className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {VALUES.map((item) => (
            <li key={item.key} className="text-center">
              <span className="bg-site-accent-soft text-site-accent-ink mx-auto flex h-12 w-12 items-center justify-center rounded-full">
                <SiteIcon name={item.icon} className="text-xl" />
              </span>
              <h3 className="text-site-ink mt-5 text-base font-semibold">
                {t(`crossValue.${item.key}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {t(`crossValue.${item.key}Desc`)}
              </p>
            </li>
          ))}
        </ul>
      </SiteSection>

      <SiteSection labelledBy="solutions-workflow-title">
        <SectionHeading
          id="solutions-workflow-title"
          title={t("workflowStrip.title")}
          description={t("workflowStrip.description")}
        />
        <div className="mt-12">
          <StepGrid
            steps={WORKFLOW.map((step) => ({
              title: t(`workflowStrip.${step}Title`),
              description: t(`workflowStrip.${step}Desc`),
            }))}
          />
        </div>
      </SiteSection>

      <SiteSection
        labelledBy="solutions-matrix-title"
        className="bg-site-surface border-site-border border-y"
      >
        <SectionHeading
          id="solutions-matrix-title"
          title={t("questionMatrix.heading")}
          description={t("questionMatrix.description")}
        />
        <div className="border-site-border mt-12 overflow-x-auto rounded-2xl border">
          <table className="w-full min-w-[640px] border-collapse text-start text-sm">
            <thead className="bg-site-canvas">
              <tr className="border-site-border border-b">
                {(
                  ["complexity", "sampleQuery", "retrievalStrategy"] as const
                ).map((col) => (
                  <th
                    key={col}
                    scope="col"
                    className="text-site-ink-subtle px-6 py-4 text-start text-xs font-medium tracking-wide uppercase"
                  >
                    {t(`questionMatrix.${col}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-site-border divide-y">
              {MATRIX.map((row) => (
                <tr key={row}>
                  <th scope="row" className="px-6 py-4 text-start align-top">
                    <span className="bg-site-accent-soft text-site-accent-ink inline-flex rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap">
                      {t(`questionMatrix.${row}Label`)}
                    </span>
                  </th>
                  <td className="text-site-ink px-6 py-4 align-top">
                    {t(`questionMatrix.${row}Query`)}
                  </td>
                  <td className="text-site-ink-muted px-6 py-4 align-top">
                    {t(`questionMatrix.${row}Strategy`)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SiteSection>

      <SiteCtaPanel
        id="solutions-cta-title"
        title={t("cta.heading")}
        description={t("cta.description")}
        primary={{ href: links.requestDemo, label: t("cta.primaryCta") }}
        secondary={{ href: links.product, label: t("cta.secondaryCta") }}
      />
    </div>
  );
}
