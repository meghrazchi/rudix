import { useTranslations } from "next-intl";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

const STEPS = [
  { key: "multiModalUpload", icon: "upload_file" },
  { key: "chunkingVector", icon: "splitscreen" },
  { key: "retrievalGrids", icon: "manage_search" },
  { key: "trustedAnswer", icon: "verified" },
] as const;

export function ProductWorkflow() {
  const t = useTranslations("public.product.workflowSection");

  return (
    <SiteSection
      labelledBy="product-workflow-title"
      className="bg-site-surface border-site-border border-y"
    >
      <SectionHeading
        id="product-workflow-title"
        eyebrow={t("label")}
        title={t("heading")}
        align="center"
      />
      <div className="relative mt-14">
        <div
          aria-hidden="true"
          className="bg-site-border absolute inset-x-[12%] top-6 hidden h-px md:block"
        />
        <ol className="relative grid gap-10 md:grid-cols-4 md:gap-6">
          {STEPS.map((step) => (
            <li
              key={step.key}
              className="flex flex-col items-center text-center"
            >
              <span className="border-site-border bg-site-surface text-site-accent flex h-12 w-12 items-center justify-center rounded-full border">
                <SiteIcon name={step.icon} className="text-xl" />
              </span>
              <h3 className="text-site-ink mt-5 text-base font-semibold">
                {t(`${step.key}Title`)}
              </h3>
              <p className="text-site-ink-muted mt-1.5 max-w-[16rem] text-sm leading-6">
                {t(`${step.key}Desc`)}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </SiteSection>
  );
}
