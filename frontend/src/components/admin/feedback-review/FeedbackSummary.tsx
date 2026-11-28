"use client";

import { triggerCsvDownload } from "@/components/admin/feedback-review/feedbackReviewShared";
import { useFeedbackReviewController } from "@/components/admin/feedback-review/useFeedbackReviewController";

export function FeedbackSummary({
  ctl,
}: {
  ctl: ReturnType<typeof useFeedbackReviewController>;
}) {
  const { t, openCount, highSeverityCount, resolvedCount, exportUrl } = ctl;

  return (
    <>
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              {t("header.eyebrow")}
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              {t("header.title")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              {t("header.description")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => triggerCsvDownload(exportUrl)}
            className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
          >
            {t("actions.exportCsv")}
          </button>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            {t("stats.openItems")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {openCount}
          </p>
        </article>
        <article className="rounded-xl border border-amber-200 bg-amber-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-amber-700 uppercase">
            {t("stats.highSeverity")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-amber-700">
            {highSeverityCount}
          </p>
        </article>
        <article className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            {t("stats.resolved")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-emerald-700">
            {resolvedCount}
          </p>
        </article>
      </section>
    </>
  );
}
