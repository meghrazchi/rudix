"use client";

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  listAuditLogs,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
import { queryKeys } from "@/lib/api/query";
import {
  formatAuditStatusLabel,
  getAuditStatusCode,
  getAuditStatusFilter,
  matchesAuditStatusFilter,
  sanitizeAuditMetadata,
  type AuditStatusFilter,
} from "@/lib/admin-audit";
import {
  canViewAdminUsage,
  DASHBOARD_RANGE_PRESETS,
  formatInteger,
  resolveUsageDateRange,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import {
  extractRequestIdFromError,
  isForbiddenError,
  sanitizeRequestId,
} from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { isExternalHref } from "@/lib/top-bar";
import { useOverlayFocus } from "@/lib/use-overlay-focus";
import { useAuthSession } from "@/lib/use-auth-session";

const AUDIT_PAGE_LIMIT = 20;

type AppliedFilters = {
  userId: string | null;
  action: string | null;
  resourceType: string | null;
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

function resolveAuditExportUrl(): string | null {
  if (!getFrontendRuntimeConfig().features.exports) {
    return null;
  }
  const configured = process.env.NEXT_PUBLIC_ADMIN_AUDIT_EXPORT_URL?.trim();
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

function statusBadgeClass(filter: Exclude<AuditStatusFilter, "all">): string {
  if (filter === "success") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (filter === "client_error") {
    return "bg-amber-100 text-amber-800";
  }
  if (filter === "server_error") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-200 text-slate-700";
}

export function AdminAuditLogsPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [userIdInput, setUserIdInput] = useState("");
  const [actionInput, setActionInput] = useState("");
  const [resourceTypeInput, setResourceTypeInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<AuditStatusFilter>("all");
  const [offset, setOffset] = useState(0);
  const [selectedEvent, setSelectedEvent] =
    useState<AuditLogListItemResponse | null>(null);
  const eventDrawerRef = useRef<HTMLElement | null>(null);
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({
    userId: null,
    action: null,
    resourceType: null,
  });

  const closeSelectedEvent = useCallback(() => {
    setSelectedEvent(null);
  }, [setSelectedEvent]);

  useOverlayFocus({
    isOpen: selectedEvent != null,
    containerRef: eventDrawerRef,
    onClose: closeSelectedEvent,
  });

  const usageRange = useMemo(
    () => resolveUsageDateRange(rangePreset),
    [rangePreset],
  );
  const exportBaseUrl = resolveAuditExportUrl();

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs({
      from: usageRange.from,
      to: usageRange.to,
      limit: AUDIT_PAGE_LIMIT,
      offset,
      user_id: appliedFilters.userId,
      action: appliedFilters.action,
      resource_type: appliedFilters.resourceType,
    }),
    queryFn: () =>
      listAuditLogs({
        from: usageRange.from,
        to: usageRange.to,
        limit: AUDIT_PAGE_LIMIT,
        offset,
        user_id: appliedFilters.userId ?? undefined,
        action: appliedFilters.action ?? undefined,
        resource_type: appliedFilters.resourceType ?? undefined,
      }),
    enabled: isAdminUser,
  });

  const forbiddenError =
    auditQuery.isError && isForbiddenError(auditQuery.error)
      ? auditQuery.error
      : null;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin audit logs restricted"
          description="Only owner and admin roles can access audit logs."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Audit logs unavailable"
          description="Your role no longer has access to audit logs."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  const audit = auditQuery.data;
  const endpointUnavailable =
    auditQuery.isError &&
    isApiClientError(auditQuery.error) &&
    auditQuery.error.status === 404;
  const filteredEvents = (audit?.items ?? []).filter((event) =>
    matchesAuditStatusFilter(event, statusFilter),
  );
  const pageTotal = audit?.total ?? 0;
  const pageStart = pageTotal === 0 ? 0 : offset + 1;
  const pageEnd =
    pageTotal === 0 ? 0 : Math.min(offset + AUDIT_PAGE_LIMIT, pageTotal);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + AUDIT_PAGE_LIMIT < pageTotal;
  const exportUrl = exportBaseUrl
    ? withExportQuery(exportBaseUrl, {
        from: usageRange.from,
        to: usageRange.to,
        user_id: appliedFilters.userId ?? undefined,
        action: appliedFilters.action ?? undefined,
        resource_type: appliedFilters.resourceType ?? undefined,
      })
    : null;
  const exportExternal = exportUrl ? isExternalHref(exportUrl) : false;
  const selectedStatus = selectedEvent
    ? getAuditStatusFilter(selectedEvent)
    : null;
  const selectedStatusCode = selectedEvent
    ? getAuditStatusCode(selectedEvent.metadata)
    : null;
  const selectedSanitizedMetadata = selectedEvent
    ? sanitizeAuditMetadata(selectedEvent.metadata)
    : null;

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setOffset(0);
    setAppliedFilters({
      userId: trimToNull(userIdInput),
      action: trimToNull(actionInput),
      resourceType: trimToNull(resourceTypeInput),
    });
  }

  function clearFilters(): void {
    setUserIdInput("");
    setActionInput("");
    setResourceTypeInput("");
    setStatusFilter("all");
    setOffset(0);
    setAppliedFilters({ userId: null, action: null, resourceType: null });
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
              Audit logs
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Inspect audit events by actor, action, resource, status, and
              sanitized metadata.
            </p>
          </div>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Date range
            <select
              value={rangePreset}
              onChange={(event) => {
                setOffset(0);
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
        <form
          className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_1fr_auto_auto]"
          onSubmit={applyFilters}
        >
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            User ID
            <input
              value={userIdInput}
              onChange={(event) => setUserIdInput(event.target.value)}
              placeholder="UUID (optional)"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Action
            <input
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              placeholder="e.g. documents.reindex.queued"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Resource type
            <input
              value={resourceTypeInput}
              onChange={(event) => setResourceTypeInput(event.target.value)}
              placeholder="document, chat_session..."
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
            Status
            <select
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as AuditStatusFilter)
              }
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
            >
              <option value="all">All statuses</option>
              <option value="success">Success</option>
              <option value="client_error">Client error</option>
              <option value="server_error">Server error</option>
              <option value="unknown">Unknown</option>
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

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-lg font-bold text-[#2a2640]">Audit events</h2>
          {auditQuery.isSuccess ? (
            <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Showing {formatInteger(pageStart)}-{formatInteger(pageEnd)} of{" "}
              {formatInteger(pageTotal)}
            </p>
          ) : null}
        </div>

        {endpointUnavailable ? (
          <EmptyState
            compact
            className="mt-3 rounded-lg border border-dashed border-[#d7d4e8] bg-[#fcfbff] px-3 py-3"
            title="Audit log endpoint is not configured for this deployment."
            description="Enable GET /admin/audit-logs in the backend to populate this page."
          />
        ) : null}
        {auditQuery.isLoading ? (
          <LoadingState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
            title="Loading audit events..."
          />
        ) : null}
        {auditQuery.isError && !endpointUnavailable ? (
          <div className="mt-3">
            <ErrorState
              compact
              error={auditQuery.error}
              description={getApiErrorMessage(auditQuery.error)}
              onRetry={() => {
                void auditQuery.refetch();
              }}
            />
          </div>
        ) : null}
        {auditQuery.isSuccess && filteredEvents.length === 0 ? (
          <EmptyState
            compact
            className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
            title="No audit events match the current filters."
          />
        ) : null}

        {auditQuery.isSuccess && filteredEvents.length > 0 ? (
          <>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full divide-y divide-[#e6e3f3] text-sm">
                <thead>
                  <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                    <th className="px-3 py-2">Actor</th>
                    <th className="px-3 py-2">Action</th>
                    <th className="px-3 py-2">Resource</th>
                    <th className="px-3 py-2">Timestamp</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Metadata</th>
                    <th className="px-3 py-2">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f0edf8]">
                  {filteredEvents.map((item) => {
                    const status = getAuditStatusFilter(item);
                    const statusCode = getAuditStatusCode(item.metadata);
                    const metadataKeys = Object.keys(item.metadata ?? {});
                    return (
                      <tr key={item.audit_log_id}>
                        <td className="px-3 py-2 text-[#4d4963]">
                          {item.user_id ?? "System"}
                        </td>
                        <td className="px-3 py-2 font-semibold text-[#2f2a46]">
                          {item.action}
                        </td>
                        <td className="px-3 py-2 text-[#4d4963]">
                          {item.resource_type}
                          {item.resource_id ? `:${item.resource_id}` : ""}
                        </td>
                        <td className="px-3 py-2 text-[#4d4963]">
                          {formatTimestamp(item.created_at)}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`rounded-full px-2 py-1 text-xs font-bold tracking-wide uppercase ${statusBadgeClass(status)}`}
                          >
                            {formatAuditStatusLabel(status)}
                            {statusCode ? ` (${statusCode})` : ""}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-[#4d4963]">
                          {formatInteger(metadataKeys.length)} keys
                        </td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => setSelectedEvent(item)}
                            className="rounded-lg border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
                          >
                            View details
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() =>
                  setOffset((previous) =>
                    Math.max(0, previous - AUDIT_PAGE_LIMIT),
                  )
                }
                disabled={!hasPreviousPage || auditQuery.isFetching}
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] enabled:hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() =>
                  setOffset((previous) => previous + AUDIT_PAGE_LIMIT)
                }
                disabled={!hasNextPage || auditQuery.isFetching}
                className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3f3b58] enabled:hover:bg-[#f8f6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </>
        ) : null}
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Export</h2>
        {exportUrl ? (
          <Link
            href={exportUrl}
            target={exportExternal ? "_blank" : undefined}
            rel={exportExternal ? "noreferrer noopener" : undefined}
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
              Set <code>NEXT_PUBLIC_ADMIN_AUDIT_EXPORT_URL</code> to enable CSV
              export.
            </p>
          </div>
        )}
      </section>

      {selectedEvent ? (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-[#17172a]/35"
          onClick={closeSelectedEvent}
        >
          <aside
            ref={eventDrawerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="audit-event-details-title"
            className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
                  Audit event details
                </p>
                <h3
                  id="audit-event-details-title"
                  className="mt-1 text-lg font-bold text-[#2a2640]"
                >
                  {selectedEvent.action}
                </h3>
              </div>
              <button
                type="button"
                data-overlay-autofocus="true"
                onClick={closeSelectedEvent}
                className="rounded border border-[#d2cee6] px-2 py-1 text-xs font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
              >
                Close
              </button>
            </div>
            <dl className="mt-4 grid gap-2 text-sm">
              <div>
                <dt className="font-semibold text-[#2a2640]">Actor</dt>
                <dd className="text-[#4d4963]">
                  {selectedEvent.user_id ?? "System"}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-[#2a2640]">Resource</dt>
                <dd className="text-[#4d4963]">
                  {selectedEvent.resource_type}
                  {selectedEvent.resource_id
                    ? `:${selectedEvent.resource_id}`
                    : ""}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-[#2a2640]">Timestamp</dt>
                <dd className="text-[#4d4963]">
                  {formatTimestamp(selectedEvent.created_at)}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-[#2a2640]">Status</dt>
                <dd className="text-[#4d4963]">
                  {selectedStatus
                    ? formatAuditStatusLabel(selectedStatus)
                    : "Unknown"}
                  {selectedStatusCode ? ` (${selectedStatusCode})` : ""}
                </dd>
              </div>
              {sanitizeRequestId(selectedEvent.request_id) ? (
                <div>
                  <dt className="font-semibold text-[#2a2640]">Trace ID</dt>
                  <dd className="text-[#4d4963]">
                    {sanitizeRequestId(selectedEvent.request_id)}
                  </dd>
                </div>
              ) : null}
            </dl>
            <div className="mt-5">
              <h4 className="text-sm font-semibold text-[#2a2640]">
                Sanitized metadata
              </h4>
              <pre className="mt-2 overflow-x-auto rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-xs text-[#2f2a46]">
                {JSON.stringify(selectedSanitizedMetadata, null, 2)}
              </pre>
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
