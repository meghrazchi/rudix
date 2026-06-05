"use client";

import { useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  getObservabilitySnapshot,
  type ApiMetrics,
  type IndexingMetrics,
  type LlmMetrics,
  type ObservabilitySnapshot,
  type StorageMetrics,
} from "@/lib/api/observability";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
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

function formatMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(value)} ms`;
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

type SignalStatus = "healthy" | "degraded" | "missing";

function resolveSignalStatus(
  rate: number | null | undefined,
  degradedThreshold: number,
): SignalStatus {
  if (rate == null) return "missing";
  if (rate > degradedThreshold) return "degraded";
  return "healthy";
}

function signalBadgeClass(status: SignalStatus): string {
  if (status === "healthy") return "bg-emerald-100 text-emerald-800";
  if (status === "degraded") return "bg-rose-100 text-rose-800";
  return "bg-slate-200 text-slate-700";
}

function signalBadgeLabel(status: SignalStatus): string {
  if (status === "healthy") return "Healthy";
  if (status === "degraded") return "Degraded";
  return "No data";
}

function MetricRow({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm">
      <dt className="text-[#4f4b68]">{label}</dt>
      <dd className="text-right">
        <span className="font-semibold text-[#2f2a46]">{value}</span>
        {note ? (
          <span className="ml-2 text-[11px] text-[#6d6985]">{note}</span>
        ) : null}
      </dd>
    </div>
  );
}

function SectionCard({
  title,
  badge,
  badgeClass,
  children,
}: {
  title: string;
  badge?: string;
  badgeClass?: string;
  children: React.ReactNode;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-2">
        <h2 className="text-lg font-bold text-[#2a2640]">{title}</h2>
        {badge ? (
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${badgeClass ?? "bg-slate-200 text-slate-700"}`}
          >
            {badge}
          </span>
        ) : null}
      </div>
      {children}
    </article>
  );
}

function MissingTelemetryNotice({ entity }: { entity: string }) {
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
      No {entity} telemetry in the selected time range. Signals will appear once
      events are recorded.
    </p>
  );
}

function ApiMetricsSection({ metrics }: { metrics: ApiMetrics }) {
  const errorStatus = resolveSignalStatus(metrics.error_rate, 0.05);
  return (
    <SectionCard
      title="API metrics"
      badge={signalBadgeLabel(errorStatus)}
      badgeClass={signalBadgeClass(errorStatus)}
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="API audit log" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total requests"
            value={formatCount(metrics.total_requests)}
          />
          <MetricRow
            label="Failed requests"
            value={formatCount(metrics.failed_requests)}
          />
          <MetricRow label="Error rate" value={formatPct(metrics.error_rate)} />
          <MetricRow
            label="Avg latency"
            value={formatMs(metrics.avg_latency_ms)}
          />
          <MetricRow
            label="P95 latency"
            value={formatMs(metrics.p95_latency_ms)}
          />
        </dl>
      )}
    </SectionCard>
  );
}

