"use client";

import { useMemo, useState, type FormEvent } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getUsageSummary } from "@/lib/api/admin-usage";
import { getApiErrorMessage } from "@/lib/api/errors";
import { listDocuments } from "@/lib/api/documents";
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
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { isExternalHref } from "@/lib/top-bar";
import { useAuthSession } from "@/lib/use-auth-session";

type AppliedFilters = {
  userId: string | null;
};

function trimToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function formatPeriodLabel(start: string, end: string): string {
  if (start === end) {
    return start;
  }
  return `${start} to ${end}`;
}

function resolveUsageExportUrl(): string | null {
  if (!getFrontendRuntimeConfig().features.exports) {
    return null;
  }
  const configured = process.env.NEXT_PUBLIC_ADMIN_USAGE_EXPORT_URL?.trim();
  if (!configured) {
    return null;
  }
  return configured;
}

function withExportQuery(
  url: string,
  params: Record<string, string | undefined>,
): string {
  try {
    const parsed = new URL(url, "http://placeholder.local");
    for (const [key, value] of Object.entries(params)) {
      if (value) {
        parsed.searchParams.set(key, value);
      }
    }
    if (/^https?:\/\//i.test(url)) {
      return parsed.toString();
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function UsageMetricCard({
  title,
  value,
  caption,
  loading,
  error,
}: {
  title: string;
  value: string;
  caption: string;
  loading: boolean;
  error: string | null;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="mb-1 text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
        {title}
      </p>
      {loading ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">Loading...</p>
      ) : null}
      {!loading && error ? (
        <p className="text-sm font-semibold text-rose-700">
          Unable to load: {error}
        </p>
      ) : null}
      {!loading && !error ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p>
      ) : null}
      <p className="mt-2 text-xs text-[#6a6780]">{caption}</p>
    </article>
  );
}

function PlannedFeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <article className="rounded-2xl border border-dashed border-[#d7d4e8] bg-[#fcfbff] p-4">
      <p className="mb-1 text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
        Planned
      </p>
      <h3 className="text-sm font-bold text-[#2a2640]">{title}</h3>
      <p className="mt-1 text-sm text-[#68647b]">{description}</p>
    </article>
  );
}

