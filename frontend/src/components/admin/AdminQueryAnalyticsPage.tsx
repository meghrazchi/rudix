"use client";

import React, {
  forwardRef,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  buildQueryAnalyticsExportUrl,
  convertKnowledgeGap,
  createKnowledgeGap,
  detectKnowledgeGaps,
  getQueryAnalyticsSummary,
  getQueryAnalyticsTrends,
  listKnowledgeGaps,
  updateKnowledgeGap,
  type GapStatus,
  type GapType,
  type KnowledgeGapResponse,
} from "@/lib/api/query-analytics";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { isForbiddenError, extractRequestIdFromError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { useOverlayFocus } from "@/lib/use-overlay-focus";

const PAGE_LIMIT = 25;

type DatePreset = "7d" | "30d" | "90d";

const DATE_PRESETS: { label: string; value: DatePreset }[] = [
  { label: "Last 7 days", value: "7d" },
  { label: "Last 30 days", value: "30d" },
  { label: "Last 90 days", value: "90d" },
];

function presetToDateRange(preset: DatePreset): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to);
  switch (preset) {
    case "7d":
      from.setDate(from.getDate() - 6);
      break;
    case "90d":
      from.setDate(from.getDate() - 89);
      break;
    default:
      from.setDate(from.getDate() - 29);
  }
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatConf(value: number | null | undefined): string {
  if (value == null) return "—";
  return (value * 100).toFixed(1) + "%";
}

