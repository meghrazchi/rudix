"use client";

import { useMemo, useState, type FormEvent } from "react";

import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  exportUsageDashboard,
  getUsageDashboard,
  type FeatureArea,
  type TopModelUsage,
  type TopUserUsage,
  type UsageDashboardResponse,
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
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

const FEATURE_AREA_OPTIONS: Array<{ value: FeatureArea; label: string }> = [
  { value: "all", label: "All areas" },
  { value: "chat", label: "Chat / Q&A" },
  { value: "agent", label: "Agents" },
  { value: "evaluation", label: "Evaluations" },
  { value: "pipeline", label: "Indexing pipeline" },
  { value: "api", label: "API calls" },
];

type AppliedFilters = {
  userId: string | null;
  model: string | null;
  featureArea: FeatureArea;
};

function trimToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function formatPeriodLabel(start: string, end: string): string {
  return start === end ? start : `${start} to ${end}`;
}

function UsageMetricCard({
  title,
  value,
  caption,
  loading,
  error,
  estimate,
}: {
  title: string;
  value: string;
  caption: string;
  loading: boolean;
  error: string | null;
  estimate?: boolean;
}) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <p className="text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
          {title}
        </p>
        {estimate ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
            estimate
          </span>
        ) : null}
      </div>
      {loading ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">Loading...</p>
      ) : null}
      {!loading && error ? (
        <p className="text-sm font-semibold text-rose-700">Unable to load</p>
      ) : null}
      {!loading && !error ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p>
      ) : null}
      <p className="mt-2 text-xs text-[#6a6780]">{caption}</p>
    </article>
  );
}

