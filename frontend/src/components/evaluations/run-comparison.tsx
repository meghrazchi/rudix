"use client";

import { useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  buildComparisonExportUrl,
  compareEvaluationRuns,
  type CaseComparisonRow,
  type CompareRunsParams,
  type MetricDelta,
  type RunComparisonResponse,
} from "@/lib/api/evaluations";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { ErrorState } from "@/components/states/ErrorState";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CaseFilter = {
  query: string;
  caseStatus: "all" | "regression" | "improvement" | "failed_any";
  difficulty: "all" | "easy" | "medium" | "hard";
};

function caseFilterDefaults(): CaseFilter {
  return { query: "", caseStatus: "all", difficulty: "all" };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMetricValue(value: number | null, metric: string): string {
  if (value == null) return "—";
  if (metric === "latency_ms_average") return `${Math.round(value)} ms`;
  if (metric === "cost_usd_total") return `$${value.toFixed(4)}`;
  if (value <= 1) return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(2);
}

function formatDelta(delta: number | null, metric: string): string {
  if (delta == null) return "—";
  if (metric === "latency_ms_average") {
    return delta >= 0 ? `+${Math.round(delta)} ms` : `${Math.round(delta)} ms`;
  }
  if (metric === "cost_usd_total") {
    return delta >= 0
      ? `+$${delta.toFixed(4)}`
      : `-$${Math.abs(delta).toFixed(4)}`;
  }
  const pct = (delta * 100).toFixed(1);
  return delta >= 0 ? `+${pct}%` : `${pct}%`;
}

function runLabel(runId: string, runName: string | null): string {
  return runName || runId.slice(0, 8);
}

function filterCases(
  cases: CaseComparisonRow[],
  filter: CaseFilter,
): CaseComparisonRow[] {
  return cases.filter((c) => {
    if (filter.caseStatus === "regression" && !c.regression) return false;
    if (filter.caseStatus === "improvement" && !c.improvement) return false;
    if (filter.caseStatus === "failed_any") {
      const aFailed = c.run_a != null && c.run_a.status === "failed";
      const bFailed = c.run_b != null && c.run_b.status === "failed";
      if (!aFailed && !bFailed) return false;
    }
    if (filter.difficulty !== "all" && c.difficulty !== filter.difficulty)
      return false;
    if (filter.query.trim()) {
      const q = filter.query.trim().toLowerCase();
      if (!c.question.toLowerCase().includes(q)) return false;
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricBadge({
  isRegression,
  isImprovement,
}: {
  isRegression: boolean;
  isImprovement: boolean;
}) {
  const t = useTranslations("evaluations.runComparison");
  if (isRegression) {
    return (
      <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
        {t("regression")}
      </span>
    );
  }
  if (isImprovement) {
    return (
      <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
        {t("improvement")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
      {t("unchanged")}
    </span>
  );
}

function CaseStatusBadge({ row }: { row: CaseComparisonRow }) {
  const t = useTranslations("evaluations.runComparison");
  if (row.regression) {
    return (
      <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
        {t("regression")}
      </span>
    );
  }
  if (row.improvement) {
    return (
      <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
        {t("improvement")}
      </span>
    );
  }
  return null;
}

function MetricSummaryTable({
  deltas,
  labelA,
  labelB,
}: {
  deltas: MetricDelta[];
  labelA: string;
  labelB: string;
}) {
  const t = useTranslations("evaluations.runComparison");
  if (deltas.length === 0) {
    return <p className="text-sm text-gray-500">{t("noMetricSummary")}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full divide-y divide-gray-100 text-sm">
        <caption className="sr-only">{t("metricCaption")}</caption>
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              {t("metric")}
            </th>
            <th className="px-3 py-2 text-right text-xs font-semibold tracking-wide text-gray-500 uppercase">
              {t("runA", { label: labelA })}
            </th>
            <th className="px-3 py-2 text-right text-xs font-semibold tracking-wide text-gray-500 uppercase">
              {t("runB", { label: labelB })}
            </th>
            <th className="px-3 py-2 text-right text-xs font-semibold tracking-wide text-gray-500 uppercase">
              {t("delta")}
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              {t("status")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {deltas.map((d) => (
            <tr
              key={d.metric}
              className={
                d.is_regression
                  ? "bg-red-50"
                  : d.is_improvement
                    ? "bg-green-50"
                    : undefined
              }
            >
              <td className="px-3 py-2 font-medium text-gray-800">{d.label}</td>
              <td className="px-3 py-2 text-right text-gray-700 tabular-nums">
                {formatMetricValue(d.run_a_value, d.metric)}
              </td>
              <td className="px-3 py-2 text-right text-gray-700 tabular-nums">
                {formatMetricValue(d.run_b_value, d.metric)}
              </td>
              <td
                className={`px-3 py-2 text-right font-semibold tabular-nums ${
                  d.is_regression
                    ? "text-red-700"
                    : d.is_improvement
                      ? "text-green-700"
                      : "text-gray-500"
                }`}
              >
                {formatDelta(d.delta, d.metric)}
              </td>
              <td className="px-3 py-2">
                <MetricBadge
                  isRegression={d.is_regression}
                  isImprovement={d.is_improvement}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ExpandedCase = {
  questionId: string;
  side: "a" | "b";
};

function CaseComparisonTable({
  cases,
  filter,
  onFilterChange,
  labelA,
  labelB,
}: {
  cases: CaseComparisonRow[];
  filter: CaseFilter;
  onFilterChange: (next: CaseFilter) => void;
  labelA: string;
  labelB: string;
}) {
  const t = useTranslations("evaluations.runComparison");
  const [expanded, setExpanded] = useState<ExpandedCase | null>(null);

  const visible = useMemo(() => filterCases(cases, filter), [cases, filter]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          aria-label={t("searchCases")}
          placeholder={t("searchPlaceholder")}
          value={filter.query}
          onChange={(e) => onFilterChange({ ...filter, query: e.target.value })}
          className="h-8 w-56 rounded border border-gray-300 px-2 text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-[#8b5cf6] focus:outline-none"
        />
        <select
          aria-label={t("filterStatus")}
          value={filter.caseStatus}
          onChange={(e) =>
            onFilterChange({
              ...filter,
              caseStatus: e.target.value as CaseFilter["caseStatus"],
            })
          }
          className="h-8 rounded border border-gray-300 px-2 text-sm text-gray-700 focus:ring-2 focus:ring-[#8b5cf6] focus:outline-none"
        >
          <option value="all">{t("allCases")}</option>
          <option value="regression">{t("regressionsOnly")}</option>
          <option value="improvement">{t("improvementsOnly")}</option>
          <option value="failed_any">{t("failedAny")}</option>
        </select>
        <select
          aria-label={t("filterDifficulty")}
          value={filter.difficulty}
          onChange={(e) =>
            onFilterChange({
              ...filter,
              difficulty: e.target.value as CaseFilter["difficulty"],
            })
          }
          className="h-8 rounded border border-gray-300 px-2 text-sm text-gray-700 focus:ring-2 focus:ring-[#8b5cf6] focus:outline-none"
        >
          <option value="all">{t("allDifficulties")}</option>
          <option value="easy">{t("easy")}</option>
          <option value="medium">{t("medium")}</option>
          <option value="hard">{t("hard")}</option>
        </select>
        <span className="ml-auto text-xs text-gray-500">
          {t("casesCount", { visible: visible.length, total: cases.length })}
        </span>
      </div>

      {visible.length === 0 ? (
        <p className="py-4 text-center text-sm text-gray-500">
          {t("noCasesMatch")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <caption className="sr-only">{t("caseCaption")}</caption>
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                  {t("question")}
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                  {t("diff")}
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                  {t("runA", { label: labelA })}
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                  {t("runB", { label: labelB })}
                </th>
                <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
                  {t("status")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {visible.map((row) => {
                const isExpandedA =
                  expanded?.questionId === row.evaluation_question_id &&
                  expanded.side === "a";
                const isExpandedB =
                  expanded?.questionId === row.evaluation_question_id &&
                  expanded.side === "b";

                return (
                  <>
                    <tr
                      key={row.evaluation_question_id}
                      className={
                        row.regression
                          ? "bg-red-50"
                          : row.improvement
                            ? "bg-green-50"
                            : undefined
                      }
                    >
                      <td className="max-w-xs px-3 py-2">
                        <p className="truncate text-gray-800">{row.question}</p>
                        {row.tags.length > 0 && (
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            {row.tags.map((tag) => (
                              <span
                                key={tag}
                                className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-500">
                        {row.difficulty ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <CaseResultCell
                          result={row.run_a}
                          isExpanded={isExpandedA}
                          onToggle={() =>
                            setExpanded(
                              isExpandedA
                                ? null
                                : {
                                    questionId: row.evaluation_question_id,
                                    side: "a",
                                  },
                            )
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <CaseResultCell
                          result={row.run_b}
                          isExpanded={isExpandedB}
                          onToggle={() =>
                            setExpanded(
                              isExpandedB
                                ? null
                                : {
                                    questionId: row.evaluation_question_id,
                                    side: "b",
                                  },
                            )
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <CaseStatusBadge row={row} />
                      </td>
                    </tr>
                    {(isExpandedA || isExpandedB) && (
                      <tr
                        key={`${row.evaluation_question_id}-expanded`}
                        className="bg-gray-50"
                      >
                        <td colSpan={5} className="px-4 py-3">
                          <CaseAnswerDetail
                            result={isExpandedA ? row.run_a : row.run_b}
                            side={isExpandedA ? "a" : "b"}
                            label={isExpandedA ? labelA : labelB}
                          />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CaseResultCell({
  result,
  isExpanded,
  onToggle,
}: {
  result: CaseComparisonRow["run_a"];
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const t = useTranslations("evaluations.runComparison");
  if (!result) {
    return <span className="text-xs text-gray-400">{t("noResult")}</span>;
  }
  const isFailed = result.status === "failed";
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-xs font-medium ${
            isFailed
              ? "bg-red-100 text-red-700"
              : "bg-emerald-100 text-emerald-700"
          }`}
        >
          {isFailed ? t("failed") : t("ok")}
        </span>
        {result.retrieval_score != null && (
          <span className="text-xs text-gray-600 tabular-nums">
            {t("retShort", {
              value: (result.retrieval_score * 100).toFixed(0),
            })}
          </span>
        )}
        {result.faithfulness_score != null && (
          <span className="text-xs text-gray-600 tabular-nums">
            {t("faithShort", {
              value: (result.faithfulness_score * 100).toFixed(0),
            })}
          </span>
        )}
      </div>
      {result.generated_answer && (
        <button
          type="button"
          onClick={onToggle}
          className="text-xs text-[#7c3aed] underline hover:no-underline"
        >
          {isExpanded ? t("hideAnswer") : t("viewAnswer")}
        </button>
      )}
    </div>
  );
}

function CaseAnswerDetail({
  result,
  side,
  label,
}: {
  result: CaseComparisonRow["run_a"];
  side: "a" | "b";
  label: string;
}) {
  const t = useTranslations("evaluations.runComparison");
  if (!result) return null;
  return (
    <div className="space-y-2 text-sm">
      <p className="font-semibold text-gray-700">
        {t("answerFrom", { label, side: side.toUpperCase() })}
      </p>
      {result.generated_answer ? (
        <p className="rounded bg-white p-2 whitespace-pre-wrap text-gray-800 ring-1 ring-gray-200">
          {result.generated_answer}
        </p>
      ) : (
        <p className="text-gray-400 italic">{t("noAnswer")}</p>
      )}
      {result.failure_reason && (
        <p className="text-red-600">
          {t.rich("failure", {
            strong: (chunks) => <span className="font-medium">{chunks}</span>,
            reason: result.failure_reason,
          })}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

type RunComparisonPanelProps = {
  runAId: string;
  runBId: string;
  onClose?: () => void;
};

export function RunComparisonPanel({
  runAId,
  runBId,
  onClose,
}: RunComparisonPanelProps) {
  const t = useTranslations("evaluations.runComparison");
  const [caseFilter, setCaseFilter] = useState<CaseFilter>(caseFilterDefaults);

  const queryParams: CompareRunsParams = {
    difficulty: caseFilter.difficulty !== "all" ? caseFilter.difficulty : null,
  };

  const comparisonQuery = useQuery({
    queryKey: queryKeys.evaluations.compare(runAId, runBId, queryParams),
    queryFn: () => compareEvaluationRuns(runAId, runBId, queryParams),
    enabled: Boolean(runAId) && Boolean(runBId),
  });

  const comparison: RunComparisonResponse | null = comparisonQuery.data ?? null;

  const labelA = comparison
    ? runLabel(comparison.run_a.evaluation_run_id, comparison.run_a.run_name)
    : runAId.slice(0, 8);
  const labelB = comparison
    ? runLabel(comparison.run_b.evaluation_run_id, comparison.run_b.run_name)
    : runBId.slice(0, 8);

  return (
    <section
      aria-label={t("panelAria")}
      className="space-y-6 rounded-xl border border-[#ddd8ec] bg-white p-4 shadow-sm"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{t("title")}</h2>
          <p className="mt-0.5 text-sm text-gray-500">
            <span className="font-medium text-gray-700">{labelA}</span>
            {t("vs")}
            <span className="font-medium text-gray-700">{labelB}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {comparison && (
            <>
              <a
                href={buildComparisonExportUrl(runAId, runBId, "csv")}
                download="comparison.csv"
                className="rounded border border-[#cbc6dd] px-3 py-1.5 text-xs font-semibold text-[#403b5f] hover:bg-gray-50"
              >
                {t("exportCsv")}
              </a>
              <a
                href={buildComparisonExportUrl(runAId, runBId, "json")}
                download="comparison.json"
                className="rounded border border-[#cbc6dd] px-3 py-1.5 text-xs font-semibold text-[#403b5f] hover:bg-gray-50"
              >
                {t("exportJson")}
              </a>
            </>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-[#cbc6dd] px-3 py-1.5 text-xs font-semibold text-[#403b5f] hover:bg-gray-50"
            >
              {t("close")}
            </button>
          )}
        </div>
      </div>

      {/* Regression / improvement counts */}
      {comparison && (
        <div className="flex flex-wrap gap-4">
          <div className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2">
            <span className="text-2xl font-bold text-red-700 tabular-nums">
              {comparison.regression_count}
            </span>
            <span className="text-sm text-red-700">
              {t("regressionCount", { count: comparison.regression_count })}
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2">
            <span className="text-2xl font-bold text-green-700 tabular-nums">
              {comparison.improvement_count}
            </span>
            <span className="text-sm text-green-700">
              {t("improvementCount", { count: comparison.improvement_count })}
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2">
            <span className="text-2xl font-bold text-gray-700 tabular-nums">
              {comparison.total_cases}
            </span>
            <span className="text-sm text-gray-600">{t("totalCases")}</span>
          </div>
        </div>
      )}

      {/* Loading / error states */}
      {comparisonQuery.isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      )}

      {comparisonQuery.isError && (
        <ErrorState
          compact
          error={comparisonQuery.error}
          description={getApiErrorMessage(comparisonQuery.error)}
          onRetry={() => void comparisonQuery.refetch()}
        />
      )}

      {/* Metric summary table */}
      {comparison && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-700">
            {t("metricSummary")}
          </h3>
          <MetricSummaryTable
            deltas={comparison.metric_deltas}
            labelA={labelA}
            labelB={labelB}
          />
        </div>
      )}

      {/* Run headers */}
      {comparison && (
        <div className="grid grid-cols-2 gap-4">
          <RunHeaderCard run={comparison.run_a} label={t("baselineLabel")} />
          <RunHeaderCard run={comparison.run_b} label={t("candidateLabel")} />
        </div>
      )}

      {/* Case comparison */}
      {comparison && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-700">
            {t("caseComparison")}
          </h3>
          <CaseComparisonTable
            cases={comparison.cases}
            filter={caseFilter}
            onFilterChange={setCaseFilter}
            labelA={labelA}
            labelB={labelB}
          />
        </div>
      )}
    </section>
  );
}

function RunHeaderCard({
  run,
  label,
}: {
  run: RunComparisonResponse["run_a"];
  label: string;
}) {
  const t = useTranslations("evaluations.runComparison");
  const statusColor =
    run.status === "completed"
      ? "text-emerald-700 bg-emerald-50"
      : run.status === "failed"
        ? "text-red-700 bg-red-50"
        : "text-gray-700 bg-gray-50";

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-gray-700">{label}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor}`}
        >
          {["completed", "failed", "running", "queued", "cancelled"].includes(
            run.status,
          )
            ? t(`runStatus.${run.status}`)
            : run.status}
        </span>
      </div>
      <p className="mt-1 truncate text-xs text-gray-500">
        {run.run_name ?? run.evaluation_run_id}
      </p>
      {run.started_at && (
        <p className="mt-0.5 text-xs text-gray-400">
          {t("started", { date: new Date(run.started_at).toLocaleString() })}
        </p>
      )}
    </div>
  );
}
