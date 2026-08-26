"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import {
  exportUsageAdoption,
  getUsageAdoptionCharts,
  getUsageAdoptionSummary,
  listUsageAdoptionUsers,
  sendOnboardingReminder,
} from "@/lib/api/usage-adoption";
import type {
  OnboardingStatus,
  UsageAdoptionQuery,
  UsageAdoptionUserRow,
} from "@/lib/schemas/usage-adoption";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

const PAGE_SIZE = 25;

const ROLE_OPTIONS = [
  "",
  "owner",
  "admin",
  "member",
  "viewer",
  "reviewer",
  "security_admin",
  "billing_admin",
  "developer",
] as const;

function toneClass(tone: "good" | "warn" | "bad" | "neutral"): string {
  switch (tone) {
    case "good":
      return "bg-emerald-100 text-emerald-800";
    case "warn":
      return "bg-amber-100 text-amber-800";
    case "bad":
      return "bg-rose-100 text-rose-800";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function onboardingTone(status: OnboardingStatus): "good" | "warn" | "bad" {
  if (status === "completed") return "good";
  if (status === "in_progress") return "warn";
  return "bad";
}

function Badge({
  label,
  tone,
}: {
  label: string;
  tone: "good" | "warn" | "bad" | "neutral";
}) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${toneClass(tone)}`}
    >
      {label}
    </span>
  );
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-white p-3 shadow-sm">
      <p className="text-[11px] font-semibold tracking-wide text-[#6d6985] uppercase">
        {label}
      </p>
      <p className="mt-1 text-2xl font-extrabold text-[#2a2640]">{value}</p>
    </div>
  );
}

function ChartCard({
  title,
  data,
  formatValue,
}: {
  title: string;
  data: Array<{ label: string; value: number }>;
  formatValue?: (value: number) => string;
}) {
  const t = useTranslations("adminUsageAdoption");
  const hasData = data.some((item) => item.value > 0);
  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-bold text-[#2a2640]">{title}</h3>
      {!hasData ? (
        <p className="py-8 text-center text-xs text-[#8d8aa3]">
          {t("charts.empty")}
        </p>
      ) : (
        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ left: 4, right: 16 }}
            >
              <CartesianGrid horizontal={false} stroke="#ece9f7" />
              <XAxis type="number" hide domain={[0, "dataMax"]} />
              <YAxis
                type="category"
                dataKey="label"
                width={120}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#5f5b72", fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{ borderRadius: 8, borderColor: "#dfdced" }}
                formatter={(value) =>
                  formatValue ? formatValue(Number(value)) : value
                }
              />
              <Bar
                dataKey="value"
                radius={[0, 6, 6, 0]}
                barSize={12}
                fill="#3525cd"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function UserRow({
  row,
  onFilterByRole,
}: {
  row: UsageAdoptionUserRow;
  onFilterByRole: (role: string) => void;
}) {
  const t = useTranslations("adminUsageAdoption");
  const [reminderSent, setReminderSent] = useState(false);

  const reminderMutation = useMutation({
    mutationFn: () => sendOnboardingReminder(row.user_id),
    onSuccess: () => setReminderSent(true),
  });

  return (
    <tr className="border-b border-[#e4e1f2] align-top hover:bg-[#faf9ff]">
      <td className="px-3 py-2">
        <p className="text-sm font-semibold text-[#2f2a46]">{row.name}</p>
        <p className="text-xs text-[#8d8aa3]">{row.email}</p>
        {reminderMutation.isError ? (
          <p className="mt-1 text-xs text-rose-700">
            {getApiErrorMessage(reminderMutation.error)}
          </p>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          onClick={() => onFilterByRole(row.role)}
          className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
        >
          {row.role}
        </button>
      </td>
      <td className="px-3 py-2 text-xs text-[#6d6985]">
        {formatDateTime(row.last_active_at)}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.questions_asked}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">{row.sources_used}</td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.citation_clicks}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.feedback_submitted}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">{row.saved_answers}</td>
      <td className="px-3 py-2">
        <Badge
          label={t(`onboardingStatus.${row.onboarding_status}`)}
          tone={onboardingTone(row.onboarding_status)}
        />
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1.5">
          {row.onboarding_status !== "completed" ? (
            <button
              type="button"
              onClick={() => reminderMutation.mutate()}
              disabled={reminderMutation.isPending || reminderSent}
              className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {reminderSent
                ? t("actions.reminderSent")
                : reminderMutation.isPending
                  ? t("actions.sendingReminder")
                  : t("actions.sendReminder")}
            </button>
          ) : null}
          <Link
            href="/admin/audit-logs"
            className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            {t("actions.viewActivity")}
          </Link>
          <button
            type="button"
            onClick={() => onFilterByRole(row.role)}
            className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            {t("actions.viewTeamUsage")}
          </button>
        </div>
      </td>
    </tr>
  );
}

export function AdminUsageAdoptionPage() {
  const t = useTranslations("adminUsageAdoption");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState<string | null>(null);

  const query: UsageAdoptionQuery = {
    ...(fromDate ? { from: fromDate } : {}),
    ...(toDate ? { to: toDate } : {}),
    ...(roleFilter ? { role: roleFilter } : {}),
  };
  const usersQuery_: UsageAdoptionQuery = {
    ...query,
    page,
    page_size: PAGE_SIZE,
  };

  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.usageAdoptionSummary(
      query as Record<string, unknown>,
    ),
    queryFn: () => getUsageAdoptionSummary(query),
    enabled: isAdminUser,
  });
  const chartsQuery = useQuery({
    queryKey: queryKeys.admin.usageAdoptionCharts(
      query as Record<string, unknown>,
    ),
    queryFn: () => getUsageAdoptionCharts(query),
    enabled: isAdminUser,
  });
  const usersQuery = useQuery({
    queryKey: queryKeys.admin.usageAdoptionUsers(
      usersQuery_ as Record<string, unknown>,
    ),
    queryFn: () => listUsageAdoptionUsers(usersQuery_),
    enabled: isAdminUser,
  });

  function resetPage() {
    setPage(1);
  }

  function filterByRole(nextRole: string) {
    setRoleFilter(nextRole);
    resetPage();
  }

  function invalidateAll() {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "usage-adoption"],
    });
  }

  async function handleExport() {
    try {
      setExportError(null);
      const blob = await exportUsageAdoption(query);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "usage-adoption.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(getApiErrorMessage(err));
    }
  }

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  const summary = summaryQuery.data;
  const charts = chartsQuery.data;
  const rows = usersQuery.data?.rows ?? [];
  const total = usersQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              {t("header.eyebrow")}
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              {t("header.title")}
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              {t("header.description")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/admin/team"
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.inviteUser")}
            </Link>
            <button
              type="button"
              onClick={() => void handleExport()}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.export")}
            </button>
            <button
              type="button"
              onClick={() => {
                invalidateAll();
                void usersQuery.refetch();
                void summaryQuery.refetch();
                void chartsQuery.refetch();
              }}
              disabled={usersQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {usersQuery.isFetching
                ? t("actions.refreshing")
                : t("actions.refresh")}
            </button>
          </div>
        </div>
        {exportError ? (
          <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {exportError}
          </p>
        ) : null}
      </header>

      {summaryQuery.isLoading ? (
        <LoadingState compact title={t("states.loadingSummary")} />
      ) : summary ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7">
          <MetricCard
            label={t("metrics.activeUsers")}
            value={summary.active_users}
          />
          <MetricCard label={t("metrics.newUsers")} value={summary.new_users} />
          <MetricCard
            label={t("metrics.returningUsers")}
            value={summary.returning_users}
          />
          <MetricCard
            label={t("metrics.questionsAsked")}
            value={summary.questions_asked}
          />
          <MetricCard
            label={t("metrics.documentsUploaded")}
            value={summary.documents_uploaded}
          />
          <MetricCard
            label={t("metrics.collectionsUsed")}
            value={summary.collections_used}
          />
          <MetricCard
            label={t("metrics.connectorsUsed")}
            value={summary.connectors_used}
          />
          <MetricCard
            label={t("metrics.citationClicks")}
            value={summary.citation_clicks}
          />
          <MetricCard
            label={t("metrics.trustPanelOpens")}
            value={summary.trust_panel_opens}
          />
          <MetricCard
            label={t("metrics.feedbackSubmitted")}
            value={summary.feedback_submitted}
          />
          <MetricCard
            label={t("metrics.savedAnswers")}
            value={summary.saved_answers}
          />
          <MetricCard
            label={t("metrics.onboardingCompletionRate")}
            value={formatPercent(summary.onboarding_completion_rate)}
          />
          <MetricCard
            label={t("metrics.invitationsSent")}
            value={summary.invitations_sent}
          />
          <MetricCard
            label={t("metrics.invitationsAccepted")}
            value={summary.invitations_accepted}
          />
        </div>
      ) : null}

      {chartsQuery.isLoading ? (
        <LoadingState compact title={t("states.loadingCharts")} />
      ) : charts ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <ChartCard
            title={t("charts.activationFunnel")}
            data={charts.funnel.map((step) => ({
              label: step.label,
              value: step.users_reached,
            }))}
          />
          <ChartCard
            title={t("charts.dropOffPoints")}
            data={charts.drop_off_points.map((step) => ({
              label: step.label,
              value: Math.round((step.drop_off_rate ?? 0) * 100),
            }))}
            formatValue={(value) => `${value}%`}
          />
          <ChartCard
            title={t("charts.activeUsersTrend")}
            data={charts.active_users_series.map((point) => ({
              label: point.date.slice(5),
              value: point.active_users,
            }))}
          />
          <ChartCard
            title={t("charts.questionsPerUser")}
            data={charts.questions_per_user.map((bucket) => ({
              label: bucket.bucket,
              value: bucket.user_count,
            }))}
          />
          <ChartCard
            title={t("charts.featureUsage")}
            data={Object.entries(charts.feature_usage).map(([area, count]) => ({
              label: area,
              value: count,
            }))}
          />
          <ChartCard
            title={t("charts.roleAdoption")}
            data={charts.role_adoption_comparison.map((row) => ({
              label: row.role,
              value: row.active_users,
            }))}
          />
        </div>
      ) : null}

      <div className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e1f2] px-5 py-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.from")}
            <input
              type="date"
              value={fromDate}
              onChange={(e) => {
                setFromDate(e.target.value);
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.to")}
            <input
              type="date"
              value={toDate}
              onChange={(e) => {
                setToDate(e.target.value);
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.role")}
            <select
              value={roleFilter}
              onChange={(e) => filterByRole(e.target.value)}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {ROLE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
        </div>

        {usersQuery.isLoading ? (
          <LoadingState
            compact
            title={t("states.loadingUsers")}
            className="px-5 py-8"
          />
        ) : usersQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={usersQuery.error}
              description={getApiErrorMessage(usersQuery.error)}
              onRetry={() => void usersQuery.refetch()}
            />
          </div>
        ) : rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-[#6d6985]">
            {t("states.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-start text-sm">
              <thead className="border-b border-[#e4e1f2] bg-[#faf9ff] text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                <tr>
                  <th className="px-3 py-2">{t("table.user")}</th>
                  <th className="px-3 py-2">{t("table.role")}</th>
                  <th className="px-3 py-2">{t("table.lastActive")}</th>
                  <th className="px-3 py-2">{t("table.questionsAsked")}</th>
                  <th className="px-3 py-2">{t("table.sourcesUsed")}</th>
                  <th className="px-3 py-2">{t("table.citationClicks")}</th>
                  <th className="px-3 py-2">{t("table.feedback")}</th>
                  <th className="px-3 py-2">{t("table.savedAnswers")}</th>
                  <th className="px-3 py-2">{t("table.onboarding")}</th>
                  <th className="px-3 py-2">{t("table.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <UserRow
                    key={row.user_id}
                    row={row}
                    onFilterByRole={filterByRole}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > PAGE_SIZE ? (
          <div className="flex items-center justify-between border-t border-[#e4e1f2] px-5 py-3">
            <p className="text-xs text-[#6d6985]">
              {t("pagination.summary", { total, page, totalPages })}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("actions.previous")}
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("actions.next")}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
