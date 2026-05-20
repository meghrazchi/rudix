"use client";

import { useMemo } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import { getTopBarNotifications } from "@/lib/api/notifications";
import { listDocuments } from "@/lib/api/documents";
import { listAuditLogs, getUsageSummary, type AuditLogListItemResponse } from "@/lib/api/admin-usage";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { formatLatencyMs, formatPercentage, formatUsd, resolveUsageDateRange } from "@/lib/dashboard";
import { resolveNotificationsEndpoint, isExternalHref } from "@/lib/top-bar";
import { useAuthSession } from "@/lib/use-auth-session";

type MonitoringSeverity = "critical" | "high" | "medium" | "low" | "info";

type MonitoringEvent = {
  id: string;
  title: string;
  details: string;
  createdAt: string;
  severity: MonitoringSeverity;
  href?: string | null;
};

type MonitoringPanel = {
  key: string;
  title: string;
  href: string | null;
};

const FAILED_DOCUMENTS_LIMIT = 8;
const AUDIT_EVENTS_LIMIT = 60;
const RECENT_EVENTS_LIMIT = 6;

function trimToNull(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseFloatEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return parsed;
}

function parseIntEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return parsed;
}

function isSafeMonitoringHref(value: string): boolean {
  return value.startsWith("/") || /^https?:\/\//i.test(value);
}

function resolveConfiguredHref(value: string | undefined): string | null {
  const trimmed = trimToNull(value);
  if (!trimmed) {
    return null;
  }
  if (!isSafeMonitoringHref(trimmed)) {
    return null;
  }
  return trimmed;
}

function resolveMonitoringPanels(): MonitoringPanel[] {
  return [
    {
      key: "monitoring",
      title: "Monitoring dashboard",
      href: resolveConfiguredHref(process.env.NEXT_PUBLIC_ADMIN_MONITORING_URL),
    },
    {
      key: "sentry",
      title: "Sentry",
      href: resolveConfiguredHref(process.env.NEXT_PUBLIC_SENTRY_URL),
    },
    {
      key: "logs",
      title: "Logs",
      href: resolveConfiguredHref(process.env.NEXT_PUBLIC_LOGS_URL),
    },
    {
      key: "metrics",
      title: "Metrics",
      href: resolveConfiguredHref(process.env.NEXT_PUBLIC_METRICS_URL),
    },
    {
      key: "tracing",
      title: "Tracing",
      href: resolveConfiguredHref(process.env.NEXT_PUBLIC_TRACING_URL),
    },
  ];
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }
  return new Date(parsed).toLocaleString();
}

function extractNumericValue(
  record: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const key of keys) {
    const candidate = record[key];
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
    if (typeof candidate === "string") {
      const parsed = Number.parseFloat(candidate);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

function hasFailureStatusCode(record: Record<string, unknown>): boolean {
  const statusCode = extractNumericValue(record, ["status_code", "statusCode", "http_status"]);
  return statusCode !== null && statusCode >= 500;
}

function isFailedEvaluationEvent(event: AuditLogListItemResponse): boolean {
  const action = event.action.toLowerCase();
  if (!action.includes("evaluation")) {
    return false;
  }
  if (action.includes("failed")) {
    return true;
  }
  return hasFailureStatusCode(event.metadata);
}

function isLowConfidenceEvent(
  event: AuditLogListItemResponse,
  threshold: number,
): boolean {
  const action = event.action.toLowerCase();
  if (!action.includes("chat") && !action.includes("query")) {
    return false;
  }
  if (action.includes("low_confidence")) {
    return true;
  }
  const confidence = extractNumericValue(event.metadata, [
    "confidence",
    "answer_confidence",
    "avg_confidence",
    "confidence_score",
  ]);
  if (confidence == null) {
    return false;
  }
  return confidence < threshold;
}

function isHighLatencyEvent(
  event: AuditLogListItemResponse,
  thresholdMs: number,
): boolean {
  const action = event.action.toLowerCase();
  if (!action.includes("chat") && !action.includes("query")) {
    return false;
  }
  if (action.includes("high_latency")) {
    return true;
  }
  const latencyMs = extractNumericValue(event.metadata, [
    "latency_ms",
    "avg_latency_ms",
    "duration_ms",
    "answer_latency_ms",
  ]);
  if (latencyMs == null) {
    return false;
  }
  return latencyMs >= thresholdMs;
}

function sortByCreatedAtDesc<T extends { createdAt: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftValue = Date.parse(left.createdAt);
    const rightValue = Date.parse(right.createdAt);
    if (Number.isNaN(leftValue) || Number.isNaN(rightValue)) {
      return 0;
    }
    return rightValue - leftValue;
  });
}

