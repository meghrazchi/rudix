import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { isApiClientError } from "@/lib/api/errors";
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
  resolveUsageDateRange,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { useOverlayFocus } from "@/lib/use-overlay-focus";
import { useAuthSession } from "@/lib/use-auth-session";
import {
  AUDIT_PAGE_LIMIT,
  DEFAULT_FILTERS,
  trimToNull,
  triggerBlobDownload,
  buildExportFilename,
  summarizeBeforeAfter,
  buildRelatedLinks,
  getActorLabel,
  type AppliedFilters,
} from "@/components/admin/audit-logs/auditShared";

export function useAuditLogsController() {
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
  return {
    t,
    state,
    role,
    isAdminUser,
    exportsEnabled,
    rangePreset,
    setRangePreset,
    organizationIdInput,
    setOrganizationIdInput,
    actorInput,
    setActorInput,
    actionInput,
    setActionInput,
    entityInput,
    setEntityInput,
    resourceIdInput,
    setResourceIdInput,
    documentIdInput,
    setDocumentIdInput,
    collectionIdInput,
    setCollectionIdInput,
    ipAddressInput,
    setIpAddressInput,
    sessionIdInput,
    setSessionIdInput,
    requestIdInput,
    setRequestIdInput,
    resultFilterInput,
    setResultFilterInput,
    severityInput,
    setSeverityInput,
    searchInput,
    setSearchInput,
    showAdvancedFilters,
    setShowAdvancedFilters,
    offset,
    setOffset,
    drawerTop,
    setDrawerTop,
    selectedEvent,
    setSelectedEvent,
    appliedFilters,
    setAppliedFilters,
    eventDrawerRef,
    tableOverlayHostRef,
    closeSelectedEvent,
    usageRange,
    queryParams,
    auditQuery,
    exportMutation,
    forbiddenError,
    audit,
    endpointUnavailable,
    rows,
    pageTotal,
    pageStart,
    pageEnd,
    hasPreviousPage,
    hasNextPage,
    selectedSanitizedMetadata,
    selectedBeforeAfter,
    selectedRelatedLinks,
    uniqueActors,
    securityAlerts,
    applyFilters,
    clearFilters,
    openEventDetails,
  };
}
