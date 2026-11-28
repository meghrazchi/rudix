import { useState } from "react";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { ChunkingComparisonPanel } from "@/components/evaluations/chunking-comparison-panel";
import { MultilingualEvalPanel } from "@/components/evaluations/multilingual-eval-panel";
import { EmptyState } from "@/components/states/EmptyState";
import type { EvaluationRunDetailResponse } from "@/lib/api/evaluations";
import type {
  EvaluationCaseView,
  ResultFilters,
  RunComparison,
} from "@/components/evaluations/evaluation-view-model";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  runStatusScreenReaderText,
} from "@/components/evaluations/evaluation-view-model";
import { EvaluationStatusBadge } from "@/components/evaluations/evaluation-ui";
import { buildPipelineExplorerHref } from "@/lib/pipeline-links";

type RunDetailSectionProps = {
  run: EvaluationRunDetailResponse;
  datasetName: string;
  comparison: RunComparison;
  failureReason: string | null;
  failureType: string | null;
};

function formatLatency(value: number | null | undefined, na: string): string {
  if (value == null || !Number.isFinite(value)) {
    return na;
  }
  return `${Math.round(value)} ms`;
}

function citationHref(caseRow: EvaluationCaseView): string | null {
  if (caseRow.citations.length > 0 && caseRow.citations[0].documentId) {
    const citation = caseRow.citations[0];
    return `/documents/${encodeURIComponent(citation.documentId ?? "")}?chunk_id=${encodeURIComponent(citation.chunkId ?? "")}&back=${encodeURIComponent("/evaluations")}`;
  }

  if (caseRow.expectedDocumentId) {
    return `/documents/${encodeURIComponent(caseRow.expectedDocumentId)}?back=${encodeURIComponent("/evaluations")}`;
  }

  return null;
}

function StatusSummary({
  run,
  datasetName,
}: {
  run: EvaluationRunDetailResponse;
  datasetName: string;
}) {
  const t = useTranslations("evaluations.runDetail");
  const started = run.started_at ?? run.created_at;
  const durationMs =
    run.completed_at && started
      ? Math.max(0, Date.parse(run.completed_at) - Date.parse(started))
      : null;

  return (
    <dl className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.runId")}
        </dt>
        <dd className="font-medium text-[#312b4c]">{run.evaluation_run_id}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.dataset")}
        </dt>
        <dd className="font-medium text-[#312b4c]">{datasetName}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.started")}
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(started)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.completed")}
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(run.completed_at)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.duration")}
        </dt>
        <dd className="text-[#4a4565]">{formatDuration(durationMs)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          {t("summary.updated")}
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(run.updated_at)}</dd>
      </div>
    </dl>
  );
}