function LlmMetricsSection({ metrics }: { metrics: LlmMetrics }) {
  const errorStatus = resolveSignalStatus(metrics.error_rate, 0.1);
  return (
    <SectionCard
      title="LLM metrics"
      badge={signalBadgeLabel(errorStatus)}
      badgeClass={signalBadgeClass(errorStatus)}
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="LLM usage" />
      ) : (
        <div className="space-y-4">
          <dl className="space-y-2">
            <MetricRow
              label="Total LLM events"
              value={formatCount(metrics.total_events)}
            />
            <MetricRow
              label="Failed events"
              value={formatCount(metrics.failed_events)}
            />
            <MetricRow
              label="LLM error rate"
              value={formatPct(metrics.error_rate)}
            />
            <MetricRow
              label="Avg latency"
              value={formatMs(metrics.avg_latency_ms)}
            />
          </dl>
          {metrics.top_models.length > 0 ? (
            <div>
              <p className="mb-2 text-xs font-semibold text-[#5d58a8] uppercase tracking-wide">
                Top models
              </p>
              <ul className="space-y-1">
                {metrics.top_models.slice(0, 5).map((model) => (
                  <li
                    key={model.model_name}
                    className="flex items-center justify-between rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-[#2f2a46]">
                      {model.model_name}
                    </span>
                    <span className="text-[#6d6985]">
                      {formatCount(model.event_count)} calls
                      {model.error_count > 0 ? (
                        <span className="ml-2 text-rose-600">
                          ({model.error_count} errors)
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}

function IndexingMetricsSection({ metrics }: { metrics: IndexingMetrics }) {
  const successStatus: SignalStatus =
    metrics.telemetry_missing
      ? "missing"
      : metrics.success_rate == null
        ? "missing"
        : metrics.success_rate >= 0.95
          ? "healthy"
          : "degraded";

  return (
    <SectionCard
      title="Indexing pipeline"
      badge={signalBadgeLabel(successStatus)}
      badgeClass={signalBadgeClass(successStatus)}
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="pipeline" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total jobs"
            value={formatCount(metrics.total_jobs)}
          />
          <MetricRow
            label="Succeeded"
            value={formatCount(metrics.succeeded_jobs)}
          />
          <MetricRow
            label="Failed"
            value={formatCount(metrics.failed_jobs)}
          />
          <MetricRow
            label="In progress"
            value={formatCount(metrics.in_progress_jobs)}
          />
          <MetricRow
            label="Success rate"
            value={formatPct(metrics.success_rate)}
          />
        </dl>
      )}
      {metrics.failed_jobs > 0 ? (
        <div className="mt-3">
          <Link
            href="/admin/documents"
            className="text-xs font-semibold text-[#3525cd] hover:underline"
          >
            View failed documents →
          </Link>
        </div>
      ) : null}
    </SectionCard>
  );
}

function StorageMetricsSection({ metrics }: { metrics: StorageMetrics }) {
  const failedPct =
    metrics.total_documents > 0
      ? metrics.failed_documents / metrics.total_documents
      : 0;
  const failedStatus: SignalStatus =
    failedPct > 0.1 ? "degraded" : "healthy";

  return (
    <SectionCard
      title="Storage and documents"
      badge={signalBadgeLabel(failedStatus)}
      badgeClass={signalBadgeClass(failedStatus)}
    >
      <dl className="space-y-2">
        <MetricRow
          label="Total documents"
          value={formatCount(metrics.total_documents)}
        />
        <MetricRow
          label="Indexed"
          value={formatCount(metrics.indexed_documents)}
        />
        <MetricRow
          label="Failed / blocked"
          value={formatCount(metrics.failed_documents)}
        />
        <MetricRow
          label="Pending / processing"
          value={formatCount(metrics.pending_documents)}
        />
        <MetricRow
          label="Total chunks"
          value={formatCount(metrics.total_chunks)}
        />
      </dl>
      {metrics.failed_documents > 0 ? (
        <div className="mt-3">
          <Link
            href="/admin/documents"
            className="text-xs font-semibold text-[#3525cd] hover:underline"
          >
            Review failed documents →
          </Link>
        </div>
      ) : null}
    </SectionCard>
  );
}

function SnapshotTimestamp({ snapshot }: { snapshot: ObservabilitySnapshot }) {
  const dt = new Date(snapshot.generated_at);
  const label = Number.isNaN(dt.getTime())
    ? snapshot.generated_at
    : dt.toLocaleString();
  return (
    <p className="text-xs text-[#6a6780]">
      Snapshot generated at {label} — range {snapshot.range.from} to{" "}
      {snapshot.range.to}
    </p>
  );
}

export function AdminObservabilityPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const [timeRange, setTimeRange] = useState<TimeRangeOption>("30d");
  const queryDates = resolveQueryDates(timeRange);

  const snapshotQuery = useQuery({
    queryKey: queryKeys.admin.observability(queryDates),
    queryFn: () => getObservabilitySnapshot(queryDates),
    enabled: isAdminUser,
  });

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin observability restricted"
          description="Only owner and admin roles can access the observability dashboard."
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Admin
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Observability
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              API health, LLM error rates, indexing reliability, and storage
              status across your deployment.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {TIME_RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setTimeRange(opt.value)}
                className={`rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors ${
                  timeRange === opt.value
                    ? "border-[#3525cd] bg-[#3525cd] text-white"
                    : "border-[#cbc5e6] text-[#3e376f] hover:bg-[#f5f3ff]"
                }`}
              >
                {opt.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void snapshotQuery.refetch()}
              disabled={snapshotQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {snapshotQuery.isFetching ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>
      </header>

      {snapshotQuery.isLoading ? (
        <LoadingState
          compact
          className="rounded-2xl border border-[#d7d4e8] bg-white px-5 py-8 shadow-sm"
          title="Loading observability snapshot..."
        />
      ) : snapshotQuery.isError ? (
        <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <ErrorState
            compact
            error={snapshotQuery.error}
            description={getApiErrorMessage(snapshotQuery.error)}
            onRetry={() => void snapshotQuery.refetch()}
          />
        </div>
      ) : snapshotQuery.data ? (
        <>
          <div className="rounded-2xl border border-[#d7d4e8] bg-white px-5 py-3 shadow-sm">
            <SnapshotTimestamp snapshot={snapshotQuery.data} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ApiMetricsSection metrics={snapshotQuery.data.api_metrics} />
            <LlmMetricsSection metrics={snapshotQuery.data.llm_metrics} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <IndexingMetricsSection
              metrics={snapshotQuery.data.indexing_metrics}
            />
            <StorageMetricsSection
              metrics={snapshotQuery.data.storage_metrics}
            />
          </div>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-lg font-bold text-[#2a2640]">
              Related admin pages
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  href: "/admin/system-health",
                  label: "System health",
                  note: "Dependency health checks",
                },
                {
                  href: "/admin/failed-jobs",
                  label: "Failed jobs",
                  note: "Retry and resolve failed tasks",
                },
                {
                  href: "/admin/audit-logs",
                  label: "Audit logs",
                  note: "Full event audit trail",
                },
                {
                  href: "/admin/usage",
                  label: "Usage analytics",
                  note: "Token and cost trends",
                },
              ].map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 hover:bg-[#f1edff]"
                >
                  <p className="text-sm font-semibold text-[#3525cd]">
                    {link.label}
                  </p>
                  <p className="mt-0.5 text-xs text-[#6d6985]">{link.note}</p>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
