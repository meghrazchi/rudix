import Link from "next/link";

import { EmptyState } from "@/components/states/EmptyState";
import type {
  EvaluationRunListItem,
  EvaluationRunStatus,
  RunFilters,
} from "@/components/evaluations/evaluation-view-model";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  runStatusLabel,
  runStatusScreenReaderText,
} from "@/components/evaluations/evaluation-view-model";

type KpiTone = "default" | "good" | "warn" | "bad";
type KpiTrendTone = "good" | "warn" | "bad" | "muted";
type KpiSparkline = "rise" | "flat" | "drop" | "wave";

export type EvaluationKpiItem = {
  id: string;
  label: string;
  value: string;
  helper: string;
  tone?: KpiTone;
  unavailable?: boolean;
  trendLabel?: string;
  trendTone?: KpiTrendTone;
  sparkline?: KpiSparkline;
};

export type EvaluationSetOverviewRow = {
  setId: string;
  name: string;
  author: string;
  questionCount: number;
  latencyMs: number | null;
  score: number | null;
  statusLabel: string;
  statusTone: "good" | "warn" | "bad" | "muted";
};

type EvaluationPageHeaderProps = {
  canRun: boolean;
  canCreateSet: boolean;
  onStartRun: () => void;
  onCreateSet: () => void;
  runDisabledReason?: string | null;
};

type SetsOverviewTableProps = {
  rows: EvaluationSetOverviewRow[];
  selectedSetId: string | null;
  canCreateSet: boolean;
  onSelectSet: (setId: string) => void;
  onCreateSet: () => void;
};

type RecentRunItem = {
  runId: string;
  runName: string;
  status: EvaluationRunStatus;
  createdAt: string;
  durationMs: number | null;
  modelLabel: string | null;
  rerankerLabel: string | null;
};

type RecentRunsPanelProps = {
  items: RecentRunItem[];
  activeRunId: string | null;
  onSelectRun: (runId: string) => void;
};

type InsightsRowProps = {
  retrievalP95Ms: number | null;
  generationP95Ms: number | null;
  hallucinationRisk: number | null;
  hallucinationRiskDelta: number | null;
  nextRunLabel: string;
  nextRunEta: string;
  onTriggerRun: () => void;
  triggerDisabled: boolean;
};

const STATUS_COLOR_BY_VALUE: Record<EvaluationRunStatus, string> = {
  queued: "border-amber-200 bg-amber-50 text-amber-800",
  running: "border-blue-200 bg-blue-50 text-blue-800",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
  failed: "border-rose-200 bg-rose-50 text-rose-800",
  cancelled: "border-zinc-300 bg-zinc-100 text-zinc-800",
  unknown: "border-slate-300 bg-slate-100 text-slate-700",
};

const SET_STATUS_CLASS: Record<EvaluationSetOverviewRow["statusTone"], string> =
  {
    good: "border-emerald-100 bg-emerald-50 text-emerald-700",
    warn: "border-amber-100 bg-amber-50 text-amber-700",
    bad: "border-rose-100 bg-rose-50 text-rose-700",
    muted: "border-slate-200 bg-slate-50 text-slate-600",
  };

const KPI_TONE_CLASS: Record<KpiTone, string> = {
  default: "border-gray-200 bg-white",
  good: "border-emerald-100 bg-white",
  warn: "border-amber-100 bg-white",
  bad: "border-rose-100 bg-white",
};

const KPI_TREND_CLASS: Record<KpiTrendTone, string> = {
  good: "bg-emerald-50 text-emerald-600",
  warn: "bg-amber-50 text-amber-600",
  bad: "bg-rose-50 text-rose-600",
  muted: "bg-gray-100 text-gray-500",
};

function statusBadgeClass(status: EvaluationRunStatus): string {
  return `inline-flex items-center rounded border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${STATUS_COLOR_BY_VALUE[status]}`;
}

function asRoundedMs(value: number | null): string {
  if (value == null || !Number.isFinite(value)) {
    return "N/A";
  }
  return `${Math.round(value)}ms`;
}

