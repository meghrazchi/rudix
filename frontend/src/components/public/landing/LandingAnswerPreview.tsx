import { useTranslations } from "next-intl";

import { SiteIcon } from "@/components/public/site/primitives";

const SOURCES = [
  { number: 1, file: "returns-policy.pdf", sectionKey: "source1Section" },
  { number: 2, file: "warranty-terms.pdf", sectionKey: "source2Section" },
] as const;

function CitationChip({ number, label }: { number: number; label: string }) {
  return (
    <sup
      aria-label={label}
      className="bg-site-accent-soft text-site-accent-ink mx-0.5 inline-flex h-5 min-w-5 -translate-y-px items-center justify-center rounded-full px-1.5 align-middle font-mono text-[11px] font-semibold"
    >
      {number}
    </sup>
  );
}

/**
 * Illustrative product preview built from UI (not a screenshot) so it stays
 * crisp, themable, translatable, and readable by crawlers.
 */
export function LandingAnswerPreview() {
  const t = useTranslations("public.landing.preview");

  return (
    <figure
      aria-label={t("ariaLabel")}
      className="border-site-border bg-site-surface mx-auto w-full max-w-4xl rounded-2xl border p-2 text-start shadow-[0_24px_60px_-32px_rgba(15,17,23,0.25)]"
    >
      <div className="border-site-border flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
          <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
          <span className="bg-site-border h-2.5 w-2.5 rounded-full" />
          <span className="text-site-ink-subtle ms-2 text-xs font-medium">
            {t("windowLabel")}
          </span>
        </div>
        <span className="bg-site-muted text-site-ink-muted inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs">
          <SiteIcon name="folder_open" className="text-sm" />
          {t("documentsIndexed")}
        </span>
      </div>

      <div className="space-y-5 p-4 md:p-6">
        <div className="flex justify-end">
          <div className="bg-site-muted max-w-md rounded-2xl rounded-se-sm px-4 py-3">
            <div className="text-site-ink-subtle mb-1 flex items-center justify-between gap-6 text-xs">
              <span className="font-medium">{t("you")}</span>
              <span>{t("justNow")}</span>
            </div>
            <p className="text-site-ink text-sm font-medium md:text-base">
              {t("question")}
            </p>
          </div>
        </div>

        <div className="border-site-border rounded-2xl border p-4 md:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="bg-site-accent text-site-on-accent flex h-6 w-6 items-center justify-center rounded-md">
                <SiteIcon name="auto_awesome" className="text-sm" filled />
              </span>
              <span className="text-site-ink text-sm font-semibold">
                {t("assistant")}
              </span>
            </div>
            <span className="bg-site-success-soft text-site-success inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium">
              <span className="bg-site-success h-1.5 w-1.5 rounded-full" />
              {t("confidence")}
            </span>
          </div>

          <p className="text-site-ink mt-3 text-sm leading-7 md:text-[15px]">
            {t("answerIntro")}
            <CitationChip
              number={1}
              label={t("citationLabel", { number: 1 })}
            />
            . {t("answerMiddle")}
            <CitationChip
              number={2}
              label={t("citationLabel", { number: 2 })}
            />
            , {t("answerEnd")}
          </p>

          <div className="border-site-border mt-4 border-t pt-4">
            <p className="text-site-ink-subtle text-xs font-semibold tracking-[0.08em] uppercase">
              {t("sourcesHeading")}
            </p>
            <ul className="mt-2 space-y-1.5">
              {SOURCES.map((source) => (
                <li
                  key={source.number}
                  className="bg-site-canvas flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="bg-site-accent-soft text-site-accent-ink rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold">
                      {source.number}
                    </span>
                    <SiteIcon
                      name="picture_as_pdf"
                      className="text-site-ink-subtle text-base"
                    />
                    <bdi className="text-site-ink truncate text-sm font-medium">
                      {source.file}
                    </bdi>
                    <span className="text-site-ink-subtle hidden text-xs sm:inline">
                      {t(source.sectionKey)}
                    </span>
                  </div>
                  <span className="text-site-accent-ink inline-flex items-center gap-1 text-xs font-medium">
                    {t("viewSource")}
                    <SiteIcon
                      name="arrow_forward"
                      className="rtl-mirror text-sm"
                    />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </figure>
  );
}
