"use client";

import { useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getGraphObservabilitySnapshot,
  type GraphAlertItem,
  type GraphEntityMetrics,
  type GraphExtractionMetrics,
  type GraphObservabilitySnapshot,
  type GraphQueryMetrics,
  type GraphRelationMetrics,
  type GraphTrendPoint,
} from "@/lib/api/graph-observability";
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

function formatCount(value: number): string {
  return value.toLocaleString();
}

function formatFloat(value: number | null | undefined, decimals = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
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

function GraphStatusBanner({
  graphEnabled,
  neo4jReachable,
}: {
  graphEnabled: boolean;
  neo4jReachable: boolean;
}) {
  if (!graphEnabled) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        Enterprise Graph is disabled. Set{" "}
        <code className="rounded bg-slate-200 px-1">
          ENTERPRISE_GRAPH_ENABLED=true
        </code>{" "}
        to activate Neo4j integration.
      </div>
    );
  }
  if (!neo4jReachable) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        Neo4j is configured but currently unreachable. Entity and relation
        metrics are unavailable until the connection is restored.
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      Neo4j Enterprise Graph is connected and operational.
    </div>
  );
}

function AlertsSection({ alerts }: { alerts: GraphAlertItem[] }) {
  if (alerts.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold text-[#2a2640]">Active alerts</h2>
      {alerts.map((alert, idx) => (
        <div
          key={idx}
          className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${
            alert.level === "critical"
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-amber-200 bg-amber-50 text-amber-800"
          }`}
        >
          <span className="mt-0.5 shrink-0 text-[10px] font-semibold tracking-wide uppercase">
            {alert.level}
          </span>
          <p>{alert.message}</p>
        </div>
      ))}
    </section>
  );
}

function ExtractionMetricsSection({
  metrics,
}: {
  metrics: GraphExtractionMetrics;
}) {
  const status = resolveSignalStatus(
    metrics.success_rate != null ? 1 - metrics.success_rate : null,
    0.2,
  );
  return (
    <SectionCard
      title="Extraction runs"
      badge={signalBadgeLabel(status)}
      badgeClass={signalBadgeClass(status)}
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="extraction run" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total documents processed"
            value={formatCount(metrics.total_runs)}
          />
          <MetricRow label="Completed" value={formatCount(metrics.succeeded)} />
          <MetricRow label="Failed" value={formatCount(metrics.failed)} />
          <MetricRow label="In progress" value={formatCount(metrics.running)} />
          <MetricRow label="Skipped" value={formatCount(metrics.skipped)} />
          <MetricRow
            label="Success rate"
            value={formatPct(metrics.success_rate)}
          />
        </dl>
      )}
    </SectionCard>
  );
}

function EntityMetricsSection({ metrics }: { metrics: GraphEntityMetrics }) {
  const lowConfRate =
    metrics.total_entities > 0
      ? metrics.low_confidence_count / metrics.total_entities
      : null;
  const status = resolveSignalStatus(lowConfRate, 0.3);
  return (
    <SectionCard
      title="Entity quality"
      badge={metrics.telemetry_missing ? "No data" : signalBadgeLabel(status)}
      badgeClass={
        metrics.telemetry_missing
          ? "bg-slate-200 text-slate-700"
          : signalBadgeClass(status)
      }
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="entity" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total entities"
            value={formatCount(metrics.total_entities)}
          />
          <MetricRow
            label="Avg confidence"
            value={formatFloat(metrics.avg_confidence)}
          />
          <MetricRow
            label="Low-confidence entities"
            value={formatCount(metrics.low_confidence_count)}
            note="< 0.5"
          />
          {metrics.by_type.slice(0, 5).map((t) => (
            <MetricRow
              key={t.entity_type}
              label={t.entity_type}
              value={formatCount(t.count)}
              note={
                t.avg_confidence != null
                  ? `avg conf ${t.avg_confidence.toFixed(2)}`
                  : undefined
              }
            />
          ))}
        </dl>
      )}
    </SectionCard>
  );
}

function RelationMetricsSection({
  metrics,
}: {
  metrics: GraphRelationMetrics;
}) {
  return (
    <SectionCard
      title="Relation quality"
      badge={metrics.telemetry_missing ? "No data" : "Connected"}
      badgeClass={
        metrics.telemetry_missing
          ? "bg-slate-200 text-slate-700"
          : "bg-emerald-100 text-emerald-800"
      }
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="relation" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total relations"
            value={formatCount(metrics.total_relations)}
          />
          <MetricRow
            label="Avg confidence"
            value={formatFloat(metrics.avg_confidence)}
          />
          <MetricRow
            label="Low-confidence relations"
            value={formatCount(metrics.low_confidence_count)}
            note="< 0.5"
          />
        </dl>
      )}
    </SectionCard>
  );
}

function GraphQueryMetricsSection({ metrics }: { metrics: GraphQueryMetrics }) {
  const status = resolveSignalStatus(metrics.failure_rate, 0.1);
  return (
    <SectionCard
      title="GraphRAG queries"
      badge={signalBadgeLabel(status)}
      badgeClass={signalBadgeClass(status)}
    >
      {metrics.telemetry_missing ? (
        <MissingTelemetryNotice entity="GraphRAG query" />
      ) : (
        <dl className="space-y-2">
          <MetricRow
            label="Total GraphRAG queries"
            value={formatCount(metrics.graphrag_queries)}
          />
          <MetricRow
            label="Failed queries"
            value={formatCount(metrics.graphrag_failures)}
          />
          <MetricRow
            label="Failure rate"
            value={formatPct(metrics.failure_rate)}
          />
          <MetricRow
            label="Avg expansion size"
            value={formatFloat(metrics.avg_expansion_size)}
            note="entities per query"
          />
          <MetricRow
            label="Avg latency"
            value={formatFloat(metrics.avg_latency_ms)}
            note="ms"
          />
          <MetricRow
            label="p95 latency"
            value={formatFloat(metrics.p95_latency_ms)}
            note="ms"
          />
          <MetricRow
            label="Fallback to standard RAG"
            value={formatCount(metrics.fallback_to_rag)}
          />
          <MetricRow
            label="Fallback rate"
            value={formatPct(metrics.fallback_rate)}
          />
          <MetricRow
            label="Neo4j/Cypher failures"
            value={formatCount(metrics.cypher_failures)}
          />
          <MetricRow
            label="Failure rate"
            value={formatPct(metrics.cypher_failure_rate)}
            note="Neo4j availability"
          />
        </dl>
      )}
    </SectionCard>
  );
}

function TrendRow({ point }: { point: GraphTrendPoint }) {
  return (
    <div className="grid grid-cols-5 gap-3 border-t border-[#ece8f8] py-2 text-sm first:border-t-0 first:pt-0">
      <div className="font-medium text-[#2f2a46]">
        {new Date(point.day).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })}
      </div>
      <div>{formatPct(point.extraction_failure_rate)}</div>
      <div>{formatPct(point.graphrag_failure_rate)}</div>
      <div>{formatFloat(point.avg_latency_ms)}</div>
      <div>{formatCount(point.cypher_failures)}</div>
    </div>
  );
}

function TrendsSection({ trends }: { trends: GraphTrendPoint[] }) {
  const recentTrends = trends.slice(-7);
  return (
    <SectionCard title="Quality trends">
      {recentTrends.length === 0 ? (
        <MissingTelemetryNotice entity="trend" />
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-5 gap-3 border-b border-[#ece8f8] pb-2 text-[11px] font-semibold tracking-wide text-[#6d6985] uppercase">
            <div>Day</div>
            <div>Extract fail</div>
            <div>Graph fail</div>
            <div>Avg latency</div>
            <div>Cypher fails</div>
          </div>
          {recentTrends.map((point) => (
            <TrendRow key={point.day} point={point} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function ThresholdsSection({
  snapshot,
}: {
  snapshot: GraphObservabilitySnapshot;
}) {
  const t = snapshot.thresholds;
  return (
    <SectionCard title="Alert thresholds">
      <dl className="space-y-2">
        <MetricRow
          label="Extraction failure rate max"
          value={formatPct(t.extraction_failure_rate_max)}
          note="env: GRAPH_ALERT_EXTRACTION_FAILURE_RATE_MAX"
        />
        <MetricRow
          label="GraphRAG query failure rate max"
          value={formatPct(t.query_failure_rate_max)}
          note="env: GRAPH_ALERT_QUERY_FAILURE_RATE_MAX"
        />
        <MetricRow
          label="GraphRAG fallback rate max"
          value={formatPct(t.graphrag_fallback_rate_max)}
          note="env: GRAPH_ALERT_GRAPHRAG_FALLBACK_RATE_MAX"
        />
        <MetricRow
          label="Low-confidence entity rate max"
          value={formatPct(t.low_confidence_entity_rate_max)}
          note="env: GRAPH_ALERT_LOW_CONFIDENCE_ENTITY_RATE_MAX"
        />
        <MetricRow
          label="GraphRAG latency p95 max"
          value={formatCount(Math.round(t.query_latency_ms_max))}
          note="env: GRAPH_ALERT_QUERY_LATENCY_MS_MAX"
        />
      </dl>
      <p className="mt-3 text-[11px] text-[#6d6985]">
        Thresholds are set via environment variables. Use{" "}
        <Link
          href="/admin/feature-flags"
          className="underline hover:text-[#2a2640]"
        >
          Feature flags
        </Link>{" "}
        to toggle graph_extraction, graph_explorer, and graph_rag per
        organization.
      </p>
    </SectionCard>
  );
}

export function AdminGraphObservabilityPage() {
  const {
    state: { session },
  } = useAuthSession();
  const [timeRange, setTimeRange] = useState<TimeRangeOption>("30d");

  const queryDates = resolveQueryDates(timeRange);

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "graph-observability", queryDates],
    queryFn: () => getGraphObservabilitySnapshot(queryDates),
    enabled: !!session,
  });

  if (!session || !canViewAdminUsage(session.role)) {
    return <ForbiddenState />;
  }

  if (isLoading) return <LoadingState title="Loading graph observability…" />;

  if (error) {
    return <ErrorState error={error} />;
  }

  if (!data) return null;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#2a2640]">
            Graph observability
          </h1>
          <p className="mt-1 text-sm text-[#6d6985]">
            Enterprise Graph extraction health, entity/relation quality, and
            GraphRAG query performance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {TIME_RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setTimeRange(opt.value)}
              className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                timeRange === opt.value
                  ? "bg-[#6c63ff] text-white"
                  : "bg-[#f0eeff] text-[#6c63ff] hover:bg-[#e4e1ff]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <GraphStatusBanner
        graphEnabled={data.graph_enabled}
        neo4jReachable={data.neo4j_reachable}
      />

      <AlertsSection alerts={data.alerts} />

      <div className="grid gap-6 sm:grid-cols-2">
        <ExtractionMetricsSection metrics={data.extraction} />
        <GraphQueryMetricsSection metrics={data.queries} />
        <EntityMetricsSection metrics={data.entities} />
        <RelationMetricsSection metrics={data.relations} />
      </div>

      <TrendsSection trends={data.trends} />

      <ThresholdsSection snapshot={data} />

      <p className="text-right text-[11px] text-[#9491a8]">
        Generated at{" "}
        {new Date(data.generated_at).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })}
      </p>
    </div>
  );
}
