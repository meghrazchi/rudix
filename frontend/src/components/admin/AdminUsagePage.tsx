"use client";

import { useMemo, useState, type FormEvent } from "react";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

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

const FEATURE_AREA_OPTIONS: FeatureArea[] = [
  "all",
  "chat",
  "agent",
  "evaluation",
  "pipeline",
  "api",
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
  return start === end ? start : `${start} – ${end}`;
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
  const t = useTranslations("adminUsage");
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <p className="text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
          {title}
        </p>
        {estimate ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
            {t("estimate")}
          </span>
        ) : null}
      </div>
      {loading ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">{t("loading")}</p>
      ) : null}
      {!loading && error ? (
        <p className="text-sm font-semibold text-rose-700">{t("unable")}</p>
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
  const t = useTranslations("adminUsage");
  if (loading) {
    return (
      <LoadingState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
        title={t("loadingUsers")}
      />
    );
  }
  if (users.length === 0) {
    return (
      <EmptyState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
        title={t("noUsers")}
      />
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
        <thead>
          <tr className="text-start text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            <th className="px-3 py-2">{t("userId")}</th>
            <th className="px-3 py-2">{t("questions")}</th>
            <th className="px-3 py-2">{t("tokensIn")}</th>
            <th className="px-3 py-2">{t("tokensOut")}</th>
            <th className="px-3 py-2">{t("cost")}</th>
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
  const t = useTranslations("adminUsage");
  if (loading) {
    return (
      <LoadingState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
        title={t("loadingModels")}
      />
    );
  }
  if (models.length === 0) {
    return (
      <EmptyState
        compact
        className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
        title={t("noModels")}
      />
    );
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
        <thead>
          <tr className="text-start text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            <th className="px-3 py-2">{t("model")}</th>
            <th className="px-3 py-2">{t("events")}</th>
            <th className="px-3 py-2">{t("tokensIn")}</th>
            <th className="px-3 py-2">{t("tokensOut")}</th>
            <th className="px-3 py-2">{t("cost")}</th>
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
  const t = useTranslations("adminUsage");
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
      setExportError(t("exportFailed"));
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold text-[#2a2640]">{t("export")}</h2>
      <p className="mt-1 text-sm text-[#68647b]">
        {t("exportDesc")}{" "}
        <span className="font-semibold text-amber-700">{t("estimates")}</span>
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
          {exporting ? t("exporting") : `${t("export")} CSV`}
        </button>
        <button
          type="button"
          onClick={() => handleExport("json")}
          disabled={exporting || dashboardQuery.isLoading}
          className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff] disabled:opacity-60"
        >
          {exporting ? t("exporting") : `${t("export")} JSON`}
        </button>
      </div>
    </section>
  );
}

export function AdminUsagePage() {
  const t = useTranslations("adminUsage");
  const metricTitles = Object.values(
    t.raw("metricTitles") as Record<string, string>,
  );
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
          title={t("restricted")}
          description={t("restrictedDesc")}
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("unavailable")}
          description={t("unavailableDesc")}
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
              {t("admin")}
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              {t("title")}
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">{t("intro")}</p>
          </div>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {t("dateRange")}
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
            {t("userId")}
            <input
              value={userIdInput}
              onChange={(e) => setUserIdInput(e.target.value)}
              placeholder={t("uuid")}
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {t("model")}
            <input
              value={modelInput}
              onChange={(e) => setModelInput(e.target.value)}
              placeholder={t("modelExample")}
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            {t("feature")}
            <select
              value={featureAreaInput}
              onChange={(e) =>
                setFeatureAreaInput(e.target.value as FeatureArea)
              }
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            >
              {FEATURE_AREA_OPTIONS.map((opt, index) => (
                <option key={opt} value={opt}>
                  {
                    [
                      t("allAreas"),
                      t("chat"),
                      t("agents"),
                      t("evaluations"),
                      t("pipeline"),
                      t("api"),
                    ][index]
                  }
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="h-9 self-end rounded-lg bg-[#3525cd] px-3 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            {t("apply")}
          </button>
          <button
            type="button"
            onClick={clearFilters}
            className="h-9 self-end rounded-lg border border-[#d2cee6] px-3 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
          >
            {t("reset")}
          </button>
        </form>
      </section>

      {/* Summary metric cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <UsageMetricCard
          title={metricTitles[0] ?? t("questions")}
          value={formatInteger(dash?.totals.questions_asked)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[1] ?? t("activeUsers")}
          value={formatInteger(dash?.totals.active_users)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[2] ?? t("tokensIn")}
          value={formatInteger(
            dash != null
              ? dash.totals.input_tokens + dash.totals.output_tokens
              : null,
          )}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[3] ?? t("cost")}
          value={formatUsd(dash?.totals.estimated_cost_usd)}
          caption={t("estimates")}
          loading={loading}
          error={queryError}
          estimate
        />
        <UsageMetricCard
          title={metricTitles[4] ?? ""}
          value={formatInteger(dash?.totals.documents)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[5] ?? ""}
          value={formatInteger(dash?.totals.indexed_documents)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[6] ?? t("agentRuns")}
          value={formatInteger(dash?.totals.agent_runs)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[7] ?? t("evalRuns")}
          value={formatInteger(dash?.totals.evaluation_runs)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[8] ?? ""}
          value={formatInteger(dash?.totals.indexing_jobs)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[9] ?? ""}
          value={formatInteger(dash?.totals.failed_indexing_jobs)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[10] ?? t("latency")}
          value={formatLatencyMs(dash?.totals.avg_latency_ms)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
        <UsageMetricCard
          title={metricTitles[11] ?? ""}
          value={formatPercentage(dash?.totals.avg_confidence)}
          caption={t("intro")}
          loading={loading}
          error={queryError}
        />
      </div>

      {/* Trend series table */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-[#2a2640]">{t("trends")}</h2>
            <p className="mt-1 text-sm text-[#68647b]">
              {t("range")}:{" "}
              <span className="font-semibold" dir="ltr">
                {usageRange.from}
              </span>{" "}
              – <span className="font-semibold">{usageRange.to}</span>
            </p>
          </div>
        </div>
        {loading ? (
          <LoadingState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title={t("loadingTrends")}
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
            title={t("noEvents")}
          />
        ) : null}
        {dashboardQuery.isSuccess && dash && dash.series.length > 0 ? (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
              <thead>
                <tr className="text-start text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                  {[
                    t("period"),
                    t("questions"),
                    t("activeUsers"),
                    t("tokensIn"),
                    t("tokensOut"),
                    t("cost"),
                    t("agentRuns"),
                    t("evalRuns"),
                    t("latency"),
                  ].map((label) => (
                    <th className="px-3 py-2" key={label}>
                      {label}
                    </th>
                  ))}
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
            {t("featureBreakdown")}
          </h2>
          <p className="mt-1 text-sm text-[#68647b]">
            {t("featureBreakdownDesc")}
          </p>
          <FeatureAreaBreakdown
            breakdown={dash.feature_area_breakdown}
            loading={loading}
          />
        </section>
      ) : null}

      {/* Top users */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">{t("topUsers")}</h2>
        <p className="mt-1 text-sm text-[#68647b]">{t("sorted")}</p>
        <TopUsersTable users={dash?.top_users ?? []} loading={loading} />
      </section>

      {/* Top models */}
      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">{t("topModels")}</h2>
        <p className="mt-1 text-sm text-[#68647b]">{t("sorted")}</p>
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
