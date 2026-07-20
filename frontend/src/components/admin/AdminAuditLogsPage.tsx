"use client";

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

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
  t: ReturnType<typeof useTranslations>,
): Array<{ href: string; label: string }> {
  const links: Array<{ href: string; label: string }> = [];
  const documentId =
    trimToNull(event.document_id) ??
    (event.resource_type === "document" ? trimToNull(event.resource_id) : null);
  if (documentId) {
    links.push({
      href: `/documents/${encodeURIComponent(documentId)}`,
      label: t("openDocument"),
    });
  }

  const collectionId =
    trimToNull(event.collection_id) ??
    (event.resource_type === "collection"
      ? trimToNull(event.resource_id)
      : null);
  if (collectionId) {
    links.push({ href: "/collections", label: t("openCollections") });
  }

  const sessionId =
    trimToNull(event.session_id) ??
    (event.resource_type === "chat_session"
      ? trimToNull(event.resource_id)
      : null);
  if (sessionId) {
    links.push({
      href: `/chat?session_id=${encodeURIComponent(sessionId)}`,
      label: t("openChatSession"),
    });
  }

  return links;
}

function getActorLabel(
  item: AuditLogListItemResponse,
  systemLabel: string,
): string {
  if (item.user_id) {
    return item.user_id;
  }
  const actorEmail = item.metadata.actor_email;
  if (typeof actorEmail === "string" && actorEmail.trim().length > 0) {
    return actorEmail;
  }
  return systemLabel;
}

