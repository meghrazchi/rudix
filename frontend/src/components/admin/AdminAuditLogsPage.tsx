"use client";

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage, isApiClientError } from "@/lib/api/errors";
import {
  exportAuditLogs,
  listAuditLogs,
  type AuditLogExportFormat,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
import { queryKeys } from "@/lib/api/query";
import { getAuditStatusFilter, sanitizeAuditMetadata } from "@/lib/admin-audit";
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
import { useOverlayFocus } from "@/lib/use-overlay-focus";
import { useAuthSession } from "@/lib/use-auth-session";

const AUDIT_PAGE_LIMIT = 20;

type AppliedFilters = {
  organizationId: string | null;
  actor: string | null;
  action: string | null;
  entity: string | null;
  resourceId: string | null;
  documentId: string | null;
  collectionId: string | null;
  ipAddress: string | null;
  sessionId: string | null;
  requestId: string | null;
  result: "all" | "success" | "failure" | "unknown";
  severity: string | null;
  search: string | null;
};

type BeforeAfterSummary = {
  before: unknown | null;
  after: unknown | null;
  changedFields: string[];
};

const DEFAULT_FILTERS: AppliedFilters = {
  organizationId: null,
  actor: null,
  action: null,
  entity: null,
  resourceId: null,
  documentId: null,
  collectionId: null,
  ipAddress: null,
  sessionId: null,
  requestId: null,
  result: "all",
  severity: null,
  search: null,
};

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
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

function triggerBlobDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function buildExportFilename(
  format: AuditLogExportFormat,
  fromDate: string,
  toDate: string,
): string {
  return `audit-logs-${fromDate}-${toDate}.${format}`;
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => (typeof entry === "string" ? entry.trim() : ""))
    .filter((entry) => entry.length > 0);
}

function summarizeBeforeAfter(
  metadata: Record<string, unknown>,
): BeforeAfterSummary {
  const beforeCandidates = [
    "before_summary",
    "before",
    "old",
    "previous",
    "old_access_policy",
    "previous_value",
  ];
  const afterCandidates = [
    "after_summary",
    "after",
    "new",
    "current",
    "new_access_policy",
    "next_value",
  ];

  let before: unknown | null = null;
  for (const key of beforeCandidates) {
    if (key in metadata) {
      before = metadata[key] ?? null;
      break;
    }
  }

  let after: unknown | null = null;
  for (const key of afterCandidates) {
    if (key in metadata) {
      after = metadata[key] ?? null;
      break;
    }
  }

  const changedFields = [
    ...normalizeStringArray(metadata.changed_fields),
    ...normalizeStringArray(metadata.changed_field_names),
  ];

  return { before, after, changedFields };
}

function resultPillClass(result: AuditLogListItemResponse["result"]): string {
  if (result === "success") {
    return "bg-emerald-100 text-emerald-800";
  }
  if (result === "failure") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-200 text-slate-700";
}

function buildRelatedLinks(
  event: AuditLogListItemResponse,
): Array<{ href: string; label: string }> {
  const links: Array<{ href: string; label: string }> = [];
  const documentId =
    trimToNull(event.document_id) ??
    (event.resource_type === "document" ? trimToNull(event.resource_id) : null);
  if (documentId) {
    links.push({
      href: `/documents/${encodeURIComponent(documentId)}`,
      label: "Open document",
    });
  }

  const collectionId =
    trimToNull(event.collection_id) ??
    (event.resource_type === "collection"
      ? trimToNull(event.resource_id)
      : null);
  if (collectionId) {
    links.push({ href: "/collections", label: "Open collections" });
  }

  const sessionId =
    trimToNull(event.session_id) ??
    (event.resource_type === "chat_session"
      ? trimToNull(event.resource_id)
      : null);
  if (sessionId) {
    links.push({
      href: `/chat?session_id=${encodeURIComponent(sessionId)}`,
      label: "Open chat session",
    });
  }

  return links;
}