function severityBadgeClass(severity: MonitoringSeverity): string {
  if (severity === "critical") {
    return "bg-rose-100 text-rose-800";
  }
  if (severity === "high") {
    return "bg-amber-100 text-amber-800";
  }
  if (severity === "medium") {
    return "bg-orange-100 text-orange-800";
  }
  if (severity === "low") {
    return "bg-sky-100 text-sky-800";
  }
  return "bg-slate-200 text-slate-700";
}

function severityLabel(severity: MonitoringSeverity): string {
  if (severity === "critical") {
    return "Critical";
  }
  if (severity === "high") {
    return "High";
  }
  if (severity === "medium") {
    return "Medium";
  }
  if (severity === "low") {
    return "Low";
  }
  return "Info";
}

function MetricCard({
  title,
  value,
  caption,
  severity,
}: {
  title: string;
  value: string;
  caption: string;
  severity: MonitoringSeverity;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-bold text-[#2a2640]">{title}</h3>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${severityBadgeClass(
            severity,
          )}`}
        >
          {severityLabel(severity)}
        </span>
      </div>
      <p className="mt-2 text-2xl font-extrabold text-[#2a2640]">{value}</p>
      <p className="mt-2 text-xs text-[#6a6780]">{caption}</p>
    </article>
  );
}

export function AdminMonitoringPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const monitoringPanels = useMemo(() => resolveMonitoringPanels(), []);
  const configuredMonitoringLinks = monitoringPanels.filter((panel) => panel.href);
  const notificationsEndpoint = useMemo(() => resolveNotificationsEndpoint(), []);
  const usageRange = useMemo(() => resolveUsageDateRange("30d"), []);
  const lowConfidenceThreshold = parseFloatEnv(
    process.env.NEXT_PUBLIC_MONITORING_LOW_CONFIDENCE_THRESHOLD,
    0.65,
  );
  const highLatencyThresholdMs = parseIntEnv(
    process.env.NEXT_PUBLIC_MONITORING_HIGH_LATENCY_MS_THRESHOLD,
    2000,
  );

  const failedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      limit: FAILED_DOCUMENTS_LIMIT,
      offset: 0,
      status: "failed",
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        limit: FAILED_DOCUMENTS_LIMIT,
        offset: 0,
        status: "failed",
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    enabled: isAdminUser,
  });

  const usageQuery = useQuery({
    queryKey: queryKeys.admin.usage({
      from: usageRange.from,
      to: usageRange.to,
      granularity: "day",
    }),
    queryFn: () =>
      getUsageSummary({
        from: usageRange.from,
        to: usageRange.to,
        granularity: "day",
      }),
    enabled: isAdminUser,
  });

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs({
      from: usageRange.from,
      to: usageRange.to,
      limit: AUDIT_EVENTS_LIMIT,
      offset: 0,
    }),
    queryFn: () =>
      listAuditLogs({
        from: usageRange.from,
        to: usageRange.to,
        limit: AUDIT_EVENTS_LIMIT,
        offset: 0,
      }),
    enabled: isAdminUser,
  });

  const notificationsQuery = useQuery({
    queryKey: notificationsEndpoint
      ? queryKeys.topBar.notifications(notificationsEndpoint)
      : ["admin", "monitoring", "notifications", "none"],
    queryFn: () => getTopBarNotifications(notificationsEndpoint as string),
    enabled: isAdminUser && Boolean(notificationsEndpoint),
  });

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin monitoring restricted"
          description="Only owner and admin roles can access monitoring resources."
          compact={false}
        />
      </section>
    );
  }

  const failedDocuments = failedDocumentsQuery.data?.items ?? [];
  const failedDocumentsTotal = failedDocumentsQuery.data?.total ?? 0;
  const auditItems = auditQuery.data?.items ?? [];
  const failedEvaluationEvents = auditItems.filter((event) => isFailedEvaluationEvent(event));
  const lowConfidenceEvents = auditItems.filter((event) => isLowConfidenceEvent(event, lowConfidenceThreshold));
  const highLatencyEvents = auditItems.filter((event) => isHighLatencyEvent(event, highLatencyThresholdMs));
  const recentFailedDocuments: MonitoringEvent[] = sortByCreatedAtDesc(
    failedDocuments.map((document) => ({
      id: document.document_id,
      title: document.filename,
      details: document.error_message ?? "Document processing failed.",
      createdAt: document.updated_at,
      severity: "critical" as const,
      href: `/documents/${encodeURIComponent(document.document_id)}`,
    })),
  ).slice(0, RECENT_EVENTS_LIMIT);
  const recentFailedEvaluations: MonitoringEvent[] = sortByCreatedAtDesc(
    failedEvaluationEvents.map((event) => ({
      id: event.audit_log_id,
      title: event.action,
      details: event.resource_id
        ? `Evaluation run ${event.resource_id} failed.`
        : "Evaluation run failed.",
      createdAt: event.created_at,
      severity: "high" as const,
      href: "/evaluations",
    })),
  ).slice(0, RECENT_EVENTS_LIMIT);
  const recentLowConfidence: MonitoringEvent[] = sortByCreatedAtDesc(
    lowConfidenceEvents.map((event) => ({
      id: event.audit_log_id,
      title: "Low-confidence chat answer",
      details: event.action,
      createdAt: event.created_at,
      severity: "medium" as const,
      href: "/chat",
    })),
  ).slice(0, RECENT_EVENTS_LIMIT);
  const recentHighLatency: MonitoringEvent[] = sortByCreatedAtDesc(
    highLatencyEvents.map((event) => ({
      id: event.audit_log_id,
      title: "High-latency chat event",
      details: event.action,
      createdAt: event.created_at,
      severity: "medium" as const,
      href: "/chat",
    })),
  ).slice(0, RECENT_EVENTS_LIMIT);

  const endpointUnavailable =
    notificationsQuery.isError &&
    isApiClientError(notificationsQuery.error) &&
    notificationsQuery.error.status === 404;
  const notificationsAvailable = Boolean(notificationsEndpoint) && !endpointUnavailable;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Admin</p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Monitoring</h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Track failed jobs, latency and confidence risks, and observability links without leaving Rudix.
        </p>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-bold text-[#2a2640]">Monitoring overview</h2>

        {usageQuery.isLoading || auditQuery.isLoading || failedDocumentsQuery.isLoading ? (
          <LoadingState
            compact
            className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title="Loading monitoring signals..."
          />
        ) : null}

        {usageQuery.isError || auditQuery.isError || failedDocumentsQuery.isError ? (
          <div className="mb-3">
            <ErrorState
              compact
              error={usageQuery.error ?? auditQuery.error ?? failedDocumentsQuery.error}
              description={getApiErrorMessage(
                usageQuery.error ?? auditQuery.error ?? failedDocumentsQuery.error,
              )}
              onRetry={() => {
                void Promise.all([
                  usageQuery.refetch(),
                  auditQuery.refetch(),
                  failedDocumentsQuery.refetch(),
                ]);
              }}
            />
          </div>
        ) : null}

        {!usageQuery.isLoading &&
        !auditQuery.isLoading &&
        !failedDocumentsQuery.isLoading &&
        !usageQuery.isError &&
        !auditQuery.isError &&
        !failedDocumentsQuery.isError ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              title="Failed document jobs"
              value={failedDocumentsTotal.toString()}
              caption="Documents currently in failed lifecycle state."
              severity={failedDocumentsTotal > 0 ? "critical" : "low"}
            />
            <MetricCard
              title="Failed evaluation runs"
              value={failedEvaluationEvents.length.toString()}
              caption="Recent failed evaluation events from audit logs."
              severity={failedEvaluationEvents.length > 0 ? "high" : "low"}
            />
            <MetricCard
              title="Low-confidence events"
              value={lowConfidenceEvents.length.toString()}
              caption={`Chat events below confidence ${Math.round(lowConfidenceThreshold * 100)}%.`}
              severity={lowConfidenceEvents.length > 0 ? "medium" : "low"}
            />
            <MetricCard
              title="High-latency events"
              value={highLatencyEvents.length.toString()}
              caption={`Chat events above ${highLatencyThresholdMs} ms.`}
              severity={highLatencyEvents.length > 0 ? "medium" : "low"}
            />
          </div>
        ) : null}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#2a2640]">Recent failed document jobs</h2>
          {failedDocumentsQuery.isLoading ? (
            <LoadingState compact title="Loading failed document jobs..." />
          ) : failedDocumentsQuery.isError ? (
            <ErrorState
              compact
              error={failedDocumentsQuery.error}
              description={getApiErrorMessage(failedDocumentsQuery.error)}
              onRetry={() => {
                void failedDocumentsQuery.refetch();
              }}
            />
          ) : recentFailedDocuments.length === 0 ? (
            <EmptyState
              compact
              title="No failed document jobs in the selected window."
              description="Failures will appear here when processing or indexing errors are emitted."
            />
          ) : (
            <ul className="space-y-2">
              {recentFailedDocuments.map((event) => (
                <li key={event.id} className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-semibold text-rose-900">{event.title}</p>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${severityBadgeClass(
                        event.severity,
                      )}`}
                    >
                      {severityLabel(event.severity)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-rose-800">{event.details}</p>
                  <p className="mt-1 text-[11px] text-rose-700">{formatTimestamp(event.createdAt)}</p>
                  {event.href ? (
                    <Link href={event.href} className="mt-2 inline-block text-xs font-semibold text-[#3525cd] hover:underline">
                      View document
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#2a2640]">Chat and evaluation risk signals</h2>
          {auditQuery.isLoading ? (
            <LoadingState compact title="Loading risk signals..." />
          ) : auditQuery.isError ? (
            <ErrorState
              compact
              error={auditQuery.error}
              description={getApiErrorMessage(auditQuery.error)}
              onRetry={() => {
                void auditQuery.refetch();
              }}
            />
          ) : (
            <div className="space-y-3">
              {recentFailedEvaluations.length === 0 &&
              recentLowConfidence.length === 0 &&
              recentHighLatency.length === 0 ? (
                <EmptyState
                  compact
                  title="No high-risk chat or evaluation events in this range."
                  description="Signals from audit logs appear here when they are emitted by backend services."
                />
              ) : (
                <ul className="space-y-2">
                  {[...recentFailedEvaluations, ...recentLowConfidence, ...recentHighLatency]
                    .slice(0, RECENT_EVENTS_LIMIT)
                    .map((event) => (
                      <li key={event.id} className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm font-semibold text-[#2f2a46]">{event.title}</p>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${severityBadgeClass(
                              event.severity,
                            )}`}
                          >
                            {severityLabel(event.severity)}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-[#5f5a74]">{event.details}</p>
                        <p className="mt-1 text-[11px] text-[#6d6985]">{formatTimestamp(event.createdAt)}</p>
                        {event.href ? (
                          <Link
                            href={event.href}
                            className="mt-2 inline-block text-xs font-semibold text-[#3525cd] hover:underline"
                          >
                            Open related page
                          </Link>
                        ) : null}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#2a2640]">Operational telemetry snapshot</h2>
          {usageQuery.isLoading ? (
            <LoadingState compact title="Loading telemetry metrics..." />
          ) : usageQuery.isError ? (
            <ErrorState
              compact
              error={usageQuery.error}
              description={getApiErrorMessage(usageQuery.error)}
              onRetry={() => {
                void usageQuery.refetch();
              }}
            />
          ) : (
            <dl className="grid gap-2 text-sm text-[#4f4b68]">
              <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                <dt>Average latency</dt>
                <dd className="font-semibold text-[#2f2a46]">{formatLatencyMs(usageQuery.data?.totals.avg_latency_ms)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                <dt>Average confidence</dt>
                <dd className="font-semibold text-[#2f2a46]">{formatPercentage(usageQuery.data?.totals.avg_confidence)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                <dt>Estimated cost</dt>
                <dd className="font-semibold text-[#2f2a46]">{formatUsd(usageQuery.data?.totals.cost_usd)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                <dt>Tracked events</dt>
                <dd className="font-semibold text-[#2f2a46]">{usageQuery.data?.totals.event_count ?? 0}</dd>
              </div>
            </dl>
          )}
        </article>

        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-bold text-[#2a2640]">Alert feed availability</h2>
          {!notificationsEndpoint ? (
            <EmptyState
              compact
              title="Aggregation feed is not configured for this deployment."
              description="Set NEXT_PUBLIC_TOPBAR_NOTIFICATIONS_URL to enable failed-job and usage warning cards."
            />
          ) : notificationsQuery.isLoading ? (
            <LoadingState compact title="Loading monitoring feed..." />
          ) : notificationsQuery.isError ? (
            endpointUnavailable ? (
              <EmptyState
                compact
                title="Monitoring feed endpoint is unavailable."
                description="Keep this panel feature-flagged until the aggregation endpoint is deployed."
              />
            ) : (
              <ErrorState
                compact
                error={notificationsQuery.error}
                description={getApiErrorMessage(notificationsQuery.error)}
                onRetry={() => {
                  void notificationsQuery.refetch();
                }}
              />
            )
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-[#4f4b68]">
                Feed status:{" "}
                <span className="font-semibold text-emerald-700">
                  {notificationsAvailable ? "available" : "unavailable"}
                </span>
              </p>
              {notificationsQuery.data?.items?.length ? (
                <ul className="space-y-2">
                  {notificationsQuery.data.items.slice(0, 4).map((item) => (
                    <li key={item.id} className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-semibold text-[#2f2a46]">{item.title}</p>
                        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-700">
                          {item.severity}
                        </span>
                      </div>
                      {item.message ? <p className="mt-1 text-xs text-[#5f5a74]">{item.message}</p> : null}
                      {item.created_at ? (
                        <p className="mt-1 text-[11px] text-[#6d6985]">{formatTimestamp(item.created_at)}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
                  No current alerts in the feed.
                </p>
              )}
            </div>
          )}
        </article>
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-bold text-[#2a2640]">External observability links</h2>
        {configuredMonitoringLinks.length === 0 ? (
          <EmptyState
            compact
            title="External observability links are not configured."
            description="Set NEXT_PUBLIC_ADMIN_MONITORING_URL, NEXT_PUBLIC_SENTRY_URL, NEXT_PUBLIC_LOGS_URL, NEXT_PUBLIC_METRICS_URL, or NEXT_PUBLIC_TRACING_URL."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {configuredMonitoringLinks.map((panel) => {
              const href = panel.href as string;
              const external = isExternalHref(href);
              return (
                <Link
                  key={panel.key}
                  href={href}
                  target={external ? "_blank" : undefined}
                  rel={external ? "noreferrer noopener" : undefined}
                  className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-sm font-semibold text-[#3525cd] hover:bg-[#f1edff]"
                >
                  {panel.title}
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}