export function AdminAuditLogsPage() {
  const t = useTranslations("adminAuditLogs");
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
          title={t("restricted")}
          description={t("restrictedDescription")}
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
          description={t("unavailableDescription")}
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
    ? buildRelatedLinks(selectedEvent, t)
    : [];
  const uniqueActors = new Set(
    rows.map((item) => getActorLabel(item, t("system"))),
  ).size;
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
              {t("eyebrow")}
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-[#1b1b24]">
              {t("title")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-[#464555]">
              {t("description")}
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
                    ? t("preparingExport")
                    : t("exportCsv")}
                </button>
                <button
                  type="button"
                  onClick={() => exportMutation.mutate("json")}
                  disabled={exportMutation.isPending}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-4 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {t("exportJson")}
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
            {t("totalEvents")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(pageTotal)}
          </p>
        </article>

        <article className="rounded-xl border border-rose-200 bg-rose-50/50 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-rose-700 uppercase">
            {t("securityAlerts")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-rose-700">
            {formatInteger(securityAlerts)}
          </p>
        </article>

        <article className="rounded-xl border border-[#c7c4d8] bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
            {t("uniqueActors")}
          </p>
          <p className="mt-2 font-mono text-3xl font-semibold text-[#1b1b24]">
            {formatInteger(uniqueActors)}
          </p>
        </article>

        <article className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5 shadow-sm">
          <p className="text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
            {t("exportStatus")}
          </p>
          <p className="mt-2 text-lg font-semibold text-emerald-700">
            {exportsEnabled ? t("ready") : t("disabled")}
          </p>
        </article>
      </section>

      <section className="rounded-xl border border-[#c7c4d8] bg-white p-4 shadow-sm">
        <form className="space-y-3" onSubmit={applyFilters}>
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[240px] flex-1 space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("searchActor")}
              </span>
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t("searchPlaceholder")}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              />
            </label>

            <label className="w-[190px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("dateRange")}
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
                    {t(`ranges.${option.value}`)}
                  </option>
                ))}
              </select>
            </label>

            <label className="w-[190px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("actionType")}
              </span>
              <select
                value={actionInput}
                onChange={(event) => setActionInput(event.target.value)}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="">{t("allActions")}</option>
                <option value="auth.login.succeeded">{t("login")}</option>
                <option value="document.upload.accepted">{t("upload")}</option>
                <option value="collection.policy.updated">
                  {t("policyChange")}
                </option>
                <option value="chat.query.completed">{t("chatQuery")}</option>
              </select>
            </label>

            <label className="w-[170px] space-y-1">
              <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("severity")}
              </span>
              <select
                value={severityInput}
                onChange={(event) => setSeverityInput(event.target.value)}
                className="h-10 w-full rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
              >
                <option value="">{t("allLevels")}</option>
                <option value="info">{t("info")}</option>
                <option value="warning">{t("warning")}</option>
                <option value="critical">{t("critical")}</option>
              </select>
            </label>

            <button
              type="button"
              onClick={() => setShowAdvancedFilters((current) => !current)}
              className="h-10 rounded-lg border border-[#c7c4d8] px-3 text-xs font-semibold tracking-wide text-[#38485d] uppercase hover:bg-[#f5f2ff]"
            >
              {showAdvancedFilters ? t("hideAdvanced") : t("advancedFilters")}
            </button>
            <button
              type="submit"
              className="h-10 rounded-lg bg-[#3525cd] px-4 text-xs font-semibold tracking-wide text-white uppercase hover:bg-[#2b1fa8]"
            >
              {t("applyFilters")}
            </button>
            <button
              type="button"
              onClick={clearFilters}
              className="h-10 px-2 text-xs font-semibold tracking-wide text-[#3525cd] uppercase hover:underline"
            >
              {t("clearFilters")}
            </button>
          </div>

          {showAdvancedFilters ? (
            <div className="grid gap-3 border-t border-[#e4e1ee] pt-3 sm:grid-cols-2 xl:grid-cols-4">
              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("organization")}
                <input
                  value={organizationIdInput}
                  onChange={(event) =>
                    setOrganizationIdInput(event.target.value)
                  }
                  placeholder={t("organizationPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("actor")}
                <input
                  value={actorInput}
                  onChange={(event) => setActorInput(event.target.value)}
                  placeholder={t("actorPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("result")}
                <select
                  aria-label={t("result")}
                  value={resultFilterInput}
                  onChange={(event) =>
                    setResultFilterInput(
                      event.target.value as AppliedFilters["result"],
                    )
                  }
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                >
                  <option value="all">{t("allResults")}</option>
                  <option value="success">{t("success")}</option>
                  <option value="failure">{t("failure")}</option>
                  <option value="unknown">{t("unknown")}</option>
                </select>
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("entity")}
                <input
                  value={entityInput}
                  onChange={(event) => setEntityInput(event.target.value)}
                  placeholder={t("entityPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("resourceId")}
                <input
                  value={resourceIdInput}
                  onChange={(event) => setResourceIdInput(event.target.value)}
                  placeholder={t("resourcePlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("documentId")}
                <input
                  value={documentIdInput}
                  onChange={(event) => setDocumentIdInput(event.target.value)}
                  placeholder={t("documentPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("collectionId")}
                <input
                  value={collectionIdInput}
                  onChange={(event) => setCollectionIdInput(event.target.value)}
                  placeholder={t("collectionPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("ipAddress")}
                <input
                  value={ipAddressInput}
                  onChange={(event) => setIpAddressInput(event.target.value)}
                  placeholder={t("ipPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("sessionId")}
                <input
                  value={sessionIdInput}
                  onChange={(event) => setSessionIdInput(event.target.value)}
                  placeholder={t("sessionPlaceholder")}
                  className="h-10 rounded-lg border border-[#c7c4d8] bg-white px-3 text-sm text-[#1b1b24]"
                />
              </label>

              <label className="grid gap-1 text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("requestId")}
                <input
                  value={requestIdInput}
                  onChange={(event) => setRequestIdInput(event.target.value)}
                  placeholder={t("requestPlaceholder")}
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
              {t("auditEvents")}
            </h2>
            {auditQuery.isSuccess ? (
              <p className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                {t("showingCompact", {
                  start: formatInteger(pageStart),
                  end: formatInteger(pageEnd),
                  total: formatInteger(pageTotal),
                })}
              </p>
            ) : null}
          </div>

          {endpointUnavailable ? (
            <EmptyState
              compact
              className="m-4 rounded-lg border border-dashed border-[#d7d4e8] bg-[#fcfbff] px-3 py-3"
              title={t("endpointUnavailable")}
              description={t("endpointUnavailableDescription")}
            />
          ) : null}
          {auditQuery.isLoading ? (
            <LoadingState
              compact
              className="m-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
              title={t("loading")}
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
              title={t("empty")}
            />
          ) : null}

          {auditQuery.isSuccess && rows.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="border-b border-[#e4e1ee] bg-[#fcf8ff]">
                    <tr className="text-left text-[11px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      <th className="px-4 py-3">{t("timestampUtc")}</th>
                      <th className="px-4 py-3">{t("actor")}</th>
                      <th className="px-4 py-3">{t("action")}</th>
                      <th className="px-4 py-3">{t("entity")}</th>
                      <th className="px-4 py-3 text-center">{t("result")}</th>
                      <th className="px-4 py-3">{t("ipAddress")}</th>
                      <th className="px-4 py-3">{t("details")}</th>
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
                            {getActorLabel(item, t("system"))}
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
                              {t(item.result ?? "unknown")}
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
                              {t("viewDetails")}
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
                  {t("showingEvents", {
                    start: formatInteger(pageStart),
                    end: formatInteger(pageEnd),
                    total: formatInteger(pageTotal),
                  })}
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
                    {t("previous")}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setOffset((previous) => previous + AUDIT_PAGE_LIMIT)
                    }
                    disabled={!hasNextPage || auditQuery.isFetching}
                    className="rounded-lg border border-[#c7c4d8] px-3 py-2 text-sm font-semibold text-[#38485d] enabled:hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("next")}
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
              aria-label={t("closeEventDetails")}
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
                      {t("eventDetails")}
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
                    {t("close")}
                  </button>
                </div>

                <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                  {t("verifiedRecord")}
                </div>

                <dl className="grid gap-2 text-sm">
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("requestId")}
                    </dt>
                    <dd className="font-mono text-xs text-[#302f39]">
                      {sanitizeRequestId(selectedEvent.request_id) ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("organization")}
                    </dt>
                    <dd className="text-[#302f39]">
                      {selectedEvent.organization_id}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("actor")}
                    </dt>
                    <dd className="text-[#302f39]">
                      {getActorLabel(selectedEvent, t("system"))}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("resultSeverity")}
                    </dt>
                    <dd className="text-[#302f39]">
                      {(selectedEvent.result ?? "unknown").toUpperCase()} /{" "}
                      {selectedEvent.severity ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("ipSession")}
                    </dt>
                    <dd className="font-mono text-xs text-[#302f39]">
                      {selectedEvent.ip_address ?? "-"} /{" "}
                      {selectedEvent.session_id ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("timestamp")}
                    </dt>
                    <dd className="text-[#302f39]">
                      {formatTimestamp(selectedEvent.created_at)}
                    </dd>
                  </div>
                </dl>

                {selectedRelatedLinks.length > 0 ? (
                  <div className="mt-5">
                    <h4 className="text-xs font-semibold tracking-[0.08em] text-[#777587] uppercase">
                      {t("relatedLinks")}
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
                      {t("beforeAfterSummary")}
                    </h4>
                    {selectedBeforeAfter.changedFields.length > 0 ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-[#777587] uppercase">
                          {t("changedFields")}
                        </p>
                        <p className="text-sm text-[#302f39]">
                          {selectedBeforeAfter.changedFields.join(", ")}
                        </p>
                      </div>
                    ) : null}
                    {selectedBeforeAfter.before != null ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-rose-700 uppercase">
                          {t("before")}
                        </p>
                        <pre className="mt-1 overflow-x-auto rounded-lg bg-[#1f1f29] p-3 font-mono text-xs text-rose-100">
                          {JSON.stringify(selectedBeforeAfter.before, null, 2)}
                        </pre>
                      </div>
                    ) : null}
                    {selectedBeforeAfter.after != null ? (
                      <div>
                        <p className="text-[10px] font-semibold tracking-[0.08em] text-emerald-700 uppercase">
                          {t("after")}
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
                    {t("sanitizedMetadata")}
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

      <p className="text-xs text-[#68647b]">{t("exportNotice")}</p>
    </section>
  );
}
