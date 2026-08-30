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
import { updateConflictStatus } from "@/lib/api/conflicts";
import { revokeResourceGrant } from "@/lib/api/permissions";
import {
  exportPermissionsAccessReport,
  getPermissionsAccessCharts,
  getPermissionsAccessSummary,
  listPermissionsAccessRows,
} from "@/lib/api/permissions-access";
import type {
  BroadAccessUserRow,
  PermissionsAccessQuery,
  PermissionsAccessRow,
} from "@/lib/schemas/permissions-access";
import { usePermissions } from "@/lib/use-permissions";

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

const ACCESS_SOURCE_OPTIONS = [
  "",
  "explicit_grant",
  "explicit_deny",
  "connector_acl",
  "conflict",
] as const;

const CONFLICT_STATUS_OPTIONS = [
  "",
  "open",
  "investigating",
  "resolved",
  "dismissed",
] as const;

function MetricCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number | string;
  tone?: "neutral" | "warn";
}) {
  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-white p-3 shadow-sm">
      <p className="text-[11px] font-semibold tracking-wide text-[#6d6985] uppercase">
        {label}
      </p>
      <p
        className={`mt-1 text-2xl font-extrabold ${
          tone === "warn" && Number(value) > 0
            ? "text-amber-600"
            : "text-[#2a2640]"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ChartCard({
  title,
  data,
  emptyLabel,
  formatValue,
}: {
  title: string;
  data: Array<{ label: string; value: number }>;
  emptyLabel: string;
  formatValue?: (value: number) => string;
}) {
  const hasData = data.some((item) => item.value > 0);
  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-bold text-[#2a2640]">{title}</h3>
      {!hasData ? (
        <p className="py-8 text-center text-xs text-[#8d8aa3]">{emptyLabel}</p>
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
                width={140}
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

function BroadAccessUsersCard({ users }: { users: BroadAccessUserRow[] }) {
  const t = useTranslations("adminPermissionsAccess");
  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-bold text-[#2a2640]">
        {t("charts.broadAccessUsers")}
      </h3>
      {users.length === 0 ? (
        <p className="py-8 text-center text-xs text-[#8d8aa3]">
          {t("charts.empty")}
        </p>
      ) : (
        <ul className="max-h-52 space-y-2 overflow-y-auto">
          {users.map((u) => (
            <li
              key={u.user_id}
              className="rounded-lg border border-[#ede9fb] px-3 py-2"
            >
              <p className="text-xs font-semibold text-[#2a2640]">
                {u.name}{" "}
                <span className="font-normal text-[#8d8aa3]">{u.email}</span>
              </p>
              <p className="mt-0.5 text-[11px] text-[#6d6985]">{u.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// The debugger only accepts PolicyEngine's Action enum values. Row access
// levels can also be "read_only" (the coarser vocabulary used by resource
// grants/denies/ACL mappings), "denied", or "conflict" (a synthesized row) —
// none of which are valid actions, so fall back to "view" for those.
const DEBUGGER_ACTIONS = new Set([
  "list",
  "view",
  "search",
  "chat",
  "cite",
  "create",
  "manage",
  "sync",
  "export",
  "evaluate",
  "delete",
]);

function accessDebuggerHref(row: PermissionsAccessRow): string | null {
  if (!row.user_id) return null;
  const action = DEBUGGER_ACTIONS.has(row.access_level)
    ? row.access_level
    : "view";
  const qs = new URLSearchParams({
    user: row.user_id,
    resource_type: row.resource_type,
    action,
  });
  if (row.resource_id) qs.set("resource", row.resource_id);
  return `/admin/access-debugger?${qs.toString()}`;
}

function AccessRow({ row }: { row: PermissionsAccessRow }) {
  const t = useTranslations("adminPermissionsAccess");
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const removeGrantMutation = useMutation({
    mutationFn: () => revokeResourceGrant(row.grant_id!),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "permissions-access"],
      });
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  const fixConflictMutation = useMutation({
    mutationFn: () =>
      updateConflictStatus(row.conflict_id!, { status: "investigating" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "permissions-access"],
      });
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  const debuggerHref = accessDebuggerHref(row);

  return (
    <tr className="border-b border-[#e4e1f2] align-top hover:bg-[#faf9ff]">
      <td className="px-3 py-2">
        <p className="text-sm font-semibold text-[#2f2a46]">
          {row.user_name ?? t("table.unknownUser")}
        </p>
        <p className="text-xs text-[#8d8aa3]">{row.user_email ?? "—"}</p>
        {actionError ? (
          <p className="mt-1 text-xs text-rose-700">{actionError}</p>
        ) : null}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">{row.role ?? "—"}</td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">{row.team ?? "—"}</td>
      <td className="px-3 py-2">
        <p className="text-sm text-[#2f2a46]">
          {row.resource_label ?? row.resource_id ?? "—"}
        </p>
        <p className="text-xs text-[#8d8aa3]">{row.resource_type}</p>
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">{row.access_level}</td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {t(`accessSource.${row.access_source}`)}
      </td>
      <td className="px-3 py-2">
        {row.conflict_status ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 uppercase">
            {row.conflict_status}
          </span>
        ) : (
          <span className="text-xs text-[#8d8aa3]">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-[#6d6985]">
        {formatDateTime(row.last_access)}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1.5">
          {debuggerHref ? (
            <Link
              href={debuggerHref}
              className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.openDebugger")}
            </Link>
          ) : null}
          {row.user_id ? (
            <Link
              href="/admin/permissions"
              className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.reviewUser")}
            </Link>
          ) : null}
          {row.resource_id ? (
            <Link
              href="/admin/permissions"
              className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.reviewResource")}
            </Link>
          ) : null}
          {row.grant_id ? (
            <button
              type="button"
              onClick={() => removeGrantMutation.mutate()}
              disabled={removeGrantMutation.isPending}
              className="rounded border border-rose-200 px-2 py-0.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {removeGrantMutation.isPending
                ? t("actions.removing")
                : t("actions.removeBroadAccess")}
            </button>
          ) : null}
          {row.conflict_id ? (
            <button
              type="button"
              onClick={() => fixConflictMutation.mutate()}
              disabled={fixConflictMutation.isPending}
              className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {fixConflictMutation.isPending
                ? t("actions.fixing")
                : t("actions.fixConflict")}
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

export function AdminPermissionsAccessPage() {
  const t = useTranslations("adminPermissionsAccess");
  const { hasPermission } = usePermissions();
  const canView = hasPermission("security_center:view");
  const canExport = hasPermission("security_center:configure");
  const queryClient = useQueryClient();

  const [roleFilter, setRoleFilter] = useState("");
  const [accessSourceFilter, setAccessSourceFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [conflictStatusFilter, setConflictStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState<string | null>(null);

  const rowsFilterQuery: PermissionsAccessQuery = {
    ...(roleFilter ? { role: roleFilter } : {}),
    ...(accessSourceFilter ? { access_source: accessSourceFilter } : {}),
    ...(resourceTypeFilter ? { resource_type: resourceTypeFilter } : {}),
    ...(conflictStatusFilter ? { conflict_status: conflictStatusFilter } : {}),
    ...(search.trim() ? { search: search.trim() } : {}),
  };
  const rowsQuery_: PermissionsAccessQuery = {
    ...rowsFilterQuery,
    page,
    page_size: PAGE_SIZE,
  };

  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.permissionsAccessSummary(),
    queryFn: () => getPermissionsAccessSummary(),
    enabled: canView,
  });
  const chartsQuery = useQuery({
    queryKey: queryKeys.admin.permissionsAccessCharts(),
    queryFn: () => getPermissionsAccessCharts(),
    enabled: canView,
  });
  const rowsQuery = useQuery({
    queryKey: queryKeys.admin.permissionsAccessRows(
      rowsQuery_ as Record<string, unknown>,
    ),
    queryFn: () => listPermissionsAccessRows(rowsQuery_),
    enabled: canView,
  });

  function resetPage() {
    setPage(1);
  }

  function invalidateAll() {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "permissions-access"],
    });
  }

  async function handleExport() {
    try {
      setExportError(null);
      const blob = await exportPermissionsAccessReport(rowsFilterQuery);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "permissions-access-report.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(getApiErrorMessage(err));
    }
  }

  if (!canView) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
          backHref="/admin"
          compact={false}
        />
      </section>
    );
  }

  const summary = summaryQuery.data;
  const charts = chartsQuery.data;
  const rows = rowsQuery.data?.items ?? [];
  const total = rowsQuery.data?.total ?? 0;
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
              href="/admin/permissions"
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.manageConflicts")}
            </Link>
            {canExport ? (
              <button
                type="button"
                onClick={() => void handleExport()}
                className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
              >
                {t("actions.export")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => {
                invalidateAll();
                void rowsQuery.refetch();
                void summaryQuery.refetch();
                void chartsQuery.refetch();
              }}
              disabled={rowsQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {rowsQuery.isFetching
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
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <MetricCard
            label={t("metrics.totalUsers")}
            value={summary.total_users}
          />
          <MetricCard
            label={t("metrics.adminUsers")}
            value={summary.admin_users}
          />
          <MetricCard
            label={t(
              summary.external_users_is_heuristic
                ? "metrics.externalUsersHeuristic"
                : "metrics.externalUsers",
            )}
            value={summary.external_users}
          />
          <MetricCard
            label={t("metrics.broadAccessUsers")}
            value={summary.broad_access_users}
            tone="warn"
          />
          <MetricCard
            label={t("metrics.permissionConflicts")}
            value={summary.permission_conflicts_open}
            tone="warn"
          />
          <MetricCard
            label={t("metrics.orphanedGrants")}
            value={summary.orphaned_grants}
            tone="warn"
          />
          <MetricCard
            label={t("metrics.expiredGrants")}
            value={summary.expired_active_grants}
            tone="warn"
          />
          <MetricCard
            label={t("metrics.connectorAclMismatches")}
            value={summary.connector_acl_mismatches}
            tone="warn"
          />
          <MetricCard
            label={t("metrics.resourcesWithoutOwner")}
            value={summary.resources_without_owner}
          />
          <MetricCard
            label={t("metrics.unauthorizedAttempts")}
            value={summary.unauthorized_access_attempts}
            tone="warn"
          />
        </div>
      ) : null}

      {chartsQuery.isLoading ? (
        <LoadingState compact title={t("states.loadingCharts")} />
      ) : charts ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <ChartCard
            title={t("charts.usersByRole")}
            emptyLabel={t("charts.empty")}
            data={charts.users_by_role.map((r) => ({
              label: r.role,
              value: r.count,
            }))}
          />
          <ChartCard
            title={t("charts.accessDistribution")}
            emptyLabel={t("charts.empty")}
            data={charts.access_distribution.map((r) => ({
              label: t(`accessSource.${r.access_source}`),
              value: r.count,
            }))}
          />
          <ChartCard
            title={t("charts.conflictsByResourceType")}
            emptyLabel={t("charts.empty")}
            data={charts.conflicts_by_resource_type.map((r) => ({
              label: r.resource_type,
              value: r.count,
            }))}
          />
          <BroadAccessUsersCard users={charts.broad_access_users} />
          <ChartCard
            title={t("charts.failedAccessAttempts")}
            emptyLabel={t("charts.empty")}
            data={charts.failed_access_attempts.map((p) => ({
              label: p.date.slice(5),
              value: p.count,
            }))}
          />
        </div>
      ) : null}

      <div className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e1f2] px-5 py-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.role")}
            <select
              value={roleFilter}
              onChange={(e) => {
                setRoleFilter(e.target.value);
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {ROLE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.accessSource")}
            <select
              value={accessSourceFilter}
              onChange={(e) => {
                setAccessSourceFilter(e.target.value);
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {ACCESS_SOURCE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? t(`accessSource.${value}`) : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.resourceType")}
            <input
              type="text"
              value={resourceTypeFilter}
              onChange={(e) => {
                setResourceTypeFilter(e.target.value);
                resetPage();
              }}
              placeholder={t("filters.resourceTypePlaceholder")}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.conflictStatus")}
            <select
              value={conflictStatusFilter}
              onChange={(e) => {
                setConflictStatusFilter(e.target.value);
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {CONFLICT_STATUS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.search")}
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                resetPage();
              }}
              placeholder={t("filters.searchPlaceholder")}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
        </div>

        {rowsQuery.isLoading ? (
          <LoadingState
            compact
            title={t("states.loadingRows")}
            className="px-5 py-8"
          />
        ) : rowsQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={rowsQuery.error}
              description={getApiErrorMessage(rowsQuery.error)}
              onRetry={() => void rowsQuery.refetch()}
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
                  <th className="px-3 py-2">{t("table.team")}</th>
                  <th className="px-3 py-2">{t("table.resource")}</th>
                  <th className="px-3 py-2">{t("table.accessLevel")}</th>
                  <th className="px-3 py-2">{t("table.accessSource")}</th>
                  <th className="px-3 py-2">{t("table.conflictStatus")}</th>
                  <th className="px-3 py-2">{t("table.lastAccess")}</th>
                  <th className="px-3 py-2">{t("table.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <AccessRow key={row.id} row={row} />
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