function TopUsersTable({
  users,
  loading,
}: {
  users: TopUserUsage[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <LoadingState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
        title="Loading top users..."
      />
    );
  }
  if (users.length === 0) {
    return (
      <EmptyState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
        title="No user data in selected range."
      />
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
        <thead>
          <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            <th className="px-3 py-2">User ID</th>
            <th className="px-3 py-2">Questions</th>
            <th className="px-3 py-2">Tokens in</th>
            <th className="px-3 py-2">Tokens out</th>
            <th className="px-3 py-2">Est. cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#f0edf8]">
          {users.map((u) => (
            <tr key={u.user_id}>
              <td className="px-3 py-2 font-mono text-xs text-[#2f2a46]">
                {u.user_id}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(u.questions)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(u.input_tokens)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(u.output_tokens)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatUsd(u.estimated_cost_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TopModelsTable({
  models,
  loading,
}: {
  models: TopModelUsage[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <LoadingState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
        title="Loading top models..."
      />
    );
  }
  if (models.length === 0) {
    return (
      <EmptyState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
        title="No model data in selected range."
      />
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
        <thead>
          <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            <th className="px-3 py-2">Model</th>
            <th className="px-3 py-2">Events</th>
            <th className="px-3 py-2">Tokens in</th>
            <th className="px-3 py-2">Tokens out</th>
            <th className="px-3 py-2">Est. cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#f0edf8]">
          {models.map((m) => (
            <tr key={m.model_name}>
              <td className="px-3 py-2 font-medium text-[#2f2a46]">
                {m.model_name}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(m.event_count)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(m.input_tokens)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatInteger(m.output_tokens)}
              </td>
              <td className="px-3 py-2 text-[#4d4963]">
                {formatUsd(m.estimated_cost_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FeatureAreaBreakdown({
  breakdown,
  loading,
}: {
  breakdown: Record<string, number> | undefined;
  loading: boolean;
}) {
  if (loading || !breakdown) return null;
  const entries = Object.entries(breakdown).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      {entries.map(([area, count]) => (
        <span
          key={area}
          className="rounded-full border border-[#d2cee6] bg-[#f5f3ff] px-3 py-1 text-xs font-semibold text-[#3f3b58]"
        >
          {area}: {formatInteger(count)}
        </span>
      ))}
    </div>
  );
}

function ExportSection({
  dashboardQuery,
  appliedFilters,
  usageRange,
}: {
  dashboardQuery: ReturnType<typeof useQuery<UsageDashboardResponse>>;
  appliedFilters: AppliedFilters;
  usageRange: { from: string; to: string };
}) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleExport(format: "csv" | "json") {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportUsageDashboard(format, {
        from: usageRange.from,
        to: usageRange.to,
        user_id: appliedFilters.userId ?? undefined,
        model: appliedFilters.model ?? undefined,
        feature_area:
          appliedFilters.featureArea !== "all"
            ? appliedFilters.featureArea
            : undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage-${usageRange.from}-${usageRange.to}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Export failed. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">Export</h2>
      <p className="mt-1 text-sm text-[#68647b]">
        Download usage events for billing or ops review.{" "}
        <span className="font-semibold text-amber-700">
          Costs are estimates only.
        </span>
      </p>
      {exportError ? (
        <p className="mt-2 text-sm text-rose-700">{exportError}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => handleExport("csv")}
          disabled={exporting || dashboardQuery.isLoading}
          className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60"
        >
          {exporting ? "Exporting..." : "Export CSV"}
        </button>
        <button
          type="button"
          onClick={() => handleExport("json")}
          disabled={exporting || dashboardQuery.isLoading}
          className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
        >
          {exporting ? "Exporting..." : "Export JSON"}
        </button>
      </div>
    </section>
  );
}

export function AdminUsagePage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [userIdInput, setUserIdInput] = useState("");
  const [modelInput, setModelInput] = useState("");
  const [featureAreaInput, setFeatureAreaInput] = useState<FeatureArea>("all");
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({
    userId: null,
    model: null,
    featureArea: "all",
  });

  const usageRange = useMemo(
    () => resolveUsageDateRange(rangePreset),
    [rangePreset],
  );

  const dashboardQuery = useQuery({
    queryKey: queryKeys.admin.dashboard({
      from: usageRange.from,
      to: usageRange.to,
      granularity: "day",
      user_id: appliedFilters.userId,
      model: appliedFilters.model,
      feature_area: appliedFilters.featureArea,
    }),
    queryFn: () =>
      getUsageDashboard({
        from: usageRange.from,
        to: usageRange.to,
        granularity: "day",
        user_id: appliedFilters.userId ?? undefined,
        model: appliedFilters.model ?? undefined,
        feature_area:
          appliedFilters.featureArea !== "all"
            ? appliedFilters.featureArea
            : undefined,
      }),
    enabled: isAdminUser,
  });

  const forbiddenError =
    dashboardQuery.isError &&
    isForbiddenError(dashboardQuery.error) &&
    dashboardQuery.error;

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

  const dash = dashboardQuery.data;
  const loading = dashboardQuery.isLoading;
  const queryError = dashboardQuery.isError
    ? getApiErrorMessage(dashboardQuery.error)
    : null;

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setAppliedFilters({
      userId: trimToNull(userIdInput),
      model: trimToNull(modelInput),
      featureArea: featureAreaInput,
    });
  }

  function clearFilters(): void {
    setUserIdInput("");
    setModelInput("");
    setFeatureAreaInput("all");
    setAppliedFilters({ userId: null, model: null, featureArea: "all" });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {/* Header */}
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Admin
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Usage &amp; cost dashboard
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Review questions, tokens, estimated cost, active users, documents,
              evaluation runs, and agent activity. Cost figures are{" "}
              <span className="font-semibold text-amber-700">estimates</span>{" "}
              based on recorded usage events and are not billing invoices.
            </p>
          </div>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Date range
            <select
              value={rangePreset}
              onChange={(e) =>
                setRangePreset(e.target.value as DashboardRangePreset)
              }
              className="h-9 min-w-[150px] rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            >
              {DASHBOARD_RANGE_PRESETS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {/* Filters */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <form
          className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto_auto]"
          onSubmit={applyFilters}
        >
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            User ID
            <input
              value={userIdInput}
              onChange={(e) => setUserIdInput(e.target.value)}
              placeholder="UUID (optional)"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Model
            <input
              value={modelInput}
              onChange={(e) => setModelInput(e.target.value)}
              placeholder="e.g. gpt-4o"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Feature area
            <select
              value={featureAreaInput}
              onChange={(e) =>
                setFeatureAreaInput(e.target.value as FeatureArea)
              }
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            >
              {FEATURE_AREA_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
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

      {/* Summary metric cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <UsageMetricCard
          title="Total questions"
          value={formatInteger(dash?.totals.questions_asked)}
          caption="Chat/Q&A events in selected range."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Active users"
          value={formatInteger(dash?.totals.active_users)}
          caption="Distinct users with recorded activity."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Total tokens"
          value={formatInteger(
            dash != null
              ? dash.totals.input_tokens + dash.totals.output_tokens
              : null,
          )}
          caption="Combined input and output tokens."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Estimated cost"
          value={formatUsd(dash?.totals.estimated_cost_usd)}
          caption="Approximate USD based on usage events."
          loading={loading}
          error={queryError}
          estimate
        />
        <UsageMetricCard
          title="Documents"
          value={formatInteger(dash?.totals.documents)}
          caption="Non-deleted documents in org."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Indexed documents"
          value={formatInteger(dash?.totals.indexed_documents)}
          caption="Successfully indexed documents."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Agent runs"
          value={formatInteger(dash?.totals.agent_runs)}
          caption="agent.runtime events in range."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Evaluation runs"
          value={formatInteger(dash?.totals.evaluation_runs)}
          caption="Evaluation events in selected range."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Indexing jobs"
          value={formatInteger(dash?.totals.indexing_jobs)}
          caption="Pipeline indexing events in range."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Failed indexing"
          value={formatInteger(dash?.totals.failed_indexing_jobs)}
          caption="Pipeline jobs that reported failure."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Average latency"
          value={formatLatencyMs(dash?.totals.avg_latency_ms)}
          caption="Average response latency from tracked events."
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title="Average confidence"
          value={formatPercentage(dash?.totals.avg_confidence)}
          caption="Average answer confidence from tracked events."
          loading={loading}
          error={queryError}
        />
      </div>

      {/* Trend series table */}
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
        {loading ? (
          <LoadingState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title="Loading usage trends..."
          />
        ) : null}
        {dashboardQuery.isError ? (
          <div className="mt-3">
            <ErrorState
              compact
              error={dashboardQuery.error}
              description={getApiErrorMessage(dashboardQuery.error)}
              onRetry={() => {
                void dashboardQuery.refetch();
              }}
            />
          </div>
        ) : null}
        {dashboardQuery.isSuccess && dash?.series.length === 0 ? (
          <EmptyState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
            title="No usage events were recorded in this range."
          />
        ) : null}
        {dashboardQuery.isSuccess && dash && dash.series.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
              <thead>
                <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  <th className="px-3 py-2">Period</th>
                  <th className="px-3 py-2">Questions</th>
                  <th className="px-3 py-2">Active users</th>
                  <th className="px-3 py-2">Tokens in</th>
                  <th className="px-3 py-2">Tokens out</th>
                  <th className="px-3 py-2">Est. cost</th>
                  <th className="px-3 py-2">Agent runs</th>
                  <th className="px-3 py-2">Eval runs</th>
                  <th className="px-3 py-2">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f0edf8]">
                {dash.series.map((pt) => (
                  <tr key={`${pt.period_start}:${pt.period_end}`}>
                    <td className="px-3 py-2 font-medium text-[#2f2a46]">
                      {formatPeriodLabel(pt.period_start, pt.period_end)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.questions_asked)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.active_users)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.input_tokens)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.output_tokens)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatUsd(pt.estimated_cost_usd)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.agent_runs)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatInteger(pt.evaluation_runs)}
                    </td>
                    <td className="px-3 py-2 text-[#4d4963]">
                      {formatLatencyMs(pt.avg_latency_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {/* Feature area breakdown */}
      {dash?.feature_area_breakdown &&
      Object.keys(dash.feature_area_breakdown).length > 0 ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">
            Feature area breakdown
          </h2>
          <p className="mt-1 text-sm text-[#68647b]">
            Event counts by feature area in selected range.
          </p>
          <FeatureAreaBreakdown
            breakdown={dash.feature_area_breakdown}
            loading={loading}
          />
        </section>
      ) : null}

      {/* Top users */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">
          Top users by estimated cost
        </h2>
        <p className="mt-1 text-sm text-[#68647b]">
          Sorted by estimated cost descending. Cost figures are estimates.
        </p>
        <TopUsersTable users={dash?.top_users ?? []} loading={loading} />
      </section>

      {/* Top models */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">
          Top models by estimated cost
        </h2>
        <p className="mt-1 text-sm text-[#68647b]">
          Sorted by estimated cost descending. Cost figures are estimates.
        </p>
        <TopModelsTable models={dash?.top_models ?? []} loading={loading} />
      </section>

      {/* Export */}
      <ExportSection
        dashboardQuery={dashboardQuery}
        appliedFilters={appliedFilters}
        usageRange={usageRange}
      />
    </section>
  );
}
