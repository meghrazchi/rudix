"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  EVAL_LANGUAGE_OPTIONS,
  getLanguageBreakdown,
  getLanguageCoverage,
  type LanguageBreakdownItem,
  type LanguageCoverageItem,
} from "@/lib/api/evaluations";
import { queryKeys } from "@/lib/api/query";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)} ms`;
}

function fmtUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(4)}`;
}

function languageLabel(code: string): string {
  const found = EVAL_LANGUAGE_OPTIONS.find((o) => o.value === code);
  return found ? found.label : code;
}

// ---------------------------------------------------------------------------
// Coverage warning banner
// ---------------------------------------------------------------------------

function CoverageWarning({ languages }: { languages: string[] }) {
  const t = useTranslations("evaluations.multilingual");
  if (languages.length === 0) return null;
  return (
    <div
      role="alert"
      aria-live="polite"
      className="flex items-start gap-2 rounded-md border border-yellow-300 bg-yellow-50 p-3 text-sm text-yellow-800"
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0">
        ⚠
      </span>
      <span>
        {t.rich("coverageWarning", {
          languages: languages.map(languageLabel).join(", "),
          strong: (chunks) => <strong>{chunks}</strong>,
        })}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Language coverage table
// ---------------------------------------------------------------------------

function CoverageRow({ item }: { item: LanguageCoverageItem }) {
  const t = useTranslations("evaluations.multilingual");
  return (
    <tr className={item.has_insufficient_coverage ? "bg-yellow-50" : undefined}>
      <td className="px-3 py-2 font-medium">
        {languageLabel(item.language)}
        {item.has_insufficient_coverage && (
          <span
            aria-label={t("lowBadgeAria")}
            title={t("lowBadgeTitle")}
            className="ml-1.5 inline-block rounded bg-yellow-200 px-1 text-xs text-yellow-800"
          >
            {t("lowBadge")}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {item.question_count}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {item.has_expected_answer_count}
      </td>
    </tr>
  );
}

type LanguageCoverageTableProps = {
  evaluationSetId: string;
};

export function LanguageCoverageTable({
  evaluationSetId,
}: LanguageCoverageTableProps) {
  const t = useTranslations("evaluations.multilingual");
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.evaluations.languageCoverage(evaluationSetId),
    queryFn: () => getLanguageCoverage(evaluationSetId),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="py-4 text-center text-sm text-gray-500" aria-busy="true">
        {t("loadingCoverage")}
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="py-4 text-center text-sm text-red-600" role="alert">
        {t("coverageFailed")}
      </div>
    );
  }
  if (
    data.items.length === 0 &&
    data.unlabelled_count === data.total_question_count
  ) {
    return (
      <div className="rounded-md border border-dashed border-gray-300 p-4 text-center text-sm text-gray-500">
        {t.rich("noLabels", {
          code: (chunks) => <code>{chunks}</code>,
        })}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <CoverageWarning languages={data.coverage_warning_languages} />

      <div className="overflow-x-auto rounded-md border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium tracking-wider text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2">{t("columns.language")}</th>
              <th className="px-3 py-2 text-right">{t("columns.questions")}</th>
              <th className="px-3 py-2 text-right">
                {t("columns.withExpected")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.items.map((item) => (
              <CoverageRow key={item.language} item={item} />
            ))}
            {data.unlabelled_count > 0 && (
              <tr className="text-gray-400">
                <td className="px-3 py-2 italic">{t("unlabelled")}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {data.unlabelled_count}
                </td>
                <td className="px-3 py-2" />
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-500">
        {t("totalQuestions", { count: data.total_question_count })}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Language breakdown table (per-run)
// ---------------------------------------------------------------------------

function scoreColor(value: number | null, higherIsBetter = true): string {
  if (value == null) return "";
  const good = higherIsBetter ? value >= 0.75 : value <= 0.15;
  const warn = higherIsBetter ? value >= 0.5 : value <= 0.3;
  if (good) return "text-green-700";
  if (warn) return "text-yellow-700";
  return "text-red-600";
}

function BreakdownRow({ item }: { item: LanguageBreakdownItem }) {
  const t = useTranslations("evaluations.multilingual");
  return (
    <tr className={item.has_insufficient_coverage ? "bg-yellow-50" : undefined}>
      <td className="px-3 py-2 font-medium">
        {item.language === "unlabelled" ? (
          <span className="text-gray-400 italic">{t("unlabelled")}</span>
        ) : (
          languageLabel(item.language)
        )}
        {item.has_insufficient_coverage && (
          <span
            aria-label={t("lowBadgeAria")}
            title={t("lowBadgeTitle")}
            className="ml-1.5 inline-block rounded bg-yellow-200 px-1 text-xs text-yellow-800"
          >
            {t("lowBadge")}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {item.success_count}/{item.question_count}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${scoreColor(item.retrieval_hit_rate)}`}
      >
        {fmtPct(item.retrieval_hit_rate)}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${scoreColor(item.citation_accuracy_score)}`}
      >
        {fmtPct(item.citation_accuracy_score)}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${scoreColor(item.faithfulness_score)}`}
      >
        {fmtPct(item.faithfulness_score)}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${scoreColor(item.answer_relevance_score)}`}
      >
        {fmtPct(item.answer_relevance_score)}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${scoreColor(item.language_adherence_score)}`}
      >
        {fmtPct(item.language_adherence_score)}
      </td>
      <td className="px-3 py-2 text-right text-gray-600 tabular-nums">
        {fmtMs(item.latency_ms_average)}
      </td>
      <td className="px-3 py-2 text-right text-gray-600 tabular-nums">
        {fmtUsd(item.cost_usd_total)}
      </td>
    </tr>
  );
}

type MultilingualEvalPanelProps = {
  evaluationRunId: string;
};

export function MultilingualEvalPanel({
  evaluationRunId,
}: MultilingualEvalPanelProps) {
  const t = useTranslations("evaluations.multilingual");
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.evaluations.languageBreakdown(evaluationRunId),
    queryFn: () => getLanguageBreakdown(evaluationRunId),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="py-4 text-center text-sm text-gray-500" aria-busy="true">
        {t("loadingBreakdown")}
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="py-4 text-center text-sm text-red-600" role="alert">
        {t("breakdownFailed")}
      </div>
    );
  }

  const labelled = data.items.filter((i) => i.language !== "unlabelled");
  if (labelled.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-gray-300 p-4 text-center text-sm text-gray-500">
        {t.rich("noRunLabels", {
          code: (chunks) => <code>{chunks}</code>,
        })}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <CoverageWarning languages={data.coverage_warning_languages} />

      <div className="overflow-x-auto rounded-md border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium tracking-wider text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2">{t("columns.language")}</th>
              <th
                className="px-3 py-2 text-right"
                title={t("columns.questionsTitle")}
              >
                {t("columns.questions")}
              </th>
              <th className="px-3 py-2 text-right">{t("columns.retrieval")}</th>
              <th className="px-3 py-2 text-right">{t("columns.citation")}</th>
              <th className="px-3 py-2 text-right">
                {t("columns.faithfulness")}
              </th>
              <th className="px-3 py-2 text-right">{t("columns.relevance")}</th>
              <th
                className="px-3 py-2 text-right"
                title={t("columns.langAdherenceTitle")}
              >
                {t("columns.langAdherence")}
              </th>
              <th className="px-3 py-2 text-right">
                {t("columns.avgLatency")}
              </th>
              <th className="px-3 py-2 text-right">{t("columns.cost")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {data.items.map((item) => (
              <BreakdownRow key={item.language} item={item} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
