"use client";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  getTrustAnalytics,
  type TrustAnalyticsResponse,
  type TrustDistribution,
  type WarningBreakdown,
} from "@/lib/api/trust_analytics";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

type TimeRangeOption = "7d" | "14d" | "30d" | "90d";

const TIME_RANGE_OPTIONS: { label: string; value: TimeRangeOption }[] = [
  { label: "7 days", value: "7d" },
  { label: "14 days", value: "14d" },
  { label: "30 days", value: "30d" },
  { label: "90 days", value: "90d" },
];

function resolveQueryDates(range: TimeRangeOption): {
  from: string;
  to: string;
} {
  const today = new Date();
  const days = { "7d": 7, "14d": 14, "30d": 30, "90d": 90 }[range];
  const from = new Date(today);
  from.setDate(from.getDate() - (days - 1));
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  return { from: fmt(from), to: fmt(today) };
}

function formatPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

type TrustLevel = "high" | "medium" | "low" | "warning" | "not_found";

function trustLevelBarColor(level: TrustLevel): string {
  if (level === "high") return "bg-emerald-500";
  if (level === "medium") return "bg-amber-400";
  if (level === "low") return "bg-rose-400";
  if (level === "warning") return "bg-orange-400";
  return "bg-slate-400";
}

function trustLevelTextColor(level: TrustLevel): string {
  if (level === "high") return "text-emerald-700";
  if (level === "medium") return "text-amber-700";
  if (level === "low") return "text-rose-700";
  if (level === "warning") return "text-orange-700";
  return "text-slate-600";
}

function MetricCard({
  title,
  value,
  subtitle,
  missing,
}: {
  title: string;
  value: string;
  subtitle?: string;
  missing?: boolean;
}) {
  return (
    <article
      className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm"
      data-testid="trust-metric-card"
    >
      <p className="mb-1 text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
        {title}
      </p>
      {missing ? (
        <p className="text-xl font-bold text-[#9d98b5]">—</p>
      ) : (
        <p className="text-xl font-bold text-[#2f2a46]">{value}</p>
      )}
      {subtitle ? (
        <p className="mt-1 text-[11px] text-[#9d98b5]">{subtitle}</p>
      ) : null}
    </article>
  );
}

