import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
  StatusPill,
} from "@/components/public/site/primitives";

function DocumentDetailMock() {
  const t = useTranslations("public.product.mock");
  const rows = [
    { label: t("pagesLabel"), value: "94" },
    { label: t("chunksLabel"), value: "412" },
    { label: t("languageLabel"), value: t("languageValue") },
    { label: t("versionLabel"), value: "v3" },
  ];

  return (
    <div
      aria-hidden="true"
      className="border-site-border bg-site-surface rounded-2xl border p-6"
    >
      <div className="border-site-border flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <SiteIcon name="contract" className="text-site-accent text-2xl" />
          <bdi className="text-site-ink truncate text-sm font-semibold">
            master-services-agreement.pdf
          </bdi>
        </div>
        <StatusPill tone="success">
          <span className="bg-site-success h-1.5 w-1.5 rounded-full" />
          {t("statusReady")}
        </StatusPill>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 pt-5">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="text-site-ink-subtle text-xs font-medium tracking-wide uppercase">
              {row.label}
            </dt>
            <dd className="text-site-ink mt-1 text-sm font-medium">
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="border-site-border mt-5 flex items-center justify-between border-t pt-4">
        <span className="text-site-ink-subtle text-xs font-medium tracking-wide uppercase">
          {t("statusLabel")}
        </span>
        <span className="text-site-success inline-flex items-center gap-1 text-sm font-medium">
          <SiteIcon name="check_circle" className="text-base" filled />
          {t("indexed")}
        </span>
      </div>
    </div>
  );
}

export function ProductDocuments() {
  const t = useTranslations("public.product.documentsSection");

  return (
    <SiteSection labelledBy="product-documents-title">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2 lg:gap-16">
        <div>
          <SectionHeading
            id="product-documents-title"
            eyebrow={t("eyebrow")}
            title={t("heading")}
            description={t("description")}
          />
          <ul className="mt-8 space-y-3">
            {[t("feature1"), t("feature2")].map((feature) => (
              <li
                key={feature}
                className="text-site-ink flex items-start gap-3 text-sm leading-6 md:text-base"
              >
                <SiteIcon
                  name="check_circle"
                  className="text-site-accent mt-0.5 text-xl"
                />
                {feature}
              </li>
            ))}
          </ul>
          <div className="border-site-accent/25 bg-site-accent-soft mt-8 flex items-start gap-3 rounded-2xl border p-4">
            <SiteIcon
              name="link"
              className="text-site-accent-ink mt-0.5 text-xl"
            />
            <p className="text-site-ink text-sm leading-6">
              <strong className="text-site-accent-ink font-semibold">
                {t("sourceTransparencyLabel")}.
              </strong>{" "}
              {t("sourceTransparencyText")}
            </p>
          </div>
        </div>
        <DocumentDetailMock />
      </div>
    </SiteSection>
  );
}
