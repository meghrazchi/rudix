import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import {
  SectionHeading,
  SiteIcon,
  SiteSection,
} from "@/components/public/site/primitives";

function StepWidget({ children }: { children: ReactNode }) {
  return (
    <div
      aria-hidden="true"
      className="border-site-border bg-site-canvas mt-6 rounded-xl border p-4"
    >
      {children}
    </div>
  );
}

/** Illustrative bar only; no numeric score is shown on the marketing page. */
function RelevanceBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-site-ink-subtle flex items-center justify-between text-xs">
        <bdi className="truncate font-mono">{label}</bdi>
      </div>
      <div className="bg-site-muted mt-1.5 h-1.5 overflow-hidden rounded-full">
        <div
          className="bg-site-accent h-full rounded-full"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

export function LandingWorkflow() {
  const t = useTranslations("public.landing.workflow");

  const steps = [
    {
      icon: "upload_file",
      title: t("ingestionTitle"),
      description: t("ingestionDesc"),
      widget: (
        <StepWidget>
          <div className="flex items-center gap-3">
            <SiteIcon name="description" className="text-site-accent text-xl" />
            <bdi className="text-site-ink min-w-0 flex-1 truncate text-sm font-medium">
              handbook-2026.pdf
            </bdi>
            <span className="text-site-success inline-flex items-center gap-1 text-xs font-medium">
              <SiteIcon name="check_circle" className="text-sm" filled />
              {t("indexedStatus")}
            </span>
          </div>
          <div className="bg-site-muted mt-3 h-1.5 overflow-hidden rounded-full">
            <div className="bg-site-success h-full w-full rounded-full" />
          </div>
        </StepWidget>
      ),
    },
    {
      icon: "travel_explore",
      title: t("retrievalTitle"),
      description: t("retrievalDesc"),
      widget: (
        <StepWidget>
          <p className="text-site-ink-subtle mb-3 text-xs font-medium">
            {t("relevance")}
          </p>
          <div className="space-y-3">
            <RelevanceBar label="returns-policy.pdf · p.4" value={96} />
            <RelevanceBar label="warranty-terms.pdf · p.11" value={88} />
          </div>
        </StepWidget>
      ),
    },
    {
      icon: "fact_check",
      title: t("generationTitle"),
      description: t("generationDesc"),
      widget: (
        <StepWidget>
          <div className="flex items-center justify-between">
            <span className="text-site-ink text-xs font-medium">
              {t("citedPassage")}
            </span>
            <SiteIcon
              name="verified"
              className="text-site-success text-base"
              filled
            />
          </div>
          <p className="bg-site-surface text-site-ink-muted mt-2 rounded-lg px-3 py-2 text-xs leading-5 italic">
            {t("passageText")}
          </p>
          <p className="text-site-accent-ink mt-2 inline-flex items-center gap-1 text-xs font-medium">
            {t("openSource")}
            <SiteIcon name="arrow_forward" className="rtl-mirror text-sm" />
          </p>
        </StepWidget>
      ),
    },
  ];

  return (
    <SiteSection
      labelledBy="landing-workflow-title"
      className="bg-site-muted/60 border-site-border border-y"
    >
      <SectionHeading
        id="landing-workflow-title"
        eyebrow={t("eyebrow")}
        title={t("heading")}
        description={t("description")}
        align="center"
      />
      <div className="relative mt-14">
        <div
          aria-hidden="true"
          className="bg-site-border absolute inset-x-[16%] top-[42px] hidden h-px lg:block"
        />
        <ol className="relative grid gap-4 lg:grid-cols-3">
          {steps.map((step, index) => (
            <li
              key={step.title}
              className="border-site-border bg-site-surface relative flex flex-col rounded-2xl border p-6"
            >
              <div className="flex items-center justify-between">
                <span className="bg-site-accent-soft text-site-accent-ink rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold tracking-wide uppercase">
                  {t("step", { number: String(index + 1).padStart(2, "0") })}
                </span>
                <SiteIcon
                  name={step.icon}
                  className="text-site-ink-subtle text-xl"
                />
              </div>
              <h3 className="text-site-ink mt-5 text-lg font-semibold">
                {step.title}
              </h3>
              <p className="text-site-ink-muted mt-2 text-sm leading-6">
                {step.description}
              </p>
              <div className="mt-auto">{step.widget}</div>
            </li>
          ))}
        </ol>
      </div>
    </SiteSection>
  );
}