function TrustDistributionSection({ dist }: { dist: TrustDistribution }) {
  const levels: {
    key: TrustLevel;
    label: string;
    count: number;
    pct: number | null;
  }[] = [
    { key: "high", label: "High", count: dist.high_count, pct: dist.high_pct },
    {
      key: "medium",
      label: "Medium",
      count: dist.medium_count,
      pct: dist.medium_pct,
    },
    { key: "low", label: "Low", count: dist.low_count, pct: dist.low_pct },
    {
      key: "warning",
      label: "Warning",
      count: dist.warning_count,
      pct: dist.warning_pct,
    },
    {
      key: "not_found",
      label: "Not Found",
      count: dist.not_found_count,
      pct: dist.not_found_pct,
    },
  ];
  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
      data-testid="trust-distribution-section"
    >
      <h3 className="mb-4 text-sm font-bold text-[#2f2a46]">
        Trust Score Distribution
      </h3>
      <div className="space-y-2.5">
        {levels.map(({ key, label, count, pct }) => (
          <div key={key} className="flex items-center gap-3">
            <span
              className={`w-20 shrink-0 text-[11px] font-semibold ${trustLevelTextColor(key)}`}
            >
              {label}
            </span>
            <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-[#f0eef9]">
              <div
                className={`absolute top-0 left-0 h-full rounded-full ${trustLevelBarColor(key)}`}
                style={{
                  width: pct != null ? `${(pct * 100).toFixed(1)}%` : "0%",
                }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-[11px] text-[#6a6780]">
              {formatCount(count)} ({formatPct(pct)})
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function WarningsSection({ warnings }: { warnings: WarningBreakdown }) {
  const items: { label: string; count: number; icon: string }[] = [
    {
      label: "Stale sources",
      count: warnings.stale_source_count,
      icon: "schedule",
    },
    {
      label: "Source conflicts",
      count: warnings.conflict_count,
      icon: "sync_problem",
    },
    {
      label: "OCR quality issues",
      count: warnings.ocr_count,
      icon: "document_scanner",
    },
    {
      label: "Extraction issues",
      count: warnings.extraction_count,
      icon: "error_outline",
    },
    {
      label: "Processing incomplete",
      count: warnings.processing_count,
      icon: "hourglass_empty",
    },
    {
      label: "Evidence quality",
      count: warnings.evidence_quality_count,
      icon: "quiz",
    },
    {
      label: "Citation validation failed",
      count: warnings.citation_validation_failed_count,
      icon: "link_off",
    },
  ];
  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
      data-testid="trust-warnings-section"
    >
      <h3 className="mb-4 text-sm font-bold text-[#2f2a46]">
        Warning Type Breakdown
      </h3>
      <div className="divide-y divide-[#f0eef9]">
        {items.map(({ label, count, icon }) => (
          <div key={label} className="flex items-center gap-3 py-2">
            <span
              className="material-symbols-outlined text-[15px] text-[#9d98b5]"
              aria-hidden="true"
            >
              {icon}
            </span>
            <span className="flex-1 text-[12px] text-[#2f2a46]">{label}</span>
            <span
              className={`text-[12px] font-semibold ${count > 0 ? "text-amber-700" : "text-[#9d98b5]"}`}
            >
              {formatCount(count)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function LangfuseStatusBadge({
  enabled,
  tracesLinked,
}: {
  enabled: boolean;
  tracesLinked: number;
}) {
  if (!enabled) {
    return (
      <div
        className="flex items-center gap-1.5 rounded-full border border-[#e0dced] bg-[#faf9ff] px-3 py-1 text-[11px] text-[#9d98b5]"
        data-testid="langfuse-status-badge"
      >
        <span
          className="material-symbols-outlined text-[13px]"
          aria-hidden="true"
        >
          link_off
        </span>
        Langfuse not configured
      </div>
    );
  }
  return (
    <div
      className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-[11px] text-emerald-800"
      data-testid="langfuse-status-badge"
    >
      <span
        className="material-symbols-outlined text-[13px]"
        aria-hidden="true"
      >
        link
      </span>
      Langfuse linked · {formatCount(tracesLinked)} trace
      {tracesLinked !== 1 ? "s" : ""}
    </div>
  );
}

function TrustTrendsSection({ data }: { data: TrustAnalyticsResponse }) {
  const hasData = data.daily_trends.some((p) => p.answer_count > 0);
  return (
    <section
      className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm"
      data-testid="trust-trends-section"
    >
      <h3 className="mb-1 text-sm font-bold text-[#2f2a46]">Daily Trends</h3>
      <p className="mb-4 text-[11px] text-[#9d98b5]">
        Answers answered per day with confidence and not-found signals.
      </p>
      {!hasData ? (
        <p className="py-6 text-center text-[12px] text-[#9d98b5]">
          No answer data in the selected range.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="border-b border-[#f0eef9] text-[#9d98b5]">
                <th className="py-1 pr-3 font-semibold">Date</th>
                <th className="py-1 pr-3 font-semibold">Answers</th>
                <th className="py-1 pr-3 font-semibold">Not-found rate</th>
                <th className="py-1 pr-3 font-semibold">Avg confidence</th>
                <th className="py-1 font-semibold">Avg citation support</th>
              </tr>
            </thead>
            <tbody>
              {data.daily_trends.map((point) => (
                <tr
                  key={point.date}
                  className="border-b border-[#f9f8fd] hover:bg-[#faf9ff]"
                >
                  <td className="py-1 pr-3 font-medium text-[#2f2a46]">
                    {point.date}
                  </td>
                  <td className="py-1 pr-3 text-[#6a6780]">
                    {formatCount(point.answer_count)}
                  </td>
                  <td className="py-1 pr-3 text-[#6a6780]">
                    {formatPct(point.not_found_rate)}
                  </td>
                  <td className="py-1 pr-3 text-[#6a6780]">
                    {formatScore(point.avg_confidence_score)}
                  </td>
                  <td className="py-1 text-[#6a6780]">
                    {formatScore(point.avg_citation_support_score)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function AdminTrustAnalyticsPage() {
  const { state } = useAuthSession();
  const [timeRange, setTimeRange] = useState<TimeRangeOption>("30d");

  const { from, to } = resolveQueryDates(timeRange);
  const queryParams = { from, to };

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.admin.trustAnalytics(queryParams),
    queryFn: () => getTrustAnalytics(queryParams),
    enabled: state.status === "authenticated",
  });

  if (isLoading) return <LoadingState />;
  if (isForbiddenError(error)) return <ForbiddenState />;
  if (error || !data)
    return (
      <ErrorState
        description={
          error ? getApiErrorMessage(error) : "Failed to load trust analytics."
        }
      />
    );

  const missing = data.telemetry_missing;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-[#2f2a46]">Trust Analytics</h2>
          <p className="text-[12px] text-[#9d98b5]">
            Answer trust trends, warning signals, and citation quality for your
            organization.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <LangfuseStatusBadge
            enabled={data.langfuse.enabled}
            tracesLinked={data.langfuse.traces_linked_count}
          />
          {/* Time range picker */}
          <div
            className="inline-flex rounded-full border border-[#d7d4e8] bg-white p-0.5 text-[11px] font-semibold"
            role="group"
            aria-label="Time range"
          >
            {TIME_RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setTimeRange(opt.value)}
                className={`rounded-full px-3 py-1.5 transition-colors ${
                  timeRange === opt.value
                    ? "bg-[#3525cd] text-white"
                    : "text-[#6a6780] hover:text-[#3525cd]"
                }`}
                aria-pressed={timeRange === opt.value}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {missing ? (
        <div className="rounded-2xl border border-[#e0dced] bg-[#faf9ff] py-12 text-center">
          <span
            className="material-symbols-outlined text-[32px] text-[#9d98b5]"
            aria-hidden="true"
          >
            analytics
          </span>
          <p className="mt-2 text-[13px] font-medium text-[#6a6780]">
            No trust metrics yet
          </p>
          <p className="mt-1 text-[11px] text-[#9d98b5]">
            Trust metrics are recorded automatically after each answered
            question.
          </p>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              title="Total answers"
              value={formatCount(data.total_answers)}
              subtitle={`${from} – ${to}`}
            />
            <MetricCard
              title="Not-found rate"
              value={formatPct(data.not_found_rate)}
              subtitle="Questions with no relevant source"
            />
            <MetricCard
              title="Avg confidence"
              value={formatScore(data.avg_confidence_score)}
              subtitle="Mean confidence score"
            />
            <MetricCard
              title="Avg citation support"
              value={formatScore(data.avg_citation_support_score)}
              subtitle="Mean citation support score"
            />
          </div>

          {/* Secondary stats */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MetricCard
              title="Conflict detection rate"
              value={formatPct(data.conflict_detection_rate)}
              subtitle="Answers with source conflicts"
            />
            <MetricCard
              title="Unsupported claims removed"
              value={formatCount(data.unsupported_claims_removed_total)}
              subtitle="By grounded verifier (total)"
            />
            <MetricCard
              title="Avg verification support"
              value={formatScore(data.avg_verification_support_score)}
              subtitle="Grounded verification score"
              missing={data.avg_verification_support_score == null}
            />
          </div>

          {/* Distribution + Warnings */}
          <div className="grid gap-4 lg:grid-cols-2">
            <TrustDistributionSection dist={data.trust_distribution} />
            <WarningsSection warnings={data.warnings} />
          </div>

          {/* Daily trends */}
          <TrustTrendsSection data={data} />
        </>
      )}
    </div>
  );
}