export function AdminUsagePage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [userIdInput, setUserIdInput] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({
    userId: null,
  });

  const usageRange = useMemo(
    () => resolveUsageDateRange(rangePreset),
    [rangePreset],
  );
  const exportBaseUrl = resolveUsageExportUrl();

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

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      limit: 1,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        limit: 1,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    enabled: isAdminUser,
  });

  const forbiddenError =
    (usageQuery.isError &&
      isForbiddenError(usageQuery.error) &&
      usageQuery.error) ||
    (documentsQuery.isError &&
      isForbiddenError(documentsQuery.error) &&
      documentsQuery.error) ||
    null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin usage restricted"
          description="Only owner and admin roles can access usage analytics."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Usage analytics unavailable"
          description="Your role no longer has access to this analytics page."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const usage = usageQuery.data;
  const totalTokens =
    usage &&
    Number.isFinite(usage.totals.input_tokens) &&
    Number.isFinite(usage.totals.output_tokens)
      ? usage.totals.input_tokens + usage.totals.output_tokens
      : null;
  const exportUrl = exportBaseUrl
    ? withExportQuery(exportBaseUrl, {
        from: usageRange.from,
        to: usageRange.to,
        user_id: appliedFilters.userId ?? undefined,
      })
    : null;
  const exportIsExternal = exportUrl ? isExternalHref(exportUrl) : false;

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setAppliedFilters({
      userId: trimToNull(userIdInput),
    });
  }

  function clearFilters(): void {
    setUserIdInput("");
    setAppliedFilters({ userId: null });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Admin
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Usage analytics
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Review questions, documents, token usage, estimated cost, and
              latency trends.
            </p>
          </div>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Date range
            <select
              value={rangePreset}
              onChange={(event) =>
                setRangePreset(event.target.value as DashboardRangePreset)
              }
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
        <form
          className="grid gap-3 md:grid-cols-[1fr_auto_auto]"
          onSubmit={applyFilters}
        >
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            User ID filter
            <input
              value={userIdInput}
              onChange={(event) => setUserIdInput(event.target.value)}
              placeholder="UUID (optional)"
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

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <UsageMetricCard
          title="Total questions"
          value={formatInteger(usage?.totals.event_count)}
          caption="Counted from usage events in selected range."
          loading={usageQuery.isLoading}
          error={
            usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
          }
        />
        <UsageMetricCard
          title="Total documents"
          value={formatInteger(documentsQuery.data?.total)}
          caption="Accessible documents in current organization."
          loading={documentsQuery.isLoading}
          error={
            documentsQuery.isError
              ? getApiErrorMessage(documentsQuery.error)
              : null
          }
        />
        <UsageMetricCard
          title="Total tokens"
          value={formatInteger(totalTokens)}
          caption="Input and output token total."
          loading={usageQuery.isLoading}
          error={
            usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
          }
        />
        <UsageMetricCard
          title="Estimated cost"
          value={formatUsd(usage?.totals.cost_usd)}
          caption="Estimated USD based on usage events."
          loading={usageQuery.isLoading}
          error={
            usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
          }
        />
        <UsageMetricCard
          title="Average latency"
          value={formatLatencyMs(usage?.totals.avg_latency_ms)}
          caption="Average response latency for tracked requests."
          loading={usageQuery.isLoading}
          error={
            usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
          }
        />
        <UsageMetricCard
          title="Average confidence"
          value={formatPercentage(usage?.totals.avg_confidence)}
          caption="Average confidence score from tracked responses."
          loading={usageQuery.isLoading}
          error={
            usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
          }
        />
      </div>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">Trends by date</h2>
            <p className="mt-1 text-sm text-[#68647b]">
              Range: <span className="font-semibold">{usageRange.from}</span> to{" "}
              <span className="font-semibold">{usageRange.to}</span>
            </p>
          </div>
        </div>
        {usageQuery.isLoading ? (
          <LoadingState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title="Loading usage trends..."
          />
        ) : null}
        {usageQuery.isError ? (
          <div className="mt-3">
            <ErrorState
              compact
              error={usageQuery.error}
              description={getApiErrorMessage(usageQuery.error)}
              onRetry={() => {
                void usageQuery.refetch();
              }}
            />
          </div>
        ) : null}
        {usageQuery.isSuccess && usage?.series.length === 0 ? (
          <EmptyState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
            title="No usage events were recorded in this range."
          />
        ) : null}
        {usageQuery.isSuccess && usage && usage.series.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
              <thead>
                <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  <th className="px-3 py-2">Period</th>
                  <th className="px-3 py-2">Questions</th>
                  <th className="px-3 py-2">Tokens in</th>
                  <th className="px-3 py-2">Tokens out</th>
                  <th className="px-3 py-2">Cost</th>
                  <th className="px-3 py-2">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f0edf8]">
                {usage.series.map((point) => (
                  <tr key={`${point.period_start}:${point.period_end}`}>
                    <td className="px-3 py-2 font-medium text-[#2f2a46]">
                      {formatPeriodLabel(point.period_start, point.period_end)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(point.event_count)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(point.input_tokens)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(point.output_tokens)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatUsd(point.cost_usd)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatLatencyMs(point.avg_latency_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <PlannedFeatureCard
          title="Model usage trend"
          description="Model-level usage breakdown is not available from this backend response yet."
        />
        <PlannedFeatureCard
          title="Provider usage trend"
          description="Provider-level usage breakdown is not available from this backend response yet."
        />
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Export</h2>
        {exportUrl ? (
          <Link
            href={exportUrl}
            target={exportIsExternal ? "_blank" : undefined}
            rel={exportIsExternal ? "noreferrer noopener" : undefined}
            className="mt-3 inline-flex rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            Export CSV
          </Link>
        ) : (
          <div className="mt-3 rounded-lg border border-dashed border-[#d7d4e8] bg-[#fcfbff] px-3 py-3">
            <button
              type="button"
              disabled
              title="CSV export endpoint is not configured yet."
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#8a86a1]"
            >
              Export CSV (planned)
            </button>
            <p className="mt-2 text-sm text-[#68647b]">
              Set <code>NEXT_PUBLIC_ADMIN_USAGE_EXPORT_URL</code> to enable CSV
              export.
            </p>
          </div>
        )}
      </section>
    </section>
  );
}