function ComparisonCard({ comparison }: { comparison: RunComparison }) {
  const t = useTranslations("evaluations.runDetail");
  if (!comparison.available) {
    return (
      <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
        <h3 className="text-sm font-semibold text-[#2f2a48]">
          {t("comparison.baseline")}
        </h3>
        <p className="mt-2 text-sm text-[#67627f]">{comparison.message}</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">
        {t("comparison.baselineVsLatest")}
      </h3>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-[#e7e3f3] bg-white p-2">
          <p className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {comparison.baselineLabel}
          </p>
          <p className="text-lg font-semibold text-[#2f2a48]">
            {formatPercent(comparison.baselineScore)}
          </p>
        </div>
        <div className="rounded-lg border border-[#e7e3f3] bg-white p-2">
          <p className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {comparison.latestLabel}
          </p>
          <p className="text-lg font-semibold text-[#2f2a48]">
            {formatPercent(comparison.latestScore)}
          </p>
        </div>
        <div className="rounded-lg border border-[#e7e3f3] bg-white p-2">
          <p className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {t("comparison.delta")}
          </p>
          <p className="text-lg font-semibold text-[#2f2a48]">
            {formatPercent(comparison.delta)}
          </p>
        </div>
      </div>
      <p className="mt-2 text-xs text-[#6a6581]">{comparison.message}</p>
    </section>
  );
}

function CasesFilterBar({
  filters,
  onChange,
}: {
  filters: ResultFilters;
  onChange: (next: ResultFilters) => void;
}) {
  const t = useTranslations("evaluations.runDetail.filters");
  return (
    <div className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3 lg:grid-cols-4">
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase lg:col-span-2">
        {t("searchCases")}
        <input
          type="search"
          value={filters.query}
          onChange={(event) =>
            onChange({ ...filters, query: event.target.value })
          }
          placeholder={t("searchPlaceholder")}
          className="h-9 rounded-lg border border-[#d1cce4] bg-white px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
        />
      </label>
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase">
        {t("caseStatus")}
        <select
          value={filters.status}
          onChange={(event) =>
            onChange({
              ...filters,
              status: event.target.value as ResultFilters["status"],
            })
          }
          className="h-9 rounded-lg border border-[#d1cce4] bg-white px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
        >
          <option value="all">{t("all")}</option>
          <option value="failed">{t("failed")}</option>
          <option value="low_quality">{t("lowQuality")}</option>
          <option value="completed">{t("completed")}</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase">
        {t("sort")}
        <select
          value={filters.sortBy}
          onChange={(event) =>
            onChange({
              ...filters,
              sortBy: event.target.value as ResultFilters["sortBy"],
            })
          }
          className="h-9 rounded-lg border border-[#d1cce4] bg-white px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
        >
          <option value="created_desc">{t("newest")}</option>
          <option value="latency_desc">{t("latencyDesc")}</option>
          <option value="latency_asc">{t("latencyAsc")}</option>
          <option value="quality_desc">{t("qualityDesc")}</option>
          <option value="quality_asc">{t("qualityAsc")}</option>
        </select>
      </label>
    </div>
  );
}

function CaseRow({ row }: { row: EvaluationCaseView }) {
  const t = useTranslations("evaluations.runDetail");
  const [expanded, setExpanded] = useState(false);
  const status = row.result.status.trim().toLowerCase();
  const link = citationHref(row);
  const failure = row.result.failure_reason;

  return (
    <article
      className={`rounded-lg border p-3 ${
        status === "failed" || row.isLowQuality
          ? "border-rose-200 bg-rose-50"
          : "border-[#e7e3f3] bg-white"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#2f2a48]">
            {row.result.question}
          </p>
          <p className="mt-1 text-xs text-[#66627d]">
            {t("case.expected", {
              value: row.expectedAnswer ?? t("case.unavailable"),
            })}
          </p>
          <p className="text-xs text-[#66627d]">
            {t("case.actual", {
              value: row.result.generated_answer ?? t("case.unavailable"),
            })}
          </p>
        </div>
        <div className="text-right">
          <EvaluationStatusBadge
            status={
              status === "queued" ||
              status === "running" ||
              status === "completed" ||
              status === "failed" ||
              status === "cancelled"
                ? status
                : "unknown"
            }
          />
          <span className="sr-only">
            {runStatusScreenReaderText(
              status === "queued" ||
                status === "running" ||
                status === "completed" ||
                status === "failed" ||
                status === "cancelled"
                ? status
                : "unknown",
            )}
          </span>
          <p className="mt-1 text-xs text-[#66627d]">
            {t("case.quality", { value: formatPercent(row.qualityScore) })}
          </p>
          <p className="text-xs text-[#66627d]">
            {t("case.confidence", {
              value: formatPercent(row.confidenceScore),
            })}
          </p>
        </div>
      </div>

      <div className="mt-2 grid gap-2 text-xs text-[#4f4a69] sm:grid-cols-4">
        <p>
          {t("case.latency", {
            value: formatLatency(row.result.latency_ms, t("na")),
          })}
        </p>
        <p>
          {t("case.citationAccuracy", {
            value: formatPercent(row.result.citation_accuracy_score),
          })}
        </p>
        <p>
          {t("case.retrieval", {
            value: formatPercent(row.result.retrieval_score),
          })}
        </p>
        <p>
          {t("case.faithfulness", {
            value: formatPercent(row.result.faithfulness_score),
          })}
        </p>
      </div>

      {failure ? (
        <p className="mt-2 rounded border border-rose-200 bg-rose-100 px-2 py-1 text-xs text-rose-900">
          {failure}
          {row.result.failure_type ? ` (${row.result.failure_type})` : ""}
        </p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {link ? (
          <Link
            href={link}
            className="rounded border border-[#c8c2df] bg-white px-2 py-1 text-xs font-semibold text-[#3f3a5e] hover:bg-[#f3f0fb]"
          >
            {t("case.openSource")}
          </Link>
        ) : (
          <span className="rounded border border-[#d8d3e7] bg-[#f8f7fc] px-2 py-1 text-xs text-[#7e7a95]">
            {t("case.linkUnavailable")}
          </span>
        )}

        <button
          type="button"
          onClick={() => setExpanded((previous) => !previous)}
          className="rounded border border-[#c8c2df] bg-white px-2 py-1 text-xs font-semibold text-[#3f3a5e] hover:bg-[#f3f0fb]"
        >
          {expanded ? t("case.hideDetails") : t("case.showDetails")}
        </button>
      </div>

      {expanded ? (
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          <div className="rounded border border-[#e5e1f2] bg-[#fbfaff] p-2">
            <p className="text-xs font-semibold tracking-wide text-[#68647f] uppercase">
              {t("case.retrievedCitations")}
            </p>
            {row.citations.length === 0 ? (
              <p className="mt-1 text-xs text-[#6f6b87]">
                {t("case.noCitationPayload")}
              </p>
            ) : (
              <ul className="mt-1 space-y-1 text-xs text-[#4f4a69]">
                {row.citations.map((citation, index) => (
                  <li key={`${citation.chunkId ?? "chunk"}:${index + 1}`}>
                    {(citation.filename ?? t("case.unknownDocument")) +
                      (citation.pageNumber != null
                        ? ` • ${t("case.page", { page: citation.pageNumber })}`
                        : "")}
                    {citation.score != null
                      ? ` • ${t("case.score", { score: citation.score.toFixed(2) })}`
                      : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded border border-[#e5e1f2] bg-[#fbfaff] p-2">
            <p className="text-xs font-semibold tracking-wide text-[#68647f] uppercase">
              {t("case.errorPayload")}
            </p>
            <pre className="mt-1 max-h-44 overflow-auto text-[11px] text-[#4f4a69]">
              {JSON.stringify(
                {
                  failure_reason: row.result.failure_reason,
                  failure_type: row.result.failure_type,
                  metrics: row.result.metrics,
                  details: row.result.details,
                },
                null,
                2,
              )}
            </pre>
          </div>
        </div>
      ) : null}
    </article>
  );
}

type ModelProfileMeta = {
  provider_type?: string | null;
  base_model?: string | null;
  source?: string | null;
  task_type?: string | null;
  is_local?: boolean | null;
};

function extractModelProfile(
  summary: Record<string, unknown> | null | undefined,
): ModelProfileMeta | null {
  if (!summary || typeof summary !== "object") return null;
  const mp = summary["model_profile"];
  if (!mp || typeof mp !== "object") return null;
  return mp as ModelProfileMeta;
}

function ModelProfileCard({
  summary,
}: {
  summary: Record<string, unknown> | null | undefined;
}) {
  const t = useTranslations("evaluations.runDetail.modelProfile");
  const mp = extractModelProfile(summary);
  if (!mp) return null;

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">{t("title")}</h3>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {t("provider")}
          </dt>
          <dd className="font-medium text-[#312b4c]">
            {mp.provider_type ?? "—"}
            {mp.is_local ? (
              <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
                {t("local")}
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {t("baseModel")}
          </dt>
          <dd className="font-medium text-[#312b4c]">{mp.base_model ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            {t("source")}
          </dt>
          <dd className="text-[#4a4565]">{mp.source ?? "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

function ProviderProfileCard({ run }: { run: EvaluationRunDetailResponse }) {
  const t = useTranslations("evaluations.runDetail.localMetrics");
  const summary = run.summary ?? {};
  const invalidJsonRate =
    typeof summary["invalid_json_rate"] === "number"
      ? summary["invalid_json_rate"]
      : null;
  const timeoutRate =
    typeof summary["timeout_rate"] === "number"
      ? summary["timeout_rate"]
      : null;
  const fallbackFrequency =
    typeof summary["fallback_frequency"] === "number"
      ? summary["fallback_frequency"]
      : null;

  const hasLocalMetrics =
    invalidJsonRate != null || timeoutRate != null || fallbackFrequency != null;

  if (!hasLocalMetrics) {
    return null;
  }

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">{t("title")}</h3>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
        {invalidJsonRate != null && (
          <div>
            <dt className="text-xs text-[#6b6682]">{t("invalidJson")}</dt>
            <dd
              className={`font-medium tabular-nums ${
                invalidJsonRate > 0.05 ? "text-red-600" : "text-[#312b4c]"
              }`}
            >
              {(invalidJsonRate * 100).toFixed(1)}%
            </dd>
          </div>
        )}
        {timeoutRate != null && (
          <div>
            <dt className="text-xs text-[#6b6682]">{t("timeout")}</dt>
            <dd
              className={`font-medium tabular-nums ${
                timeoutRate > 0.1 ? "text-red-600" : "text-[#312b4c]"
              }`}
            >
              {(timeoutRate * 100).toFixed(1)}%
            </dd>
          </div>
        )}
        {fallbackFrequency != null && (
          <div>
            <dt className="text-xs text-[#6b6682]">{t("fallback")}</dt>
            <dd
              className={`font-medium tabular-nums ${
                fallbackFrequency > 0.15 ? "text-amber-700" : "text-[#312b4c]"
              }`}
            >
              {(fallbackFrequency * 100).toFixed(1)}%
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}

export function EvaluationRunDetailSection({
  run,
  datasetName,
  comparison,
  failureReason,
  failureType,
}: RunDetailSectionProps) {
  const t = useTranslations("evaluations.runDetail");
  const runStatus = run.status.trim().toLowerCase();
  const statusForBadge =
    runStatus === "queued" ||
    runStatus === "running" ||
    runStatus === "completed" ||
    runStatus === "failed" ||
    runStatus === "cancelled"
      ? runStatus
      : "unknown";

  return (
    <section
      aria-label={t("detail.ariaLabel")}
      className="space-y-3 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-[#292442]">
          {t("detail.ariaLabel")}
        </h2>
        <div className="flex items-center gap-2">
          <EvaluationStatusBadge status={statusForBadge} />
          <Link
            href={buildPipelineExplorerHref({
              runType: "evaluation.run",
              evaluationRunId: run.evaluation_run_id,
            })}
            className="rounded border border-[#cfc9e4] bg-white px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            {t("detail.openTrace")}
          </Link>
        </div>
      </div>

      <p className="text-sm text-[#65617c]">
        {t("detail.dataset", { name: datasetName })}
      </p>
      <StatusSummary run={run} datasetName={datasetName} />
      <ModelProfileCard summary={run.summary} />
      <ProviderProfileCard run={run} />

      {failureReason ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {failureReason}
          {failureType ? ` (${failureType})` : ""}
        </p>
      ) : null}

      <ComparisonCard comparison={comparison} />
      <ChunkingComparisonPanel summaryValue={run.summary} />

      {run.status === "completed" && (
        <section aria-label={t("detail.multilingualAria")}>
          <h3 className="mb-2 text-sm font-semibold text-[#2f2a48]">
            {t("detail.qualityByLanguage")}
          </h3>
          <MultilingualEvalPanel evaluationRunId={run.evaluation_run_id} />
        </section>
      )}
    </section>
  );
}

export function EvaluationCasesSection({
  rows,
  filters,
  onFilterChange,
}: {
  rows: EvaluationCaseView[];
  filters: ResultFilters;
  onFilterChange: (next: ResultFilters) => void;
}) {
  const t = useTranslations("evaluations.runDetail");
  return (
    <section
      aria-label={t("cases.ariaLabel")}
      className="space-y-3 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-[#292442]">
          {t("cases.title")}
        </h2>
        <p className="text-sm text-[#66627d]">
          {t("cases.showing", { count: rows.length })}
        </p>
      </div>

      <CasesFilterBar filters={filters} onChange={onFilterChange} />

      {rows.length === 0 ? (
        <EmptyState
          compact
          title={t("cases.emptyTitle")}
          description={t("cases.emptyDescription")}
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <CaseRow key={row.result.evaluation_result_id} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

export function EvaluationRunDetailSkeleton() {
  return (
    <section className="space-y-2 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm">
      {Array.from({ length: 5 }).map((_, index) => (
        <div
          key={`run-detail-skeleton-${index + 1}`}
          className="h-10 animate-pulse rounded bg-[#f1eef8]"
        />
      ))}
    </section>
  );
}