function scoreBar(score: number | null): {
  good: string;
  warn: string;
  bad: string;
} {
  if (score == null || !Number.isFinite(score)) {
    return { good: "0%", warn: "0%", bad: "0%" };
  }

  const normalized = Math.max(0, Math.min(1, score > 1 ? score / 100 : score));
  const good = Math.min(85, Math.round(normalized * 100));
  const warn = Math.max(0, Math.min(40, 95 - good));
  const bad = Math.max(0, 100 - good - warn);

  return {
    good: `${good}%`,
    warn: `${warn}%`,
    bad: `${bad}%`,
  };
}

function sparklinePath(kind: KpiSparkline): string {
  if (kind === "drop") {
    return "M0 6 Q 30 12, 60 10 T 100 24";
  }
  if (kind === "flat") {
    return "M0 22 L 20 22 L 40 18 L 60 20 L 80 12 L 100 11";
  }
  if (kind === "wave") {
    return "M0 20 C 20 16, 40 10, 60 8 S 80 16, 100 12";
  }
  return "M0 24 Q 25 20, 50 14 T 100 5";
}

function timeAgoLabel(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return "Unknown";
  }

  const deltaMs = Math.max(0, Date.now() - timestamp);
  const deltaMinutes = Math.floor(deltaMs / 60_000);
  if (deltaMinutes < 1) {
    return "just now";
  }
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours}h ago`;
  }
  const deltaDays = Math.floor(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function runIconTone(status: EvaluationRunStatus): string {
  if (status === "running" || status === "queued") {
    return "bg-indigo-50 text-indigo-600";
  }
  if (status === "completed") {
    return "bg-emerald-50 text-emerald-600";
  }
  if (status === "failed") {
    return "bg-rose-50 text-rose-600";
  }
  return "bg-gray-100 text-gray-500";
}

function statusGlyph(status: EvaluationRunStatus): string {
  if (status === "running" || status === "queued") {
    return "▶";
  }
  if (status === "completed") {
    return "✓";
  }
  if (status === "failed") {
    return "!";
  }
  return "○";
}

function trendText(delta: number | null): string {
  if (delta == null || !Number.isFinite(delta)) {
    return "Stable";
  }
  if (delta > 0) {
    return `+${(delta * 100).toFixed(1)}%`;
  }
  if (delta < 0) {
    return `${(delta * 100).toFixed(1)}%`;
  }
  return "Stable";
}

export function EvaluationStatusBadge({
  status,
}: {
  status: EvaluationRunStatus;
}) {
  return (
    <span className={statusBadgeClass(status)}>{runStatusLabel(status)}</span>
  );
}

export function EvaluationsPageHeader({
  canRun,
  canCreateSet,
  onStartRun,
  onCreateSet,
  runDisabledReason,
}: EvaluationPageHeaderProps) {
  return (
    <header className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            Track RAG quality before shipping answers
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Measure retrieval, grounding, citations, latency, and cost to catch
            weak answers before production.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onStartRun}
            disabled={!canRun}
            title={
              !canRun ? (runDisabledReason ?? "Action restricted") : undefined
            }
            className="rounded-lg bg-[#4f46e5] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-[#4338ca] disabled:cursor-not-allowed disabled:opacity-60"
          >
            Start evaluation run
          </button>
          {canCreateSet ? (
            <button
              type="button"
              onClick={onCreateSet}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
            >
              New Set
            </button>
          ) : null}
          <Link
            href="/rag-pipeline"
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Pipeline Explorer
          </Link>
        </div>
      </div>

      {!canRun ? (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Your role can review evaluation results but only owner/admin can start
          new runs.
        </p>
      ) : null}
    </header>
  );
}

export function EvaluationKpiGrid({ items }: { items: EvaluationKpiItem[] }) {
  return (
    <section
      aria-label="Evaluation summary KPIs"
      className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4"
    >
      {items.map((item) => {
        const tone = item.tone ?? "default";
        const trendTone = item.trendTone ?? "muted";
        const sparkline = item.sparkline ?? "rise";

        return (
          <article
            key={item.id}
            className={`rounded-xl border p-5 shadow-sm ${KPI_TONE_CLASS[tone]}`}
          >
            <div className="mb-4 flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-gray-500">{item.label}</p>
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ${KPI_TREND_CLASS[trendTone]}`}
              >
                {item.trendLabel ?? item.helper}
              </span>
            </div>

            <div className="flex items-end justify-between gap-3">
              <p className="text-3xl font-bold text-gray-900">{item.value}</p>
              <div className="h-8 w-24">
                <svg className="h-full w-full" viewBox="0 0 100 30" fill="none">
                  <path
                    d={sparklinePath(sparkline)}
                    stroke="#4f46e5"
                    strokeWidth="3"
                    strokeLinecap="round"
                  />
                </svg>
              </div>
            </div>

            {item.unavailable ? (
              <p className="mt-2 text-xs text-gray-500">
                Unavailable in current payload.
              </p>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}

export function EvaluationSetsOverviewTable({
  rows,
  selectedSetId,
  canCreateSet,
  onSelectSet,
  onCreateSet,
}: SetsOverviewTableProps) {
  if (rows.length === 0) {
    return (
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-6 py-5">
          <h2 className="text-lg font-bold text-gray-800">Evaluation Sets</h2>
        </div>
        <div className="p-5">
          <EmptyState
            compact
            title="No evaluation sets yet"
            description="Create a set to start evaluating answer quality and regressions."
          />
        </div>
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-6 py-5">
        <h2 className="text-lg font-bold text-gray-800">Evaluation Sets</h2>
        {canCreateSet ? (
          <button
            type="button"
            onClick={onCreateSet}
            className="rounded-lg bg-[#4f46e5] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
          >
            New Set
          </button>
        ) : null}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left">
          <thead className="bg-gray-50 text-[10px] font-bold tracking-wider text-gray-500 uppercase">
            <tr>
              <th className="px-6 py-3">Name</th>
              <th className="px-6 py-3">Author</th>
              <th className="px-6 py-3">Questions</th>
              <th className="px-6 py-3">P95 Latency</th>
              <th className="px-6 py-3">Score</th>
              <th className="px-6 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 text-sm">
            {rows.map((row) => {
              const bars = scoreBar(row.score);
              const isSelected = row.setId === selectedSetId;

              return (
                <tr
                  key={row.setId}
                  className={`transition-colors hover:bg-gray-50 ${
                    isSelected ? "bg-indigo-50/40" : "bg-white"
                  }`}
                >
                  <td className="px-6 py-4 align-top">
                    <button
                      type="button"
                      onClick={() => onSelectSet(row.setId)}
                      className="text-left"
                    >
                      <span className="block max-w-[220px] truncate font-semibold text-gray-800">
                        {row.name}
                      </span>
                    </button>
                  </td>
                  <td className="px-6 py-4 align-top text-gray-600">
                    {row.author}
                  </td>
                  <td className="px-6 py-4 align-top text-gray-600">
                    {row.questionCount}
                  </td>
                  <td className="px-6 py-4 align-top text-gray-600">
                    {asRoundedMs(row.latencyMs)}
                  </td>
                  <td className="px-6 py-4 align-top">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-gray-900">
                        {formatPercent(row.score)}
                      </span>
                      <span className="flex h-1.5 w-16 overflow-hidden rounded-full bg-gray-100">
                        <span
                          className="h-full bg-emerald-500"
                          style={{ width: bars.good }}
                        />
                        <span
                          className="h-full bg-amber-400"
                          style={{ width: bars.warn }}
                        />
                        <span
                          className="h-full bg-rose-400"
                          style={{ width: bars.bad }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4 align-top">
                    <span
                      className={`rounded border px-2 py-1 text-[10px] font-bold tracking-tight uppercase ${
                        SET_STATUS_CLASS[row.statusTone]
                      }`}
                    >
                      {row.statusLabel}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function RecentRunsPanel({
  items,
  activeRunId,
  onSelectRun,
}: RecentRunsPanelProps) {
  return (
    <section className="flex h-full flex-col rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 px-6 py-5">
        <h2 className="text-lg font-bold text-gray-800">Recent Runs</h2>
      </div>

      <div className="flex-1 space-y-3 p-4">
        {items.length === 0 ? (
          <EmptyState
            compact
            title="No runs yet"
            description="Queue a run to start tracking quality changes."
          />
        ) : (
          items.map((item) => {
            const isActive = item.runId === activeRunId;
            const iconTone = runIconTone(item.status);

            return (
              <button
                key={item.runId}
                type="button"
                onClick={() => onSelectRun(item.runId)}
                className={`flex w-full items-start gap-3 rounded-lg p-3 text-left transition-colors ${
                  isActive ? "bg-indigo-50/40" : "hover:bg-gray-50"
                }`}
              >
                <span
                  className={`mt-1 inline-flex h-9 w-9 items-center justify-center rounded ${iconTone}`}
                  aria-hidden="true"
                >
                  <span className="text-sm font-bold">
                    {statusGlyph(item.status)}
                  </span>
                </span>

                <span className="min-w-0 flex-1">
                  <span className="mb-1 flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-bold text-gray-900">
                      {item.runName}
                    </span>
                    <span className="text-[10px] font-medium text-gray-400">
                      {timeAgoLabel(item.createdAt)}
                    </span>
                  </span>

                  <span className="mb-2 flex items-center gap-3 text-[10px] text-gray-500">
                    <span>{formatDuration(item.durationMs)}</span>
                    <span className="font-mono">id: {item.runId}</span>
                  </span>

                  <span className="flex flex-wrap gap-1.5">
                    {item.modelLabel ? (
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                        {item.modelLabel}
                      </span>
                    ) : null}
                    {item.rerankerLabel ? (
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                        {item.rerankerLabel}
                      </span>
                    ) : null}
                  </span>
                </span>
              </button>
            );
          })
        )}
      </div>

      <div className="border-t border-gray-100">
        <a
          href="#evaluation-inspector"
          className="block w-full py-4 text-center text-sm font-semibold text-indigo-600 hover:bg-gray-50"
        >
          View all runs
        </a>
      </div>
    </section>
  );
}

export function EvaluationInsightsRow({
  retrievalP95Ms,
  generationP95Ms,
  hallucinationRisk,
  hallucinationRiskDelta,
  nextRunLabel,
  nextRunEta,
  onTriggerRun,
  triggerDisabled,
}: InsightsRowProps) {
  const risk =
    hallucinationRisk == null || !Number.isFinite(hallucinationRisk)
      ? null
      : Math.max(0, Math.min(1, hallucinationRisk));
  const riskDash = risk == null ? 0 : Math.round(risk * 100);

  return (
    <section className="grid grid-cols-1 gap-8 xl:grid-cols-12">
      <article className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm xl:col-span-4">
        <h3 className="mb-6 text-sm font-medium text-gray-500">
          Latencies (P95)
        </h3>

        <div className="space-y-6">
          <div>
            <div className="mb-2 flex justify-between">
              <span className="text-sm font-semibold text-gray-700">
                Retrieval
              </span>
              <span className="text-sm font-bold text-gray-900">
                {asRoundedMs(retrievalP95Ms)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full bg-indigo-900"
                style={{
                  width:
                    retrievalP95Ms == null
                      ? "0%"
                      : `${Math.max(8, Math.min(100, Math.round(retrievalP95Ms / 5)))}%`,
                }}
              />
            </div>
          </div>

          <div>
            <div className="mb-2 flex justify-between">
              <span className="text-sm font-semibold text-gray-700">
                Generation
              </span>
              <span className="text-sm font-bold text-gray-900">
                {asRoundedMs(generationP95Ms)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full bg-[#7c2d12]"
                style={{
                  width:
                    generationP95Ms == null
                      ? "0%"
                      : `${Math.max(8, Math.min(100, Math.round(generationP95Ms / 20)))}%`,
                }}
              />
            </div>
          </div>

          <div className="flex gap-4 pt-1 text-[10px] font-bold tracking-wide text-gray-500 uppercase">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-indigo-900" /> Cold start
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-indigo-200" /> Warm
            </span>
          </div>
        </div>
      </article>

      <article className="relative rounded-xl border border-gray-200 bg-white p-6 shadow-sm xl:col-span-4">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm leading-tight font-medium text-gray-500">
            Context
            <br />
            Hallucination Risk
          </h3>
          <span className="rounded-full bg-gray-100 px-2 py-1 text-[10px] font-bold tracking-wide text-gray-500 uppercase">
            Breakdown
          </span>
        </div>

        <div className="flex flex-col items-center justify-center pt-2">
          <div className="relative mb-4 h-32 w-32">
            <svg
              className="h-full w-full -rotate-90"
              viewBox="0 0 36 36"
              aria-hidden="true"
            >
              <circle
                cx="18"
                cy="18"
                r="16"
                fill="none"
                stroke="#f3f4f6"
                strokeWidth="3"
              />
              <circle
                cx="18"
                cy="18"
                r="16"
                fill="none"
                stroke="#dc2626"
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={`${riskDash} 100`}
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-2xl font-bold text-gray-900">
              {risk == null ? "N/A" : `${Math.round(risk * 100)}%`}
            </span>
          </div>

          <p className="text-xs text-gray-500">
            {hallucinationRiskDelta == null
              ? "No prior run delta available"
              : `${hallucinationRiskDelta < 0 ? "Decrease" : "Increase"} of ${Math.abs(hallucinationRiskDelta * 100).toFixed(1)}% from previous run`}
          </p>
        </div>
      </article>

      <article className="relative flex flex-col justify-between overflow-hidden rounded-xl bg-[#312e81] p-6 text-white shadow-lg xl:col-span-4">
        <div
          className="pointer-events-none absolute top-[-12px] right-[-20px] text-white/10"
          aria-hidden="true"
        >
          <span className="text-8xl">⚡</span>
        </div>

        <div>
          <span className="mb-1 block text-xs font-medium text-indigo-200">
            Next Scheduled Run
          </span>
          <h3 className="mb-6 text-2xl font-bold">{nextRunLabel}</h3>
          <div className="mb-8 flex items-center gap-2">
            <span className="text-indigo-300">⏰</span>
            <span className="font-mono text-lg font-medium tracking-wider">
              {nextRunEta}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={onTriggerRun}
            disabled={triggerDisabled}
            className="rounded-lg bg-white px-4 py-2 text-sm font-bold text-indigo-900 shadow-sm hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Trigger Manually
          </button>
          <button
            type="button"
            onClick={onTriggerRun}
            disabled={triggerDisabled}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500 text-lg font-bold text-white shadow-lg hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Quick start evaluation run"
          >
            +
          </button>
        </div>
      </article>
    </section>
  );
}

type RunsFilterBarProps = {
  filters: RunFilters;
  datasetOptions: Array<{ id: string; name: string }>;
  ownerOptions: string[];
  onChange: (next: RunFilters) => void;
  onReset: () => void;
};

export function EvaluationRunsFilterBar({
  filters,
  datasetOptions,
  ownerOptions,
  onChange,
  onReset,
}: RunsFilterBarProps) {
  return (
    <section
      aria-label="Run filters"
      className="rounded-xl border border-gray-200 bg-white p-4"
    >
      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Search runs</span>
          <input
            type="search"
            value={filters.query}
            onChange={(event) =>
              onChange({ ...filters, query: event.target.value })
            }
            placeholder="Run name, run ID, or dataset"
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          />
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Status</span>
          <select
            value={filters.status}
            onChange={(event) =>
              onChange({
                ...filters,
                status: event.target.value as RunFilters["status"],
              })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          >
            <option value="all">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Dataset</span>
          <select
            value={filters.datasetId}
            onChange={(event) =>
              onChange({
                ...filters,
                datasetId: event.target.value as RunFilters["datasetId"],
              })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          >
            <option value="all">All datasets</option>
            {datasetOptions.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Owner</span>
          <select
            value={filters.owner}
            onChange={(event) =>
              onChange({
                ...filters,
                owner: event.target.value as RunFilters["owner"],
              })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          >
            <option value="all">All owners</option>
            {ownerOptions.map((owner) => (
              <option key={owner} value={owner}>
                {owner === "unavailable" ? "Unavailable" : owner}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Date from</span>
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(event) =>
              onChange({ ...filters, dateFrom: event.target.value })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          />
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600">
          <span>Date to</span>
          <input
            type="date"
            value={filters.dateTo}
            onChange={(event) =>
              onChange({ ...filters, dateTo: event.target.value })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          />
        </label>

        <label className="grid gap-1 text-xs font-semibold text-gray-600 xl:col-span-2">
          <span>Sort runs</span>
          <select
            value={filters.sortBy}
            onChange={(event) =>
              onChange({
                ...filters,
                sortBy: event.target.value as RunFilters["sortBy"],
              })
            }
            className="h-9 rounded-lg border border-gray-300 bg-gray-50 px-2 text-sm font-medium text-gray-900"
          >
            <option value="created_desc">Newest first</option>
            <option value="created_asc">Oldest first</option>
            <option value="score_desc">Score high to low</option>
            <option value="score_asc">Score low to high</option>
            <option value="status_asc">Status A-Z</option>
          </select>
        </label>

        <div className="flex items-end xl:justify-end">
          <button
            type="button"
            onClick={onReset}
            className="h-9 rounded-lg border border-gray-300 bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Reset filters
          </button>
        </div>
      </div>
    </section>
  );
}

type RunsTableProps = {
  runs: EvaluationRunListItem[];
  activeRunId: string | null;
  onSelectRun: (runId: string) => void;
};

export function EvaluationRunsTable({
  runs,
  activeRunId,
  onSelectRun,
}: RunsTableProps) {
  if (runs.length === 0) {
    return (
      <EmptyState
        compact
        title="No evaluation runs match the current filters."
        description="Start a run or adjust filters to populate this list."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-100 text-sm">
        <caption className="sr-only">
          Evaluation runs with status, score, regressions, owner, duration, and
          created time.
        </caption>
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Run
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Dataset
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Status
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Score
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Regressions
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Started by
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Duration
            </th>
            <th className="px-3 py-2 text-left text-xs font-semibold tracking-wide text-gray-500 uppercase">
              Created
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {runs.map((run) => {
            const isActive = run.runId === activeRunId;
            return (
              <tr
                key={run.runId}
                className={isActive ? "bg-indigo-50/40" : "bg-white"}
              >
                <td className="px-3 py-2 align-top">
                  <button
                    type="button"
                    onClick={() => onSelectRun(run.runId)}
                    className="text-left"
                  >
                    <span className="block font-semibold text-gray-900">
                      {run.runName}
                    </span>
                    <span className="mt-0.5 block text-xs text-gray-500">
                      {run.runId}
                    </span>
                  </button>
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {run.datasetName}
                </td>
                <td className="px-3 py-2 align-top">
                  <EvaluationStatusBadge status={run.status} />
                  <span className="sr-only">
                    {runStatusScreenReaderText(run.status)}
                  </span>
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {formatPercent(run.score)}
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {run.regressions == null ? "Unavailable" : run.regressions}
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {run.startedBy ?? "Unavailable"}
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {formatDuration(run.durationMs)}
                </td>
                <td className="px-3 py-2 align-top text-gray-700">
                  {formatDateTime(run.createdAt)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RunsTableSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <div className="grid grid-cols-1 gap-2 p-3">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={`run-skeleton-${index + 1}`}
            className="h-12 animate-pulse rounded-lg bg-gray-100"
          />
        ))}
      </div>
    </div>
  );
}

export function resolveKpiTrendLabel(delta: number | null | undefined): string {
  if (delta == null || !Number.isFinite(delta)) {
    return "Stable";
  }
  return trendText(delta);
}