function getActorLabel(item: AuditLogListItemResponse): string {
  if (item.user_id) {
    return item.user_id;
  }
  const actorEmail = item.metadata.actor_email;
  if (typeof actorEmail === "string" && actorEmail.trim().length > 0) {
    return actorEmail;
  }
  return "System";
}

export function AdminAuditLogsPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const exportsEnabled = getFrontendRuntimeConfig().features.exports;

  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [organizationIdInput, setOrganizationIdInput] = useState("");
  const [actorInput, setActorInput] = useState("");
  const [actionInput, setActionInput] = useState("");
  const [entityInput, setEntityInput] = useState("");
  const [resourceIdInput, setResourceIdInput] = useState("");
  const [documentIdInput, setDocumentIdInput] = useState("");
  const [collectionIdInput, setCollectionIdInput] = useState("");
  const [ipAddressInput, setIpAddressInput] = useState("");
  const [sessionIdInput, setSessionIdInput] = useState("");
  const [requestIdInput, setRequestIdInput] = useState("");
  const [resultFilterInput, setResultFilterInput] =
    useState<AppliedFilters["result"]>("all");
  const [severityInput, setSeverityInput] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [offset, setOffset] = useState(0);
  const [drawerTop, setDrawerTop] = useState(12);
  const [selectedEvent, setSelectedEvent] =
    useState<AuditLogListItemResponse | null>(null);
  const [appliedFilters, setAppliedFilters] =
    useState<AppliedFilters>(DEFAULT_FILTERS);

  const eventDrawerRef = useRef<HTMLElement | null>(null);
  const tableOverlayHostRef = useRef<HTMLDivElement | null>(null);
  const closeSelectedEvent = useCallback(() => {
    setSelectedEvent(null);
  }, []);

  useOverlayFocus({
    isOpen: selectedEvent != null,
    containerRef: eventDrawerRef,
    onClose: closeSelectedEvent,
    lockBodyScroll: false,
  });

  const usageRange = useMemo(
    () => resolveUsageDateRange(rangePreset),
    [rangePreset],
  );

  const queryParams = useMemo(
    () => ({
      from: usageRange.from,
      to: usageRange.to,
      limit: AUDIT_PAGE_LIMIT,
      offset,
      organization_id:
        appliedFilters.organizationId ??
        state.session?.organizationId ??
        undefined,
      actor: appliedFilters.actor ?? undefined,
      action: appliedFilters.action ?? undefined,
      entity: appliedFilters.entity ?? undefined,
      resource_id: appliedFilters.resourceId ?? undefined,
      document_id: appliedFilters.documentId ?? undefined,
      collection_id: appliedFilters.collectionId ?? undefined,
      ip_address: appliedFilters.ipAddress ?? undefined,
      session_id: appliedFilters.sessionId ?? undefined,
      request_id: appliedFilters.requestId ?? undefined,
      result: appliedFilters.result,
      severity: appliedFilters.severity ?? undefined,
      search: appliedFilters.search ?? undefined,
    }),
    [
      appliedFilters,
      offset,
      state.session?.organizationId,
      usageRange.from,
      usageRange.to,
    ],
  );

  const auditQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs(queryParams),
    queryFn: () => listAuditLogs(queryParams),
    enabled: isAdminUser,
  });

  const exportMutation = useMutation({
    mutationFn: async (format: AuditLogExportFormat) =>
      exportAuditLogs(format, {
        ...queryParams,
        limit: undefined,
        offset: undefined,
      }),
    onSuccess: (blob, format) => {
      const filename = buildExportFilename(
        format,
        usageRange.from,
        usageRange.to,
      );
      triggerBlobDownload(blob, filename);
    },
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
  const rows = audit?.items ?? [];
  const pageTotal = audit?.total ?? 0;
  const pageStart = pageTotal === 0 ? 0 : offset + 1;
  const pageEnd =
    pageTotal === 0 ? 0 : Math.min(offset + AUDIT_PAGE_LIMIT, pageTotal);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + AUDIT_PAGE_LIMIT < pageTotal;

  const selectedSanitizedMetadata = selectedEvent
    ? sanitizeAuditMetadata(selectedEvent.metadata)
    : null;
  const selectedBeforeAfter = selectedSanitizedMetadata
    ? summarizeBeforeAfter(selectedSanitizedMetadata)
    : null;
  const selectedRelatedLinks = selectedEvent
    ? buildRelatedLinks(selectedEvent)
    : [];
  const uniqueActors = new Set(rows.map((item) => getActorLabel(item))).size;
  const securityAlerts = rows.filter((item) => {
    const severity =
      typeof item.severity === "string" ? item.severity.toLowerCase() : "";
    const status = getAuditStatusFilter(item);
    return (
      item.result === "failure" ||
      status === "server_error" ||
      severity === "warning" ||
      severity === "critical"
    );
  }).length;

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setOffset(0);
    setAppliedFilters({
      organizationId: trimToNull(organizationIdInput),
      actor: trimToNull(actorInput),
      action: trimToNull(actionInput),
      entity: trimToNull(entityInput),
      resourceId: trimToNull(resourceIdInput),
      documentId: trimToNull(documentIdInput),
      collectionId: trimToNull(collectionIdInput),
      ipAddress: trimToNull(ipAddressInput),
      sessionId: trimToNull(sessionIdInput),
      requestId: trimToNull(requestIdInput),
      result: resultFilterInput,
      severity: trimToNull(severityInput),
      search: trimToNull(searchInput),
    });
  }

  function clearFilters(): void {
    const sessionOrganizationId = state.session?.organizationId ?? "";
    setOrganizationIdInput(sessionOrganizationId);
    setActorInput("");
    setActionInput("");
    setEntityInput("");
    setResourceIdInput("");
    setDocumentIdInput("");
    setCollectionIdInput("");
    setIpAddressInput("");
    setSessionIdInput("");
    setRequestIdInput("");
    setResultFilterInput("all");
    setSeverityInput("");
    setSearchInput("");
    setOffset(0);
    setAppliedFilters({
      ...DEFAULT_FILTERS,
      organizationId: trimToNull(sessionOrganizationId),
    });
  }

  function openEventDetails(
    item: AuditLogListItemResponse,
    triggerElement: HTMLElement | null,
  ): void {
    setSelectedEvent(item);

    const hostElement = tableOverlayHostRef.current;
    if (!hostElement || !triggerElement) {
      setDrawerTop(12);
      return;
    }

    const rowElement = triggerElement.closest("tr");
    if (!(rowElement instanceof HTMLElement)) {
      setDrawerTop(12);
      return;
    }

    const hostRect = hostElement.getBoundingClientRect();
    const rowRect = rowElement.getBoundingClientRect();
    const preferredTop = rowRect.top - hostRect.top;
    const maxTop = Math.max(12, hostElement.clientHeight - 560);
    const boundedTop = Math.max(12, Math.min(preferredTop, maxTop));
    setDrawerTop(boundedTop);
  }

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.16em] text-[#3525cd] uppercase">
              Compliance &amp; Governance
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              Audit logs
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              Track and inspect immutable system events across your organization
              for security and compliance audits.
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            {exportsEnabled ? (
              <>
                <button
                  type="button"
                  onClick={() => exportMutation.mutate("csv")}
                  disabled={exportMutation.isPending}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {exportMutation.isPending
                    ? "Preparing export..."
                    : "Export CSV"}
                </button>
                <button
                  type="button"
                  onClick={() => exportMutation.mutate("json")}
                  disabled={exportMutation.isPending}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Export JSON
                </button>
              </>
            ) : null}
          </div>
        </div>

        {exportMutation.isError ? (
          <p className="mt-3 text-sm text-rose-700">
            {getApiErrorMessage(exportMutation.error)}
          </p>
        ) : null}
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            Total events
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(pageTotal)}
          </p>
        </article>

        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            Security alerts
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {formatInteger(securityAlerts)}
          </p>
        </article>

        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            Unique actors (page)
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(uniqueActors)}
          </p>
        </article>

        <article className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            Export status
          </p>
          <p className="mt-2 text-lg font-semibold text-emerald-700">
            {exportsEnabled ? "Ready" : "Disabled"}
          </p>
        </article>
      </section>

      <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
        <form className="space-y-3" onSubmit={applyFilters}>
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[240px] flex-1 space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Search actor / ID
              </span>
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="req_9a21b... / actor / document"
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="w-[190px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Date range
              </span>
              <select
                value={rangePreset}
                onChange={(event) => {
                  setOffset(0);
                  setRangePreset(event.target.value as DashboardRangePreset);
                }}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                {DASHBOARD_RANGE_PRESETS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="w-[190px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Action type
              </span>
              <select
                value={actionInput}
                onChange={(event) => setActionInput(event.target.value)}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="">All actions</option>
                <option value="auth.login.succeeded">Login</option>
                <option value="document.upload.accepted">Upload</option>
                <option value="collection.policy.updated">Policy change</option>
                <option value="chat.query.completed">Chat query</option>
              </select>
            </label>

            <label className="w-[170px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Severity
              </span>
              <select
                value={severityInput}
                onChange={(event) => setSeverityInput(event.target.value)}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="">All levels</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </label>

            <button
              type="button"
              onClick={() => setShowAdvancedFilters((current) => !current)}
              className="h-10 rounded-lg border border-[#c7c4d8] px-3 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
            >
              {showAdvancedFilters ? "Hide advanced" : "Advanced filters"}
            </button>
            <button
              type="submit"
              className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8]"
            >
              Apply filters
            </button>
            <button
              type="button"
              onClick={clearFilters}
              className="h-10 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
            >
              Clear filters
            </button>
          </div>

          {showAdvancedFilters ? (
            <div className="grid gap-3 border-t border-[#e4e1ee] pt-3 sm:grid-cols-2 xl:grid-cols-4">
              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Organization
                <input
                  value={organizationIdInput}
                  onChange={(event) =>
                    setOrganizationIdInput(event.target.value)
                  }
                  placeholder="Current org UUID"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Actor
                <input
                  value={actorInput}
                  onChange={(event) => setActorInput(event.target.value)}
                  placeholder="UUID, email, or system"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Result
                <select
                  aria-label="Result"
                  value={resultFilterInput}
                  onChange={(event) =>
                    setResultFilterInput(
                      event.target.value as AppliedFilters["result"],
                    )
                  }
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                >
                  <option value="all">All results</option>
                  <option value="success">Success</option>
                  <option value="failure">Failure</option>
                  <option value="unknown">Unknown</option>
                </select>
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Entity
                <input
                  value={entityInput}
                  onChange={(event) => setEntityInput(event.target.value)}
                  placeholder="document, collection..."
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Resource ID
                <input
                  value={resourceIdInput}
                  onChange={(event) => setResourceIdInput(event.target.value)}
                  placeholder="Entity UUID"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Document ID
                <input
                  value={documentIdInput}
                  onChange={(event) => setDocumentIdInput(event.target.value)}
                  placeholder="Document UUID"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Collection ID
                <input
                  value={collectionIdInput}
                  onChange={(event) => setCollectionIdInput(event.target.value)}
                  placeholder="Collection UUID"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                IP Address
                <input
                  value={ipAddressInput}
                  onChange={(event) => setIpAddressInput(event.target.value)}
                  placeholder="IP or subnet fragment"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Session ID
                <input
                  value={sessionIdInput}
                  onChange={(event) => setSessionIdInput(event.target.value)}
                  placeholder="Session / JTI"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Request ID
                <input
                  value={requestIdInput}
                  onChange={(event) => setRequestIdInput(event.target.value)}
                  placeholder="Trace request ID"
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>
            </div>
          ) : null}
        </form>
      </section>

      <div ref={tableOverlayHostRef} className="relative">
        <section className="overflow-hidden rounded-xl border border-[#c7c4d8] bg-white shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#e4e1ee] bg-[#f5f2ff] px-4 py-3">
            <h2 className="text-lg font-semibold text-[#1b1b24]">
              Audit events
            </h2>
            {auditQuery.isSuccess ? (
              <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                Showing {formatInteger(pageStart)}-{formatInteger(pageEnd)} of{" "}
                {formatInteger(pageTotal)}
              </p>
            ) : null}
          </div>

          {endpointUnavailable ? (
            <EmptyState
              compact
              className="m-4 rounded-lg border border-dashed border-[#d7d4e8] bg-[#fcfbff] px-3 py-3"
              title="Audit log endpoint is not configured for this deployment."
              description="Enable GET /admin/audit-logs in the backend to populate this page."
            />
          ) : null}
          {auditQuery.isLoading ? (
            <LoadingState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
              title="Loading audit events..."
            />
          ) : null}
          {auditQuery.isError && !endpointUnavailable ? (
            <div className="m-4">
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
          {auditQuery.isSuccess && rows.length === 0 ? (
            <EmptyState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#68647b]"
              title="No audit events match the current filters."
            />
          ) : null}

          {auditQuery.isSuccess && rows.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                    <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      <th className="px-4 py-3">Timestamp (UTC)</th>
                      <th className="px-4 py-3">Actor</th>
                      <th className="px-4 py-3">Action</th>
                      <th className="px-4 py-3">Entity</th>
                      <th className="px-4 py-3 text-center">Result</th>
                      <th className="px-4 py-3">IP address</th>
                      <th className="px-4 py-3">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#ece9f5]">
                    {rows.map((item) => {
                      const isSelected =
                        selectedEvent?.audit_log_id === item.audit_log_id;

                      return (
                        <tr
                          key={item.audit_log_id}
                          onClick={(event) =>
                            openEventDetails(item, event.currentTarget)
                          }
                          className={`cursor-pointer transition-colors ${
                            isSelected ? "bg-[#ebe8ff]" : "hover:bg-[#f5f2ff]"
                          }`}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                            {formatTimestamp(item.created_at)}
                          </td>
                          <td className="px-4 py-3 text-sm font-medium text-[#1b1b24]">
                            {getActorLabel(item)}
                          </td>
                          <td className="px-4 py-3">
                            <span className="rounded border border-[#c7c4d8] bg-[#f5f2ff] px-2 py-1 font-mono text-[11px] text-[#2b1fa8] uppercase">
                              {item.action}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-[#302f39]">
                            {item.resource_type}
                            {item.resource_id ? `:${item.resource_id}` : ""}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              className={`rounded-full px-2 py-1 text-[10px] font-semibold tracking-wide uppercase ${resultPillClass(
                                item.result,
                              )}`}
                            >
                              {item.result ?? "unknown"}
                            </span>
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-[#464555]">
                            {item.ip_address ?? "-"}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                openEventDetails(item, event.currentTarget);
                              }}
                              className="rounded-lg border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
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

              <div className="flex items-center justify-between gap-3 border-t border-[#e4e1ee] px-4 py-3">
                <p className="text-sm text-[#464555]">
                  Showing {formatInteger(pageStart)} to {formatInteger(pageEnd)}{" "}
                  of {formatInteger(pageTotal)} events
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setOffset((previous) =>
                        Math.max(0, previous - AUDIT_PAGE_LIMIT),
                      )
                    }
                    disabled={!hasPreviousPage || auditQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setOffset((previous) => previous + AUDIT_PAGE_LIMIT)
                    }
                    disabled={!hasNextPage || auditQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {selectedEvent ? (
          <>
            <button
              type="button"
              aria-label="Close event details"
              onClick={closeSelectedEvent}
              className="absolute inset-0 z-10 bg-[#17172a]/15 xl:bg-transparent"
            />
            <aside
              ref={eventDrawerRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="audit-event-details-title"
              className="absolute right-0 z-20 max-h-[min(78vh,720px)] w-full max-w-[430px] overflow-y-auto rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-2xl"
              style={{ top: `${drawerTop}px` }}
            >
              <>
                <div className="mb-4 flex items-start justify-between gap-3 border-b border-[#e4e1ee] pb-3">
                  <div>
                    <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Event details
                    </p>
                    <h3
                      id="audit-event-details-title"
                      className="mt-1 text-base font-semibold text-[#1b1b24]"
                    >
                      {selectedEvent.action}
                    </h3>
                  </div>
                  <button
                    type="button"
                    data-overlay-autofocus="true"
                    onClick={closeSelectedEvent}
                    className="rounded border border-[#c7c4d8] px-2 py-1 text-xs font-semibold text-[#38485d] hover:bg-[#f5f2ff]"
                  >
                    Close
                  </button>
                </div>

                <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                  Verified immutable record
                </div>

                <dl className="grid gap-2 text-sm">
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Request ID
                    </dt>
                    <dd className="font-mono text-xs text-[#302f39]">
                      {sanitizeRequestId(selectedEvent.request_id) ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Organization
                    </dt>
                    <dd className="text-[#302f39]">
                      {selectedEvent.organization_id}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Actor
                    </dt>
                    <dd className="text-[#302f39]">
                      {getActorLabel(selectedEvent)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Result / Severity
                    </dt>
                    <dd className="text-[#302f39]">
                      {(selectedEvent.result ?? "unknown").toUpperCase()} /{" "}
                      {selectedEvent.severity ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      IP / Session
                    </dt>
                    <dd className="font-mono text-xs text-[#302f39]">
                      {selectedEvent.ip_address ?? "-"} /{" "}
                      {selectedEvent.session_id ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Timestamp
                    </dt>
                    <dd className="text-[#302f39]">
                      {formatTimestamp(selectedEvent.created_at)}
                    </dd>
                  </div>
                </dl>

                {selectedRelatedLinks.length > 0 ? (
                  <div className="mt-5">
                    <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Related links
                    </h4>
                    <div className="mt-2 grid gap-2">
                      {selectedRelatedLinks.map((link) => (
                        <Link
                          key={`${link.href}:${link.label}`}
                          href={link.href}
                          className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
                        >
                          {link.label}
                        </Link>
                      ))}
                    </div>
                  </div>
                ) : null}

                {selectedBeforeAfter &&
                (selectedBeforeAfter.before != null ||
                  selectedBeforeAfter.after != null ||
                  selectedBeforeAfter.changedFields.length > 0) ? (
                  <div className="mt-5 space-y-3">
                    <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      Before/after summary
                    </h4>
                    {selectedBeforeAfter.changedFields.length > 0 ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                          Changed fields
                        </p>
                        <p className="text-sm text-[#302f39]">
                          {selectedBeforeAfter.changedFields.join(", ")}
                        </p>
                      </div>
                    ) : null}
                    {selectedBeforeAfter.before != null ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-rose-700 uppercase">
                          Before
                        </p>
                        <pre className="mt-1 overflow-x-auto rounded-lg bg-[#1f1f29] p-3 font-mono text-xs text-rose-100">
                          {JSON.stringify(selectedBeforeAfter.before, null, 2)}
                        </pre>
                      </div>
                    ) : null}
                    {selectedBeforeAfter.after != null ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                          After
                        </p>
                        <pre className="mt-1 overflow-x-auto rounded-lg bg-[#1f1f29] p-3 font-mono text-xs text-emerald-100">
                          {JSON.stringify(selectedBeforeAfter.after, null, 2)}
                        </pre>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="mt-5">
                  <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                    Sanitized metadata
                  </h4>
                  <pre className="mt-2 overflow-x-auto rounded-lg border border-[#e4e1ee] bg-[#faf9ff] p-3 text-xs text-[#302f39]">
                    {JSON.stringify(selectedSanitizedMetadata, null, 2)}
                  </pre>
                </div>
              </>
            </aside>
          </>
        ) : null}
      </div>

      <p className="text-xs text-[#68647b]">
        Exports include sanitized metadata only. Secrets and raw private
        document content are excluded.
      </p>
    </section>
  );
}
