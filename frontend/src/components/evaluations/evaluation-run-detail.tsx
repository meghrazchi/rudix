import { useState } from "react";

import Link from "next/link";

import { ChunkingComparisonPanel } from "@/components/evaluations/chunking-comparison-panel";
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
  formatInteger,
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

function formatLatency(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
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
  const started = run.started_at ?? run.created_at;
  const durationMs =
    run.completed_at && started
      ? Math.max(0, Date.parse(run.completed_at) - Date.parse(started))
      : null;

  return (
    <dl className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Run ID
        </dt>
        <dd className="font-medium text-[#312b4c]">{run.evaluation_run_id}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Dataset
        </dt>
        <dd className="font-medium text-[#312b4c]">{datasetName}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Started
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(started)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Completed
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(run.completed_at)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Duration
        </dt>
        <dd className="text-[#4a4565]">{formatDuration(durationMs)}</dd>
      </div>
      <div>
        <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
          Updated
        </dt>
        <dd className="text-[#4a4565]">{formatDateTime(run.updated_at)}</dd>
      </div>
    </dl>
  );
}

function ComparisonCard({ comparison }: { comparison: RunComparison }) {
  if (!comparison.available) {
    return (
      <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
        <h3 className="text-sm font-semibold text-[#2f2a48]">
          Baseline comparison
        </h3>
        <p className="mt-2 text-sm text-[#67627f]">{comparison.message}</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">
        Baseline vs latest
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
            Delta
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
  return (
    <div className="grid gap-2 rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3 lg:grid-cols-4">
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase lg:col-span-2">
        Search cases
        <input
          type="search"
          value={filters.query}
          onChange={(event) =>
            onChange({ ...filters, query: event.target.value })
          }
          placeholder="Question, expected answer, actual answer"
          className="h-9 rounded-lg border border-[#d1cce4] bg-white px-2 text-sm font-medium tracking-normal text-[#2a2640] normal-case"
        />
      </label>
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase">
        Case status
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
          <option value="all">All</option>
          <option value="failed">Failed</option>
          <option value="low_quality">Low quality</option>
          <option value="completed">Completed</option>
        </select>
      </label>
      <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#615c7a] uppercase">
        Sort
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
          <option value="created_desc">Newest first</option>
          <option value="latency_desc">Latency high to low</option>
          <option value="latency_asc">Latency low to high</option>
          <option value="quality_desc">Quality high to low</option>
          <option value="quality_asc">Quality low to high</option>
        </select>
      </label>
    </div>
  );
}

function CaseRow({ row }: { row: EvaluationCaseView }) {
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
            Expected: {row.expectedAnswer ?? "Unavailable"}
          </p>
          <p className="text-xs text-[#66627d]">
            Actual: {row.result.generated_answer ?? "Unavailable"}
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
            Quality {formatPercent(row.qualityScore)}
          </p>
          <p className="text-xs text-[#66627d]">
            Confidence {formatPercent(row.confidenceScore)}
          </p>
        </div>
      </div>

      <div className="mt-2 grid gap-2 text-xs text-[#4f4a69] sm:grid-cols-4">
        <p>Latency: {formatLatency(row.result.latency_ms)}</p>
        <p>
          Citation accuracy: {formatPercent(row.result.citation_accuracy_score)}
        </p>
        <p>Retrieval: {formatPercent(row.result.retrieval_score)}</p>
        <p>Faithfulness: {formatPercent(row.result.faithfulness_score)}</p>
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
            Open source document
          </Link>
        ) : (
          <span className="rounded border border-[#d8d3e7] bg-[#f8f7fc] px-2 py-1 text-xs text-[#7e7a95]">
            Citation link unavailable
          </span>
        )}

        <button
          type="button"
          onClick={() => setExpanded((previous) => !previous)}
          className="rounded border border-[#c8c2df] bg-white px-2 py-1 text-xs font-semibold text-[#3f3a5e] hover:bg-[#f3f0fb]"
        >
          {expanded ? "Hide details" : "Show details"}
        </button>
      </div>

      {expanded ? (
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          <div className="rounded border border-[#e5e1f2] bg-[#fbfaff] p-2">
            <p className="text-xs font-semibold tracking-wide text-[#68647f] uppercase">
              Retrieved citations
            </p>
            {row.citations.length === 0 ? (
              <p className="mt-1 text-xs text-[#6f6b87]">
                No citation payload available.
              </p>
            ) : (
              <ul className="mt-1 space-y-1 text-xs text-[#4f4a69]">
                {row.citations.map((citation, index) => (
                  <li key={`${citation.chunkId ?? "chunk"}:${index + 1}`}>
                    {(citation.filename ?? "Unknown document") +
                      (citation.pageNumber != null
                        ? ` • page ${citation.pageNumber}`
                        : "")}
                    {citation.score != null
                      ? ` • score ${citation.score.toFixed(2)}`
                      : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded border border-[#e5e1f2] bg-[#fbfaff] p-2">
            <p className="text-xs font-semibold tracking-wide text-[#68647f] uppercase">
              Error and metrics payload
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
  const mp = extractModelProfile(summary);
  if (!mp) return null;

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">Model profile</h3>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            Provider
          </dt>
          <dd className="font-medium text-[#312b4c]">
            {mp.provider_type ?? "—"}
            {mp.is_local ? (
              <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
                local
              </span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            Base model
          </dt>
          <dd className="font-medium text-[#312b4c]">{mp.base_model ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            Source
          </dt>
          <dd className="text-[#4a4565]">{mp.source ?? "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

const PROVIDER_PROFILE_LABEL: Record<string, string> = {
  cloud_baseline: "Cloud Baseline",
  local_profile: "Local Profile",
  fallback_profile: "Fallback Profile",
};

function ProviderProfileCard({ run }: { run: EvaluationRunDetailResponse }) {
  const providerType = run.provider_type;
  const providerProfile = run.provider_profile;
  const modelProfileKey = run.model_profile_key;

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

  if (!providerType && !providerProfile && !hasLocalMetrics) {
    return null;
  }

  const profileLabel = providerProfile
    ? (PROVIDER_PROFILE_LABEL[providerProfile] ?? providerProfile)
    : null;
  const isLocal = providerProfile === "local_profile";

  return (
    <section className="rounded-xl border border-[#ddd8ec] bg-[#fcfbff] p-3">
      <h3 className="text-sm font-semibold text-[#2f2a48]">
        Provider &amp; profile
      </h3>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
        {providerType && (
          <div>
            <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
              Provider
            </dt>
            <dd className="font-medium text-[#312b4c]">
              {providerType}
              {isLocal && (
                <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
                  local
                </span>
              )}
            </dd>
          </div>
        )}
        {profileLabel && (
          <div>
            <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
              Profile label
            </dt>
            <dd className="font-medium text-[#312b4c]">{profileLabel}</dd>
          </div>
        )}
        {modelProfileKey && (
          <div>
            <dt className="text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
              Task profile
            </dt>
            <dd className="text-[#4a4565]">{modelProfileKey}</dd>
          </div>
        )}
      </dl>
      {hasLocalMetrics && (
        <div className="mt-3 border-t border-[#ddd8ec] pt-2">
          <p className="mb-1.5 text-xs font-semibold tracking-wide text-[#6b6682] uppercase">
            Local model metrics
          </p>
          <dl className="grid gap-2 text-sm sm:grid-cols-3">
            {invalidJsonRate != null && (
              <div>
                <dt className="text-xs text-[#6b6682]">Invalid JSON rate</dt>
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
                <dt className="text-xs text-[#6b6682]">Timeout rate</dt>
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
                <dt className="text-xs text-[#6b6682]">Fallback frequency</dt>
                <dd
                  className={`font-medium tabular-nums ${
                    fallbackFrequency > 0.15
                      ? "text-amber-700"
                      : "text-[#312b4c]"
                  }`}
                >
                  {(fallbackFrequency * 100).toFixed(1)}%
                </dd>
              </div>
            )}
          </dl>
        </div>
      )}
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
      aria-label="Run detail"
      className="space-y-3 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-[#292442]">Run detail</h2>
        <div className="flex items-center gap-2">
          <EvaluationStatusBadge status={statusForBadge} />
          <Link
            href={buildPipelineExplorerHref({
              runType: "evaluation.run",
              evaluationRunId: run.evaluation_run_id,
            })}
            className="rounded border border-[#cfc9e4] bg-white px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Open pipeline trace
          </Link>
        </div>
      </div>

      <p className="text-sm text-[#65617c]">Dataset: {datasetName}</p>
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
  return (
    <section
      aria-label="Run case results"
      className="space-y-3 rounded-2xl border border-[#d8d4e8] bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-[#292442]">Case results</h2>
        <p className="text-sm text-[#66627d]">
          Showing {formatInteger(rows.length)} case
          {rows.length === 1 ? "" : "s"}
        </p>
      </div>

      <CasesFilterBar filters={filters} onChange={onFilterChange} />

      {rows.length === 0 ? (
        <EmptyState
          compact
          title="No cases match the selected filters."
          description="Change case filters to inspect failed, low-quality, or completed answers."
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