function gapTypePillClass(t: GapType): string {
  switch (t) {
    case "no_answer":
      return "bg-rose-100 text-rose-800";
    case "low_confidence":
      return "bg-amber-100 text-amber-800";
    case "bad_feedback":
      return "bg-orange-100 text-orange-800";
    case "stale_citation":
      return "bg-sky-100 text-sky-800";
    case "missing_source":
      return "bg-violet-100 text-violet-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function gapStatusPillClass(s: GapStatus): string {
  switch (s) {
    case "resolved":
      return "bg-emerald-100 text-emerald-800";
    case "dismissed":
      return "bg-slate-200 text-slate-700";
    case "in_review":
      return "bg-blue-100 text-blue-800";
    default:
      return "bg-rose-100 text-rose-800";
  }
}

function gapTypeLabel(t: GapType): string {
  switch (t) {
    case "no_answer":
      return "No answer";
    case "low_confidence":
      return "Low confidence";
    case "bad_feedback":
      return "Bad feedback";
    case "stale_citation":
      return "Stale citation";
    case "missing_source":
      return "Missing source";
    default:
      return t;
  }
}

function triggerCsvDownload(url: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = "query-analytics.csv";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ── Gap detail panel ───────────────────────────────────────────────────────────

type GapPanelProps = {
  gap: KnowledgeGapResponse;
  onClose: () => void;
  onUpdate: (gapId: string, status: GapStatus, notes: string | null) => void;
  onConvert: (
    gapId: string,
    target: "eval_case" | "doc_request" | "review_task",
  ) => void;
  isUpdating: boolean;
};

const GapDetailPanel = forwardRef<HTMLElement, GapPanelProps>(
  function GapDetailPanel(
    { gap, onClose, onUpdate, onConvert, isUpdating },
    ref,
  ) {
    const [statusInput, setStatusInput] = useState<GapStatus>(gap.status);
    const [notesInput, setNotesInput] = useState(gap.reviewer_notes ?? "");

    return (
      <aside
        ref={ref as React.RefObject<HTMLElement>}
        role="dialog"
        aria-modal="true"
        aria-labelledby="gap-detail-title"
        className="absolute top-3 right-0 z-20 max-h-[min(85vh,760px)] w-full max-w-[420px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Knowledge gap
            </p>
            <h3
              id="gap-detail-title"
              className="mt-1 text-base font-semibold text-[#1b1b24]"
            >
              {gap.topic_label}
            </h3>
          </div>
          <button
            type="button"
            data-overlay-autofocus="true"
            onClick={onClose}
            className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
          >
            Close
          </button>
        </div>

        <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3 text-sm">
          <dl className="grid gap-2">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Type
              </dt>
              <dd>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${gapTypePillClass(gap.gap_type)}`}
                >
                  {gapTypeLabel(gap.gap_type)}
                </span>
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Occurrences
              </dt>
              <dd className="font-mono text-sm font-semibold text-[#302f39]">
                {gap.occurrence_count}
              </dd>
            </div>
            {gap.avg_confidence != null ? (
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Avg confidence
                </dt>
                <dd className="text-sm text-[#302f39]">
                  {formatConf(gap.avg_confidence)}
                </dd>
              </div>
            ) : null}
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Source
              </dt>
              <dd className="text-sm text-[#302f39]">
                {gap.gap_source.replace(/_/g, " ")}
              </dd>
            </div>
            {gap.converted_to ? (
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Converted to
                </dt>
                <dd className="text-sm text-violet-700">
                  {gap.converted_to.replace(/_/g, " ")}
                </dd>
              </div>
            ) : null}
          </dl>
        </section>

        {gap.description ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Description
            </h4>
            <p className="text-sm text-[#302f39]">{gap.description}</p>
          </section>
        ) : null}

        {gap.example_query ? (
          <section className="mb-4 rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3">
            <h4 className="mb-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Example query
            </h4>
            <p className="text-sm text-[#464555] italic">{gap.example_query}</p>
          </section>
        ) : null}

        {!gap.converted_to ? (
          <div className="mb-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onConvert(gap.gap_id, "eval_case")}
              className="rounded-lg border border-violet-300 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 hover:bg-violet-100"
            >
              Convert to eval case
            </button>
            <button
              type="button"
              onClick={() => onConvert(gap.gap_id, "doc_request")}
              className="rounded-lg border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100"
            >
              Request document
            </button>
            <button
              type="button"
              onClick={() => onConvert(gap.gap_id, "review_task")}
              className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
            >
              Create review task
            </button>
          </div>
        ) : null}

        <section className="space-y-3">
          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Status
            </span>
            <select
              value={statusInput}
              onChange={(e) => setStatusInput(e.target.value as GapStatus)}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="open">Open</option>
              <option value="in_review">In review</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Reviewer notes
            </span>
            <textarea
              value={notesInput}
              onChange={(e) => setNotesInput(e.target.value)}
              rows={3}
              maxLength={4000}
              className="w-full resize-none rounded-lg border border-[#c7c4d8] bg-white px-3 py-2 text-sm text-[#1b1b24]"
            />
          </label>

          <button
            type="button"
            onClick={() =>
              onUpdate(gap.gap_id, statusInput, notesInput.trim() || null)
            }
            disabled={isUpdating}
            className="w-full rounded-lg bg-[#3525cd] px-4 py-2 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isUpdating ? "Saving…" : "Save changes"}
          </button>

          <div className="rounded-lg border border-[#e4e1ee] bg-[#faf9ff] px-3 py-2 text-xs text-[#777587]">
            <p>
              <span className="font-semibold">Gap ID:</span>{" "}
              <span className="font-mono">{gap.gap_id}</span>
            </p>
            <p>
              <span className="font-semibold">Created:</span>{" "}
              {new Date(gap.created_at).toLocaleString()}
            </p>
          </div>
        </section>
      </aside>
    );
  },
);

// ── Main page ──────────────────────────────────────────────────────────────────

export function AdminQueryAnalyticsPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const [preset, setPreset] = useState<DatePreset>("30d");
  const dateRange = useMemo(() => presetToDateRange(preset), [preset]);

  const [gapStatusFilter, setGapStatusFilter] = useState<GapStatus | "">("");
  const [gapTypeFilter, setGapTypeFilter] = useState<GapType | "">("");
  const [gapOffset, setGapOffset] = useState(0);

  const [selectedGap, setSelectedGap] = useState<KnowledgeGapResponse | null>(
    null,
  );
  const [detectError, setDetectError] = useState<string | null>(null);
  const [detectSuccess, setDetectSuccess] = useState<string | null>(null);

  const panelRef = useRef<HTMLElement | null>(null);
  const tableHostRef = useRef<HTMLDivElement | null>(null);
  const closePanel = useCallback(() => setSelectedGap(null), []);
  useOverlayFocus({
    isOpen: selectedGap != null,
    containerRef: panelRef,
    onClose: closePanel,
    lockBodyScroll: false,
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.queryAnalytics.summary(
      dateRange as Record<string, unknown>,
    ),
    queryFn: () =>
      getQueryAnalyticsSummary({ from: dateRange.from, to: dateRange.to }),
    enabled: isAdminUser,
  });

  const trendsQuery = useQuery({
    queryKey: queryKeys.queryAnalytics.trends(
      dateRange as Record<string, unknown>,
    ),
    queryFn: () =>
      getQueryAnalyticsTrends({ from: dateRange.from, to: dateRange.to }),
    enabled: isAdminUser,
  });

  const gapParams = useMemo(
    () => ({
      status: gapStatusFilter || undefined,
      gap_type: gapTypeFilter || undefined,
      limit: PAGE_LIMIT,
      offset: gapOffset,
    }),
    [gapStatusFilter, gapTypeFilter, gapOffset],
  );

  const gapsQuery = useQuery({
    queryKey: queryKeys.queryAnalytics.gaps(
      gapParams as Record<string, unknown>,
    ),
    queryFn: () => listKnowledgeGaps(gapParams),
    enabled: isAdminUser,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      gapId,
      status,
      notes,
    }: {
      gapId: string;
      status: GapStatus;
      notes: string | null;
    }) => updateKnowledgeGap(gapId, { status, reviewer_notes: notes }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.queryAnalytics.all,
      });
      setSelectedGap(updated);
    },
  });

  const convertMutation = useMutation({
    mutationFn: ({
      gapId,
      target,
    }: {
      gapId: string;
      target: "eval_case" | "doc_request" | "review_task";
    }) => convertKnowledgeGap(gapId, { target }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.queryAnalytics.all,
      });
      setSelectedGap(null);
    },
  });

  const detectMutation = useMutation({
    mutationFn: () =>
      detectKnowledgeGaps({ from_date: dateRange.from, to_date: dateRange.to }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.queryAnalytics.all,
      });
      setDetectError(null);
      setDetectSuccess(
        `Detected ${result.detected} patterns — ${result.created} new gap(s) created, ${result.skipped_duplicates} duplicate(s) skipped.`,
      );
    },
    onError: (err) => {
      setDetectError(getApiErrorMessage(err));
      setDetectSuccess(null);
    },
  });

  const forbiddenError =
    summaryQuery.isError && isForbiddenError(summaryQuery.error)
      ? summaryQuery.error
      : null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Query analytics restricted"
          description="Only owner and admin roles can access the query analytics dashboard."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Query analytics unavailable"
          description="Your role no longer has access to this dashboard."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const summary = summaryQuery.data;
  const trends = trendsQuery.data;
  const gaps = gapsQuery.data;
  const gapRows = gaps?.items ?? [];
  const gapTotal = gaps?.total ?? 0;
  const hasPreviousPage = gapOffset > 0;
  const hasNextPage = gapOffset + PAGE_LIMIT < gapTotal;
  const pageStart = gapTotal === 0 ? 0 : gapOffset + 1;
  const pageEnd =
    gapTotal === 0 ? 0 : Math.min(gapOffset + PAGE_LIMIT, gapTotal);

  const exportUrl = buildQueryAnalyticsExportUrl({
    from: dateRange.from,
    to: dateRange.to,
  });

  // Trend sparkline data (last 14 days max for compact display)
  const sparkPoints = trends?.points.slice(-14) ?? [];

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      {/* Header */}
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              Insights &amp; Knowledge Gaps
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              Query analytics
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              Identify frequent unanswered questions, low-confidence answers,
              and missing knowledge sources. Convert gaps into evaluation cases
              or document requests.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => triggerCsvDownload(exportUrl)}
              className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
            >
              Export CSV
            </button>
          </div>
        </div>

        {/* Date preset tabs */}
        <div className="mt-4 flex gap-2">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setPreset(p.value)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                preset === p.value
                  ? "bg-[#3525cd] text-white"
                  : "border border-[#c7c4d8] text-[#464555] hover:bg-[#f5f2ff]"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </header>

      {/* Summary metrics */}
      {summaryQuery.isLoading ? (
        <LoadingState
          compact
          className="rounded-xl border border-[#e4e1f2] bg-white p-4"
          title="Loading metrics…"
        />
      ) : summaryQuery.isError ? (
        <ErrorState
          compact
          error={summaryQuery.error}
          description={getApiErrorMessage(summaryQuery.error)}
          onRetry={() => void summaryQuery.refetch()}
        />
      ) : summary && !summary.enabled ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-800">
          Query analytics is disabled. Reason:{" "}
          {summary.disabled_reason ?? "unknown"}.
        </div>
      ) : summary ? (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
            <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Total queries
            </p>
            <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
              {summary.total_queries.toLocaleString()}
            </p>
          </article>
          <article className="rounded-xl border border-rose-200 bg-rose-50/40 p-5 shadow-sm">
            <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
              Unanswered rate
            </p>
            <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
              {formatPct(summary.unanswered_rate)}
            </p>
            <p className="mt-1 text-xs text-rose-600">
              {summary.unanswered_queries} unanswered
            </p>
          </article>
          <article className="rounded-xl border border-amber-200 bg-amber-50/40 p-5 shadow-sm">
            <p className="text-xs font-semibold tracking-[0.08em] text-amber-700 uppercase">
              Avg confidence
            </p>
            <p className="mt-2 font-mono text-3xl font-semibold text-amber-700">
              {formatConf(summary.avg_confidence)}
            </p>
            <p className="mt-1 text-xs text-amber-600">
              {summary.low_confidence_queries} low-confidence answers
            </p>
          </article>
          <article className="rounded-xl border border-orange-200 bg-orange-50/40 p-5 shadow-sm">
            <p className="text-xs font-semibold tracking-[0.08em] text-orange-700 uppercase">
              Negative feedback rate
            </p>
            <p className="mt-2 font-mono text-3xl font-semibold text-orange-700">
              {formatPct(summary.negative_feedback_rate)}
            </p>
            <p className="mt-1 text-xs text-orange-600">
              {summary.negative_feedback_count} thumbs-down
            </p>
          </article>
        </section>
      ) : null}

      {/* Trend chart (compact bar view) */}
      {sparkPoints.length > 0 ? (
        <section className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-[#1b1b24]">
            Query trend (last {sparkPoints.length} days)
          </h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs text-[#464555]">
              <thead>
                <tr className="border-b border-[#e4e1ee] text-left text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  <th className="pr-4 pb-2">Date</th>
                  <th className="pr-4 pb-2 text-right">Queries</th>
                  <th className="pr-4 pb-2 text-right">Unanswered</th>
                  <th className="pr-4 pb-2 text-right">Low confidence</th>
                  <th className="pr-4 pb-2 text-right">Neg. feedback</th>
                  <th className="pb-2 text-right">Avg confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#ece9f5]">
                {sparkPoints.map((pt) => (
                  <tr key={pt.date}>
                    <td className="py-1.5 pr-4 font-mono">{pt.date}</td>
                    <td className="py-1.5 pr-4 text-right font-mono">
                      {pt.total_queries}
                    </td>
                    <td className="py-1.5 pr-4 text-right font-mono text-rose-700">
                      {pt.unanswered}
                    </td>
                    <td className="py-1.5 pr-4 text-right font-mono text-amber-700">
                      {pt.low_confidence}
                    </td>
                    <td className="py-1.5 pr-4 text-right font-mono text-orange-700">
                      {pt.negative_feedback}
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {formatConf(pt.avg_confidence)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* Feedback categories breakdown */}
      {summary && summary.top_feedback_categories.length > 0 ? (
        <section className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-[#1b1b24]">
            Top negative feedback categories
          </h2>
          <div className="flex flex-wrap gap-2">
            {summary.top_feedback_categories.map((cat) => (
              <span
                key={cat.category}
                className="flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-800"
              >
                {cat.category.replace(/_/g, " ")}
                <span className="rounded-full bg-rose-200 px-1.5 py-0.5 font-mono text-[10px] text-rose-900">
                  {cat.count}
                </span>
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {/* Knowledge gaps section */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold text-[#1b1b24]">
            Knowledge gaps
          </h2>
          <button
            type="button"
            onClick={() => {
              setDetectError(null);
              setDetectSuccess(null);
              detectMutation.mutate();
            }}
            disabled={detectMutation.isPending}
            className="h-9 rounded-lg border border-[#3525cd] bg-white px-4 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:bg-[#f5f2ff] disabled:opacity-60"
          >
            {detectMutation.isPending ? "Detecting…" : "Auto-detect gaps"}
          </button>
        </div>

        {detectError ? (
          <p className="text-sm text-rose-700">{detectError}</p>
        ) : null}
        {detectSuccess ? (
          <p className="text-sm text-emerald-700">{detectSuccess}</p>
        ) : null}

        {/* Gap filters */}
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
          <label className="w-[180px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Status
            </span>
            <select
              value={gapStatusFilter}
              onChange={(e) => {
                setGapStatusFilter(e.target.value as GapStatus | "");
                setGapOffset(0);
              }}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All statuses</option>
              <option value="open">Open</option>
              <option value="in_review">In review</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </label>

          <label className="w-[200px] space-y-1">
            <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
              Gap type
            </span>
            <select
              value={gapTypeFilter}
              onChange={(e) => {
                setGapTypeFilter(e.target.value as GapType | "");
                setGapOffset(0);
              }}
              className="h-9 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
            >
              <option value="">All types</option>
              <option value="no_answer">No answer</option>
              <option value="low_confidence">Low confidence</option>
              <option value="bad_feedback">Bad feedback</option>
              <option value="stale_citation">Stale citation</option>
              <option value="missing_source">Missing source</option>
            </select>
          </label>

          <button
            type="button"
            onClick={() => {
              setGapStatusFilter("");
              setGapTypeFilter("");
              setGapOffset(0);
            }}
            className="mt-5 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
          >
            Clear
          </button>
        </div>

        {/* Gaps table */}
        <div ref={tableHostRef} className="relative">
          <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
              <h3 className="text-base font-semibold text-[#1b1b24]">
                Gap records
              </h3>
              {gapsQuery.isSuccess ? (
                <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                  Showing {pageStart}–{pageEnd} of {gapTotal}
                </p>
              ) : null}
            </div>

            {gapsQuery.isLoading ? (
              <LoadingState
                compact
                className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
                title="Loading gaps…"
              />
            ) : null}

            {gapsQuery.isError ? (
              <div className="m-4">
                <ErrorState
                  compact
                  error={gapsQuery.error}
                  description={getApiErrorMessage(gapsQuery.error)}
                  onRetry={() => void gapsQuery.refetch()}
                />
              </div>
            ) : null}

            {gapsQuery.isSuccess && gapRows.length === 0 ? (
              <EmptyState
                compact
                className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
                title="No knowledge gaps found. Use 'Auto-detect gaps' to analyze recent data."
              />
            ) : null}

            {gapsQuery.isSuccess && gapRows.length > 0 ? (
              <>
                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-sm">
                    <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                      <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                        <th className="px-4 py-3">Topic</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3 text-right">Occurrences</th>
                        <th className="px-4 py-3 text-right">Avg confidence</th>
                        <th className="px-4 py-3 text-center">Status</th>
                        <th className="px-4 py-3">Source</th>
                        <th className="px-4 py-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#ece9f5]">
                      {gapRows.map((gap) => {
                        const isSelected = selectedGap?.gap_id === gap.gap_id;
                        return (
                          <tr
                            key={gap.gap_id}
                            onClick={() => setSelectedGap(gap)}
                            className={`cursor-pointer transition-colors ${isSelected ? "bg-[#ebe8ff]" : "hover:bg-[#f5f2ff]"}`}
                          >
                            <td className="max-w-[200px] px-4 py-3">
                              <p className="truncate text-sm font-medium text-[#1b1b24]">
                                {gap.topic_label}
                              </p>
                              {gap.converted_to ? (
                                <p className="text-[10px] text-violet-700">
                                  → {gap.converted_to.replace(/_/g, " ")}
                                </p>
                              ) : null}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${gapTypePillClass(gap.gap_type)}`}
                              >
                                {gapTypeLabel(gap.gap_type)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-[#302f39]">
                              {gap.occurrence_count}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-sm text-[#302f39]">
                              {formatConf(gap.avg_confidence)}
                            </td>
                            <td className="px-4 py-3 text-center">
                              <span
                                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${gapStatusPillClass(gap.status)}`}
                              >
                                {gap.status.replace(/_/g, " ")}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-xs text-[#777587]">
                              {gap.gap_source.replace(/_/g, " ")}
                            </td>
                            <td className="px-4 py-3">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedGap(gap);
                                }}
                                className="rounded-lg border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                              >
                                Review
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="flex items-center justify-between gap-3 border-t border-[#e4e1ee] px-4 py-3">
                  <p className="text-sm text-[#464555]">
                    Showing {pageStart} to {pageEnd} of {gapTotal} gaps
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setGapOffset((p) => Math.max(0, p - PAGE_LIMIT))
                      }
                      disabled={!hasPreviousPage || gapsQuery.isFetching}
                      className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={() => setGapOffset((p) => p + PAGE_LIMIT)}
                      disabled={!hasNextPage || gapsQuery.isFetching}
                      className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </>
            ) : null}
          </section>

          {selectedGap ? (
            <>
              <button
                type="button"
                aria-label="Close gap detail"
                onClick={closePanel}
                className="absolute inset-0 z-10 bg-[#17172a]/15 xl:bg-transparent"
              />
              <GapDetailPanel
                ref={panelRef}
                gap={selectedGap}
                onClose={closePanel}
                onUpdate={(gapId, status, notes) =>
                  updateMutation.mutate({ gapId, status, notes })
                }
                onConvert={(gapId, target) =>
                  convertMutation.mutate({ gapId, target })
                }
                isUpdating={updateMutation.isPending}
              />
            </>
          ) : null}
        </div>
      </section>

      {updateMutation.isError ? (
        <p className="text-sm text-rose-700">
          {getApiErrorMessage(updateMutation.error)}
        </p>
      ) : null}
    </section>
  );
}
