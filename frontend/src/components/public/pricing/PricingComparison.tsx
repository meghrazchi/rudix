import { useTranslations } from "next-intl";

import { PLAN_IDS } from "@/components/public/pricing/PricingPlans";
import {
  SectionHeading,
  SiteSection,
} from "@/components/public/site/primitives";

const ROWS = [
  "Document",
  "Storage",
  "TeamAccess",
  "Evaluations",
  "Audit",
  "Deployment",
  "Support",
] as const;

const FEATURED_COLUMN = "team";

export function PricingComparison() {
  const t = useTranslations("public.pricing.comparison");
  const value = (row: string, plan: string) =>
    t(`row${row}${plan.charAt(0).toUpperCase()}${plan.slice(1)}Value`);

  return (
    <SiteSection labelledBy="plan-comparison-title">
      <SectionHeading
        id="plan-comparison-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
      />

      <div className="border-site-border bg-site-surface mt-12 hidden overflow-hidden rounded-2xl border md:block">
        <table className="w-full border-collapse text-start text-sm">
          <caption className="sr-only">{t("tableCaption")}</caption>
          <thead>
            <tr className="border-site-border border-b">
              <th
                scope="col"
                className="text-site-ink-subtle px-6 py-4 text-start text-xs font-medium tracking-wide uppercase"
              >
                {t("capability")}
              </th>
              {PLAN_IDS.map((plan) => (
                <th
                  key={plan}
                  scope="col"
                  className={`text-site-ink px-6 py-4 text-start text-sm font-semibold ${
                    plan === FEATURED_COLUMN
                      ? "bg-site-accent-soft text-site-accent-ink"
                      : ""
                  }`}
                >
                  {t(plan)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-site-border divide-y">
            {ROWS.map((row) => (
              <tr key={row}>
                <th
                  scope="row"
                  className="text-site-ink px-6 py-4 text-start font-medium"
                >
                  {t(`row${row}CapabilityLabel`)}
                </th>
                {PLAN_IDS.map((plan) => (
                  <td
                    key={plan}
                    className={`text-site-ink-muted px-6 py-4 ${
                      plan === FEATURED_COLUMN
                        ? "bg-site-accent-soft/50 text-site-ink"
                        : ""
                    }`}
                  >
                    {value(row, plan)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="mt-10 space-y-3 md:hidden">
        {ROWS.map((row) => (
          <li
            key={row}
            className="border-site-border bg-site-surface rounded-2xl border p-5"
          >
            <p className="text-site-ink text-sm font-semibold">
              {t(`row${row}CapabilityLabel`)}
            </p>
            <dl className="mt-3 space-y-2">
              {PLAN_IDS.map((plan) => (
                <div
                  key={plan}
                  className="flex items-start justify-between gap-4 text-sm"
                >
                  <dt className="text-site-ink-subtle">{t(plan)}</dt>
                  <dd className="text-site-ink text-end">{value(row, plan)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </SiteSection>
  );
}
