"use client";

import { useMemo, useState, type FormEvent } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import {
  getUsageSummary,
  listAuditLogs,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  canViewAdminUsage,
  DASHBOARD_RANGE_PRESETS,
  formatInteger,
  formatLatencyMs,
  formatPercentage,
  formatUsd,
  resolveUsageDateRange,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError, sanitizeRequestId } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

const AUDIT_PAGE_LIMIT = 20;

type AppliedFilters = {
  userId: string | null;
  action: string | null;
};

function trimToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function formatTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function eventCaption(item: AuditLogListItemResponse): string {
  const resourceId = item.resource_id ? `:${item.resource_id}` : "";
  return `${item.resource_type}${resourceId}`;
}

export function AdminPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [userIdInput, setUserIdInput] = useState("");
  const [actionInput, setActionInput] = useState("");
  const [auditOffset, setAuditOffset] = useState(0);
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({
    userId: null,
    action: null,
  });

  const usageRange = useMemo(() => resolveUsageDateRange(rangePreset), [rangePreset]);

  const usageQuery = useQuery({
    queryKey: queryKeys.admin.usage({
      from: usageRange.from,
      to: usageRange.to,
      granularity: "day",
      user_id: appliedFilters.userId,
    }),
    queryFn: () =>
      getUsageSummary({
        from: usageRange.from,
        to: usageRange.to,
        granularity: "day",
        user_id: appliedFilters.userId ?? undefined,
      }),
    enabled: isAdminUser,
  });

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs({
      from: usageRange.from,
      to: usageRange.to,
      limit: AUDIT_PAGE_LIMIT,
      offset: auditOffset,
      user_id: appliedFilters.userId,
      action: appliedFilters.action,
    }),
    queryFn: () =>
      listAuditLogs({
        from: usageRange.from,
        to: usageRange.to,
        limit: AUDIT_PAGE_LIMIT,
        offset: auditOffset,
        user_id: appliedFilters.userId ?? undefined,
        action: appliedFilters.action ?? undefined,
      }),
    enabled: isAdminUser,
  });

  const forbiddenError =
    (usageQuery.isError && isForbiddenError(usageQuery.error) && usageQuery.error) ||
    (auditQuery.isError && isForbiddenError(auditQuery.error) && auditQuery.error) ||
    null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin usage restricted"
          description="Only owner and admin roles can access usage and audit analytics."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin analytics are unavailable"
          description="Your role no longer has permission to access this analytics surface."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const usage = usageQuery.data;
  const audit = auditQuery.data;
  const auditTotal = audit?.total ?? 0;
  const auditPageStart = auditTotal === 0 ? 0 : auditOffset + 1;
  const auditPageEnd = auditTotal === 0 ? 0 : Math.min(auditOffset + AUDIT_PAGE_LIMIT, auditTotal);
  const hasPreviousAuditPage = auditOffset > 0;
  const hasNextAuditPage = auditOffset + AUDIT_PAGE_LIMIT < auditTotal;

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setAuditOffset(0);
    setAppliedFilters({
      userId: trimToNull(userIdInput),
      action: trimToNull(actionInput),
    });
  }

  function clearFilters(): void {
    setUserIdInput("");
    setActionInput("");
    setAuditOffset(0);
    setAppliedFilters({ userId: null, action: null });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Admin</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Usage and audit analytics
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Review organization-scoped token usage, estimated cost, and recent operational audit events.
            </p>
          </div>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
            Date range
            <select
              value={rangePreset}
              onChange={(event) => {
                setAuditOffset(0);
                setRangePreset(event.target.value as DashboardRangePreset);
              }}
              className="h-9 min-w-[150px] rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            >
              {DASHBOARD_RANGE_PRESETS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <form className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]" onSubmit={applyFilters}>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
            User ID filter
            <input
              value={userIdInput}
              onChange={(event) => setUserIdInput(event.target.value)}
              placeholder="UUID (optional)"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
            Action filter
            <input
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              placeholder="e.g. chat.query.completed"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <button
            type="submit"
            className="h-9 self-end rounded-lg bg-[#3525cd] px-3 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={clearFilters}
            className="h-9 self-end rounded-lg border border-[#d2cee6] px-3 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
          >
            Reset
          </button>
        </form>
      </section>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Usage events"
          value={formatInteger(usage?.totals.event_count)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Input tokens"
          value={formatInteger(usage?.totals.input_tokens)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Output tokens"
          value={formatInteger(usage?.totals.output_tokens)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Estimated cost"
          value={formatUsd(usage?.totals.cost_usd)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Average confidence"
          value={formatPercentage(usage?.totals.avg_confidence)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Average latency"
          value={formatLatencyMs(usage?.totals.avg_latency_ms)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
        <MetricCard
          title="Audit events"
          value={formatInteger(audit?.total)}
          loading={auditQuery.isLoading}
          error={auditQuery.isError ? getApiErrorMessage(auditQuery.error) : null}
        />
        <MetricCard
          title="Series points"
          value={formatInteger(usage?.series.length)}
          loading={usageQuery.isLoading}
          error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
        />
      </div>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Usage trend</h2>
        <p className="mt-2 text-sm text-[#68647b]">
          Date range: <span className="font-semibold">{usageRange.from}</span> to{" "}
          <span className="font-semibold">{usageRange.to}</span>
        </p>
        {usageQuery.isLoading ? <p className="mt-3 text-sm text-[#68647b]">Loading usage trend...</p> : null}
        {usageQuery.isError ? (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-rose-700">{getApiErrorMessage(usageQuery.error)}</p>
            <button
              type="button"
              onClick={() => {
                void usageQuery.refetch();
              }}
              className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
            >
              Retry
            </button>
          </div>
        ) : null}
        {usageQuery.isSuccess && usage?.series.length === 0 ? (
          <p className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
            No usage events were recorded in this range.
          </p>
        ) : null}
        {usageQuery.isSuccess && usage && usage.series.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
              <thead>
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                  <th className="px-3 py-2">Period</th>
                  <th className="px-3 py-2">Events</th>
                  <th className="px-3 py-2">Input</th>
                  <th className="px-3 py-2">Output</th>
                  <th className="px-3 py-2">Cost</th>
                  <th className="px-3 py-2">Confidence</th>
                  <th className="px-3 py-2">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f0edf8]">
                {usage.series.map((point) => (
                  <tr key={`${point.period_start}:${point.period_end}`}>
                    <td className="px-3 py-2 font-medium text-[#2f2a46]">
                      {point.period_start}
                      {point.period_end !== point.period_start ? ` to ${point.period_end}` : ""}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatInteger(point.event_count)}</td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatInteger(point.input_tokens)}</td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatInteger(point.output_tokens)}</td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatUsd(point.cost_usd)}</td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatPercentage(point.avg_confidence)}</td>
                    <td className="px-3 py-2 text-[#4d4963]">{formatLatencyMs(point.avg_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-lg font-bold text-[#2a2640]">Recent audit activity</h2>
          {auditQuery.isSuccess ? (
            <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Showing {formatInteger(auditPageStart)}-{formatInteger(auditPageEnd)} of{" "}
              {formatInteger(auditTotal)}
            </p>
          ) : null}
        </div>
        {auditQuery.isLoading ? <p className="mt-3 text-sm text-[#68647b]">Loading recent activity...</p> : null}
        {auditQuery.isError ? (
          <div className="mt-3 space-y-2">
            <p className="text-sm text-rose-700">{getApiErrorMessage(auditQuery.error)}</p>
            <button
              type="button"
              onClick={() => {
                void auditQuery.refetch();
              }}
              className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
            >
              Retry
            </button>
          </div>
        ) : null}
        {auditQuery.isSuccess && audit?.items.length === 0 ? (
          <p className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]">
            No audit events were found for the selected range and filters.
          </p>
        ) : null}
        {auditQuery.isSuccess && audit && audit.items.length > 0 ? (
          <>
            <ul className="mt-4 space-y-2">
              {audit.items.map((item) => (
                <li key={item.audit_log_id} className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-3">
                  <p className="text-sm font-semibold text-[#2f2a46]">{item.action}</p>
                  <p className="mt-1 text-xs text-[#5f5a74]">
                    {eventCaption(item)} • {formatTimestamp(item.created_at)}
                  </p>
                  {sanitizeRequestId(item.request_id) ? (
                    <p className="mt-1 text-xs text-[#5f5a74]">
                      Trace ID: <span className="font-semibold">{sanitizeRequestId(item.request_id)}</span>
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => {
                  setAuditOffset((previous) => Math.max(0, previous - AUDIT_PAGE_LIMIT));
                }}
                disabled={!hasPreviousAuditPage || auditQuery.isFetching}
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] enabled:hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => {
                  setAuditOffset((previous) => previous + AUDIT_PAGE_LIMIT);
                }}
                disabled={!hasNextAuditPage || auditQuery.isFetching}
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] enabled:hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </>
        ) : null}
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Quick actions</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            href="/documents"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Documents
          </Link>
          <Link
            href="/chat"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Chats
          </Link>
          <Link
            href="/evaluations"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Evaluations
          </Link>
          <Link
            href="/rag-pipeline"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Pipeline Explorer
          </Link>
        </div>
      </section>
    </section>
  );
}

function MetricCard({
  title,
  value,
  loading,
  error,
}: {
  title: string;
  value: string;
  loading: boolean;
  error: string | null;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-[#6f6a8d]">{title}</p>
      {loading ? <p className="text-2xl font-extrabold text-[#2a2640]">Loading...</p> : null}
      {!loading && error ? (
        <p className="text-sm font-semibold text-rose-700">Unable to load: {error}</p>
      ) : null}
      {!loading && !error ? <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p> : null}
    </article>
  );
}
