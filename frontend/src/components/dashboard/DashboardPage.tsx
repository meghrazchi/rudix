"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getUsageSummary,
  listAuditLogs,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
import {
  getBillingCapabilities,
  getBillingPlanInfo,
  type BillingPlanStatus,
} from "@/lib/api/billing";
import { listChatSessions, type ChatSessionResponse } from "@/lib/api/chat";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  listDocuments,
  type DocumentListItemResponse,
  type DocumentStatus,
} from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import {
  canViewAdminUsage,
  computeIndexingSuccess,
  DASHBOARD_RANGE_PRESETS,
  estimateQuestionsAsked,
  extractAverageConfidence,
  extractAverageLatencyMs,
  extractLatencyScore,
  formatInteger,
  formatLatencyMs,
  formatPercentage,
  formatUsd,
  resolveUsageDateRange,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import { resolveDocumentCapabilities } from "@/lib/documents-ui";
import { usePermissions } from "@/lib/use-permissions";
import { useAuthSession } from "@/lib/use-auth-session";

const DOCUMENT_PAGE_SIZE = 200;
const CHAT_SESSION_PAGE_SIZE = 200;
const LATEST_DOCUMENTS_PAGE_SIZE = 5;
const RECENT_ACTIVITY_PAGE_SIZE = 5;
const RECENT_ACTIVITY_FETCH_LIMIT = 50;
const AUDIT_ACTIVITY_FETCH_LIMIT = 50;

type DashboardDocumentSummary = {
  totalDocuments: number;
  indexedDocuments: number;
  totalChunks: number;
  chunksEstimated: boolean;
};

type DashboardChatSummary = {
  totalSessions: number;
  questionsAsked: number;
};

type DashboardRecentActivityItem = {
  id: string;
  category:
    | "upload"
    | "processing"
    | "chat"
    | "evaluation"
    | "failure"
    | "admin"
    | "document";
  title: string;
  description: string;
  timestamp: string;
  href: string | null;
};

type DashboardAuditActivityBundle = {
  items: AuditLogListItemResponse[];
  unavailableReason: string | null;
};

function BillingStatusBanner() {
  const t = useTranslations("dashboard.billing");
  const { hasPermission } = usePermissions();
  const canViewBilling =
    hasPermission("billing:view") || hasPermission("billing:manage");
  const capabilities = useMemo(() => getBillingCapabilities(), []);

  const planQuery = useQuery({
    queryKey: ["billing", "dashboard", "plan"],
    queryFn: getBillingPlanInfo,
    enabled: canViewBilling && capabilities.planEnabled,
    retry: false,
  });

  if (!canViewBilling || !capabilities.planEnabled || !planQuery.data) {
    return null;
  }

  const statusCopy: Record<
    BillingPlanStatus,
    { tone: string; title: string; body: string }
  > = {
    active: {
      tone: "border-emerald-200 bg-emerald-50 text-emerald-900",
      title: t("active"),
      body: t("activeDescription"),
    },
    trialing: {
      tone: "border-sky-200 bg-sky-50 text-sky-900",
      title: t("trialing"),
      body: planQuery.data.trial_end_date
        ? t("trialingDescription", {
            date: new Date(
              planQuery.data.trial_end_date,
            ).toLocaleDateString(),
          })
        : t("trialingDescriptionAlt"),
    },
    past_due: {
      tone: "border-amber-200 bg-amber-50 text-amber-900",
      title: t("pastDue"),
      body: t("pastDueDescription"),
    },
    cancelled: {
      tone: "border-rose-200 bg-rose-50 text-rose-900",
      title: t("cancelled"),
      body: t("cancelledDescription"),
    },
    free: {
      tone: "border-slate-200 bg-slate-50 text-slate-900",
      title: t("free"),
      body: t("freeDescription"),
    },
    self_hosted: {
      tone: "border-slate-200 bg-slate-50 text-slate-900",
      title: t("selfHosted"),
      body: t("selfHostedDescription"),
    },
    unknown: {
      tone: "border-slate-200 bg-slate-50 text-slate-900",
      title: t("unknown"),
      body: t("unknownDescription"),
    },
  };

  const copy = statusCopy[planQuery.data.status];
  if (planQuery.data.status === "active") {
    return null;
  }

  return (
    <aside className={`rounded-2xl border px-4 py-3 ${copy.tone}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{copy.title}</p>
          <p className="mt-0.5 text-xs opacity-90">{copy.body}</p>
        </div>
        <Link
          href="/settings?tab=billing"
          className="shrink-0 rounded-lg border border-current/20 px-3 py-1.5 text-xs font-semibold hover:bg-white/40"
        >
          {t("openBilling")}
        </Link>
      </div>
    </aside>
  );
}

function parsePositiveIntegerEnv(
  value: string | undefined,
  fallback: number,
): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }

  return parsed;
}

function isTruthyEnv(value: string | undefined): boolean {
  if (!value) {
    return false;
  }

  const normalized = value.trim().toLowerCase();
  return (
    normalized === "1" ||
    normalized === "true" ||
    normalized === "yes" ||
    normalized === "on"
  );
}

async function fetchDashboardDocumentsSummary(): Promise<DashboardDocumentSummary> {
  const maxDocumentRows = parsePositiveIntegerEnv(
    process.env.NEXT_PUBLIC_DASHBOARD_MAX_DOCUMENT_ROWS,
    1_000,
  );

  let offset = 0;
  let fetchedRows = 0;
  let totalDocuments = 0;
  let totalChunks = 0;

  while (fetchedRows < maxDocumentRows) {
    const pageLimit = Math.min(
      DOCUMENT_PAGE_SIZE,
      maxDocumentRows - fetchedRows,
    );
    const page = await listDocuments({
      limit: pageLimit,
      offset,
      sort_by: "updated_at",
      sort_order: "desc",
    });

    if (offset === 0) {
      totalDocuments = page.total;
    }

    if (page.items.length === 0) {
      break;
    }

    totalChunks += page.items.reduce(
      (sum, item) => sum + Math.max(0, item.chunk_count),
      0,
    );
    fetchedRows += page.items.length;
    offset += page.items.length;

    if (fetchedRows >= totalDocuments) {
      break;
    }
  }

  let indexedDocuments = 0;
  if (totalDocuments > 0) {
    const indexedPage = await listDocuments({
      status: "indexed",
      limit: 1,
      offset: 0,
    });
    indexedDocuments = indexedPage.total;
  }

  return {
    totalDocuments,
    indexedDocuments,
    totalChunks,
    chunksEstimated: fetchedRows < totalDocuments,
  };
}

async function fetchDashboardChatSummary(): Promise<DashboardChatSummary> {
  const maxSessionRows = parsePositiveIntegerEnv(
    process.env.NEXT_PUBLIC_DASHBOARD_MAX_CHAT_SESSION_ROWS,
    1_000,
  );

  let offset = 0;
  let fetchedRows = 0;
  let totalSessions = 0;
  const sessions: ChatSessionResponse[] = [];

  while (fetchedRows < maxSessionRows) {
    const pageLimit = Math.min(
      CHAT_SESSION_PAGE_SIZE,
      maxSessionRows - fetchedRows,
    );
    const page = await listChatSessions({
      limit: pageLimit,
      offset,
    });

    if (offset === 0) {
      totalSessions = page.total;
    }

    if (page.items.length === 0) {
      break;
    }

    sessions.push(...page.items);
    fetchedRows += page.items.length;
    offset += page.items.length;

    if (fetchedRows >= totalSessions) {
      break;
    }
  }

  return {
    totalSessions,
    questionsAsked: estimateQuestionsAsked(sessions),
  };
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function safeTimestamp(value: string): number {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return parsed;
}

function resolveAuditActivityLink(
  item: AuditLogListItemResponse,
): string | null {
  const resourceType = item.resource_type.toLowerCase();
  if (resourceType === "document" && item.resource_id) {
    return `/documents?document_id=${encodeURIComponent(item.resource_id)}`;
  }
  if (resourceType === "chat_session" && item.resource_id) {
    return `/chat?session_id=${encodeURIComponent(item.resource_id)}`;
  }
  if (resourceType.includes("evaluation")) {
    return "/evaluations";
  }
  if (resourceType.includes("pipeline")) {
    return "/rag-pipeline";
  }
  return null;
}

type DocumentActivityLabels = {
  uploaded: string;
  processing: string;
  failed: string;
  updated: string;
};

function buildDocumentActivityItems(
  documents: DocumentListItemResponse[],
  labels: DocumentActivityLabels,
): DashboardRecentActivityItem[] {
  return documents.map((document) => {
    if (document.status === "uploaded") {
      return {
        id: `doc-upload:${document.document_id}`,
        category: "upload" as const,
        title: labels.uploaded,
        description: document.filename,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    if (document.status === "processing") {
      return {
        id: `doc-processing:${document.document_id}`,
        category: "processing" as const,
        title: labels.processing,
        description: document.filename,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    if (document.status === "failed") {
      return {
        id: `doc-failure:${document.document_id}`,
        category: "failure" as const,
        title: labels.failed,
        description: `${document.filename}${document.error_message ? ` — ${document.error_message}` : ""}`,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    return {
      id: `doc-updated:${document.document_id}`,
      category: "document" as const,
      title: labels.updated,
      description: document.filename,
      timestamp: document.updated_at,
      href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
    };
  });
}

type ChatActivityLabels = {
  title: string;
  messages: string;
  untitledSession: string;
};

function buildChatActivityItems(
  sessions: ChatSessionResponse[],
  labels: ChatActivityLabels,
): DashboardRecentActivityItem[] {
  return sessions
    .filter((session) => session.message_count > 0)
    .map((session) => ({
      id: `chat:${session.session_id}`,
      category: "chat" as const,
      title: labels.title,
      description: `${session.message_count} ${labels.messages} in ${session.title ?? labels.untitledSession}`,
      timestamp: session.updated_at,
      href: `/chat?session_id=${encodeURIComponent(session.session_id)}`,
    }));
}

function buildAuditActivityItems(
  items: AuditLogListItemResponse[],
): DashboardRecentActivityItem[] {
  return items.map((item) => {
    const action = item.action.toLowerCase();
    let category: DashboardRecentActivityItem["category"] = "admin";

    if (action.includes("evaluation")) {
      category = "evaluation";
    } else if (action.includes("failed") || action.includes("error")) {
      category = "failure";
    }

    return {
      id: `audit:${item.audit_log_id}`,
      category,
      title: item.action,
      description: `${item.resource_type}${item.resource_id ? `:${item.resource_id}` : ""}`,
      timestamp: item.created_at,
      href: resolveAuditActivityLink(item),
    };
  });
}

function sortActivities(
  items: DashboardRecentActivityItem[],
): DashboardRecentActivityItem[] {
  return items.sort(
    (left, right) =>
      safeTimestamp(right.timestamp) - safeTimestamp(left.timestamp),
  );
}

function activityVisual(category: DashboardRecentActivityItem["category"]): {
  icon: string;
  toneClass: string;
} {
  if (category === "upload") {
    return {
      icon: "upload_file",
      toneClass: "bg-emerald-100 text-emerald-700",
    };
  }
  if (category === "processing") {
    return {
      icon: "sync",
      toneClass: "bg-sky-100 text-sky-700",
    };
  }
  if (category === "chat") {
    return {
      icon: "forum",
      toneClass: "bg-indigo-100 text-indigo-700",
    };
  }
  if (category === "evaluation") {
    return {
      icon: "fact_check",
      toneClass: "bg-violet-100 text-violet-700",
    };
  }
  if (category === "failure") {
    return {
      icon: "error",
      toneClass: "bg-rose-100 text-rose-700",
    };
  }
  if (category === "admin") {
    return {
      icon: "admin_panel_settings",
      toneClass: "bg-slate-100 text-slate-700",
    };
  }
  return {
    icon: "description",
    toneClass: "bg-purple-100 text-purple-700",
  };
}

function documentStatusBadgeClass(status: DocumentStatus): string {
  if (status === "indexed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-bold tracking-wide text-emerald-800 uppercase";
  }
  if (status === "processing") {
    return "rounded-full bg-blue-100 px-2 py-1 text-[10px] font-bold tracking-wide text-blue-800 uppercase";
  }
  if (status === "uploaded") {
    return "rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold tracking-wide text-amber-800 uppercase";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-[10px] font-bold tracking-wide text-rose-800 uppercase";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-[10px] font-bold tracking-wide text-slate-700 uppercase";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold tracking-wide text-slate-600 uppercase";
}

type MaterialIconProps = {
  name: string;
  className?: string;
  filled?: boolean;
};

function MaterialIcon({ name, className, filled = false }: MaterialIconProps) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined ${className ?? ""}`.trim()}
      style={
        filled
          ? {
              fontVariationSettings: "'FILL' 1",
            }
          : undefined
      }
    >
      {name}
    </span>
  );
}

type DashboardKpiCardProps = {
  title: string;
  value: string;
  caption: string;
  icon: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

function DashboardKpiCard({
  title,
  value,
  caption,
  icon,
  loading = false,
  error = null,
  onRetry,
}: DashboardKpiCardProps) {
  const tCommon = useTranslations("common");
  const tKpi = useTranslations("dashboard.kpi");
  return (
    <article className="flex h-full flex-col justify-between rounded-xl border border-[#d8d5e8] bg-white p-4 shadow-sm">
      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-[#6d6986] uppercase">
            {title}
          </p>
          <MaterialIcon name={icon} className="text-[20px] text-[#5b4bcb]" />
        </div>
        {loading ? (
          <p className="text-3xl font-black text-[#2d2a44]">
            {tCommon("loading")}
          </p>
        ) : error ? (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-rose-700">
              {tKpi("unableToLoad")}
            </p>
            <p className="text-xs text-rose-700">{error}</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
              >
                {tCommon("retry")}
              </button>
            ) : null}
          </div>
        ) : (
          <p className="text-3xl font-black text-[#2d2a44]">{value}</p>
        )}
      </div>
      <p className="mt-3 text-xs text-[#64617a]">{caption}</p>
    </article>
  );
}

type DashboardPaginationProps = {
  offset: number;
  pageSize: number;
  total: number;
  visibleCount: number;
  itemLabel: string;
  onPrevious: () => void;
  onNext: () => void;
};

function DashboardPagination({
  offset,
  pageSize,
  total,
  visibleCount,
  itemLabel,
  onPrevious,
  onNext,
}: DashboardPaginationProps) {
  const tCommon = useTranslations("common");
  const tPagination = useTranslations("dashboard.pagination");

  if (total <= pageSize) {
    return null;
  }

  const canGoPrevious = offset > 0;
  const canGoNext = offset + visibleCount < total;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex items-center justify-between gap-2 border-t border-[#e0ddef] bg-[#f8f6ff] px-3 py-2">
      <button
        type="button"
        disabled={!canGoPrevious}
        onClick={onPrevious}
        className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold text-[#5e5a77] transition hover:bg-[#ece8fb] hover:text-[#3d3770] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <MaterialIcon name="chevron_left" className="text-[18px]" />
        {tCommon("previous")}
      </button>
      <div className="text-center">
        <p className="text-[10px] font-semibold tracking-wide text-[#6f6a86] uppercase">
          {tPagination("page", { current: currentPage, total: totalPages })}
        </p>
        <p className="text-[11px] text-[#6f6a86]">
          {tPagination("showing", {
            from: offset + 1,
            to: offset + visibleCount,
            count: total,
            label: itemLabel,
          })}
        </p>
      </div>
      <button
        type="button"
        disabled={!canGoNext}
        onClick={onNext}
        className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold text-[#5e5a77] transition hover:bg-[#ece8fb] hover:text-[#3d3770] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {tCommon("next")}
        <MaterialIcon name="chevron_right" className="text-[18px]" />
      </button>
    </div>
  );
}

function TrendBar({ label, value }: { label: string; value: number | null }) {
  const percentage = value === null ? null : Math.max(0, Math.min(100, value));

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold tracking-wide text-[#6d6986] uppercase">
          {label}
        </p>
        <p className="text-xs font-semibold text-[#2f2b47]">
          {percentage === null ? "N/A" : `${Math.round(percentage)}%`}
        </p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[#ece9f9]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-[#6152d7] to-[#3e2cc9]"
          style={{ width: `${percentage ?? 0}%` }}
        />
      </div>
    </div>
  );
}

function QuickActionLink({
  href,
  icon,
  label,
  primary = false,
}: {
  href: string;
  icon: string;
  label: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={
        primary
          ? "inline-flex items-center gap-2 rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2d1fb1]"
          : "inline-flex items-center gap-2 rounded-lg border border-[#d3d0e5] bg-white px-4 py-2 text-sm font-semibold text-[#3a3569] transition hover:bg-[#f4f1ff]"
      }
    >
      <MaterialIcon name={icon} className="text-[18px]" />
      {label}
    </Link>
  );
}

function DisabledQuickAction({ icon, label }: { icon: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-lg border border-[#d8d5e8] bg-[#f7f6fc] px-4 py-2 text-sm font-semibold text-[#87839d]">
      <MaterialIcon name={icon} className="text-[18px]" />
      {label}
    </span>
  );
}

export function DashboardPage() {
  const t = useTranslations("dashboard");
  const tAppShell = useTranslations("appShell");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const adminUsageEnabled = isTruthyEnv(
    process.env.NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE,
  );
  const showAdminUsage = canViewAdminUsage(role) && adminUsageEnabled;
  const documentCapabilities = resolveDocumentCapabilities(role);

  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const [latestDocumentsOffset, setLatestDocumentsOffset] = useState(0);
  const [recentActivityOffset, setRecentActivityOffset] = useState(0);

  const usageRange = useMemo(
    () => resolveUsageDateRange(rangePreset),
    [rangePreset],
  );

  const documentsQuery = useQuery({
    queryKey: ["dashboard", "documents-summary"],
    queryFn: fetchDashboardDocumentsSummary,
  });

  const chatSummaryQuery = useQuery({
    queryKey: ["dashboard", "chat-summary"],
    queryFn: fetchDashboardChatSummary,
  });

  const usageQuery = useQuery({
    queryKey: queryKeys.admin.usage({
      from: usageRange.from,
      to: usageRange.to,
      granularity: "day",
    }),
    queryFn: () =>
      getUsageSummary({
        from: usageRange.from,
        to: usageRange.to,
        granularity: "day",
      }),
    enabled: showAdminUsage,
  });

  const latestDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      limit: LATEST_DOCUMENTS_PAGE_SIZE,
      offset: latestDocumentsOffset,
      sort_by: "updated_at",
      sort_order: "desc",
      scope: "dashboard-latest",
    }),
    queryFn: () =>
      listDocuments({
        limit: LATEST_DOCUMENTS_PAGE_SIZE,
        offset: latestDocumentsOffset,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const activityDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      limit: RECENT_ACTIVITY_FETCH_LIMIT,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
      scope: "dashboard-activity",
    }),
    queryFn: () =>
      listDocuments({
        limit: RECENT_ACTIVITY_FETCH_LIMIT,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const recentChatSessionsQuery = useQuery({
    queryKey: [
      "dashboard",
      "recent-chat-sessions",
      { limit: RECENT_ACTIVITY_FETCH_LIMIT },
    ],
    queryFn: () =>
      listChatSessions({
        limit: RECENT_ACTIVITY_FETCH_LIMIT,
        offset: 0,
      }),
  });

  const auditActivityQuery = useQuery({
    queryKey: queryKeys.admin.auditLogs({
      from: usageRange.from,
      to: usageRange.to,
      limit: AUDIT_ACTIVITY_FETCH_LIMIT,
      offset: 0,
    }),
    queryFn: () =>
      listAuditLogs({
        from: usageRange.from,
        to: usageRange.to,
        limit: AUDIT_ACTIVITY_FETCH_LIMIT,
        offset: 0,
      }),
    enabled: showAdminUsage,
  });

  const documentsSummary = documentsQuery.data;
  const chatSummary = chatSummaryQuery.data;
  const usageSummary = usageQuery.data;

  const latestDocuments = useMemo(
    () => latestDocumentsQuery.data?.items ?? [],
    [latestDocumentsQuery.data?.items],
  );
  const activityDocuments = useMemo(
    () => activityDocumentsQuery.data?.items ?? [],
    [activityDocumentsQuery.data?.items],
  );
  const recentSessions = useMemo(
    () => recentChatSessionsQuery.data?.items ?? [],
    [recentChatSessionsQuery.data?.items],
  );

  const indexingSuccess = documentsSummary
    ? computeIndexingSuccess(
        documentsSummary.totalDocuments,
        documentsSummary.indexedDocuments,
      )
    : null;

  const questionsAsked =
    usageSummary?.totals.event_count ??
    (chatSummary ? chatSummary.questionsAsked : null);
  const averageConfidence = usageSummary
    ? extractAverageConfidence(usageSummary)
    : null;
  const averageLatencyMs = usageSummary
    ? extractAverageLatencyMs(usageSummary)
    : null;
  const estimatedCost = usageSummary?.totals.cost_usd ?? null;

  const latencyScore = usageSummary ? extractLatencyScore(usageSummary) : null;

  const showEmptyState =
    !documentsQuery.isLoading &&
    !documentsQuery.isError &&
    !chatSummaryQuery.isLoading &&
    !chatSummaryQuery.isError &&
    (documentsSummary?.totalDocuments ?? 0) === 0 &&
    (chatSummary?.questionsAsked ?? 0) === 0;

  const auditActivityBundle: DashboardAuditActivityBundle = (() => {
    if (!showAdminUsage) {
      return {
        items: [],
        unavailableReason: t("activity.adminOnly"),
      };
    }
    if (auditActivityQuery.isError) {
      return {
        items: [],
        unavailableReason: getApiErrorMessage(auditActivityQuery.error),
      };
    }
    return {
      items: auditActivityQuery.data?.items ?? [],
      unavailableReason: null,
    };
  })();

  const recentActivityItems = useMemo(
    () =>
      sortActivities([
        ...buildDocumentActivityItems(activityDocuments, {
          uploaded: t("activity.documentUploaded"),
          processing: t("activity.documentProcessing"),
          failed: t("activity.documentFailed"),
          updated: t("activity.documentUpdated"),
        }),
        ...buildChatActivityItems(recentSessions, {
          title: t("activity.chatQuestions"),
          messages: tAppShell("messages"),
          untitledSession: tAppShell("untitledSession"),
        }),
        ...buildAuditActivityItems(auditActivityBundle.items),
      ]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activityDocuments, recentSessions, auditActivityBundle.items],
  );

  const paginatedRecentActivityItems = useMemo(
    () =>
      recentActivityItems.slice(
        recentActivityOffset,
        recentActivityOffset + RECENT_ACTIVITY_PAGE_SIZE,
      ),
    [recentActivityItems, recentActivityOffset],
  );

  const recentActivityLoading =
    activityDocumentsQuery.isLoading ||
    recentChatSessionsQuery.isLoading ||
    (showAdminUsage && auditActivityQuery.isLoading);

  const recentActivityError = activityDocumentsQuery.isError
    ? getApiErrorMessage(activityDocumentsQuery.error)
    : recentChatSessionsQuery.isError
      ? getApiErrorMessage(recentChatSessionsQuery.error)
      : null;

  const viewDocumentHref =
    latestDocuments.length > 0
      ? `/documents?document_id=${encodeURIComponent(latestDocuments[0].document_id)}`
      : null;

  const tokenUsageRatio = useMemo(() => {
    if (!usageSummary) {
      return null;
    }

    const inputTokens = Math.max(0, usageSummary.totals.input_tokens ?? 0);
    const outputTokens = Math.max(0, usageSummary.totals.output_tokens ?? 0);
    const totalTokens = inputTokens + outputTokens;
    if (totalTokens <= 0) {
      return null;
    }

    return Math.round((inputTokens / totalTokens) * 100);
  }, [usageSummary]);

  type InstanceStatusKey = "healthy" | "checking" | "degraded";
  const apiInstanceStatusKey: InstanceStatusKey =
    documentsQuery.isError || chatSummaryQuery.isError
      ? "degraded"
      : documentsQuery.isLoading || chatSummaryQuery.isLoading
        ? "checking"
        : "healthy";
  const apiInstanceStatus = t(`instances.${apiInstanceStatusKey}`);

  const processingDocumentCount = activityDocuments.filter(
    (item) => item.status === "processing",
  ).length;
  const isIngestionIdle = processingDocumentCount === 0;
  const ingestionStatus = isIngestionIdle
    ? t("instances.idle")
    : `${processingDocumentCount} ${t("instances.running")}`;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <section className="rounded-2xl border border-[#d8d5e8] bg-white p-4 shadow-sm lg:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-semibold tracking-[0.14em] text-[#5e57ad] uppercase">
              {t("enterpriseRag")}
            </p>
            <h2 className="text-2xl font-black text-[#2d2a44]">
              {t("commandCenter")}
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-[#67637d]">
              {t("commandCenterDescription")}
            </p>
          </div>

          {showAdminUsage ? (
            <label className="grid gap-1 text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
              {t("usageRange")}
              <select
                value={rangePreset}
                onChange={(event) =>
                  setRangePreset(event.target.value as DashboardRangePreset)
                }
                className="h-9 min-w-[160px] rounded-lg border border-[#d3d0e6] bg-white px-2 text-sm font-semibold text-[#2f2b47]"
              >
                {DASHBOARD_RANGE_PRESETS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(`rangePresets.${option.value}`)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        <div className="mt-4">
          <BillingStatusBanner />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {documentCapabilities.canUpload ? (
            <QuickActionLink
              href="/documents"
              icon="upload_file"
              label={t("uploadDocument")}
              primary
            />
          ) : (
            <DisabledQuickAction
              icon="upload_file"
              label={t("uploadDocument")}
            />
          )}
          <QuickActionLink href="/chat" icon="chat" label={t("newChat")} />
          {viewDocumentHref ? (
            <QuickActionLink
              href={viewDocumentHref}
              icon="visibility"
              label={t("viewDocument")}
            />
          ) : (
            <DisabledQuickAction icon="visibility" label={t("viewDocument")} />
          )}
          <QuickActionLink
            href="/evaluations"
            icon="play_circle"
            label={t("evaluationRun")}
          />
          <QuickActionLink
            href="/rag-pipeline"
            icon="account_tree"
            label={t("pipelineExplorer")}
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DashboardKpiCard
          title={t("kpi.totalDocuments")}
          value={formatInteger(documentsSummary?.totalDocuments)}
          caption={t("kpi.totalDocumentsDescription")}
          icon="description"
          loading={documentsQuery.isLoading}
          error={
            documentsQuery.isError
              ? getApiErrorMessage(documentsQuery.error)
              : null
          }
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
        <DashboardKpiCard
          title={t("kpi.indexedDocuments")}
          value={formatInteger(documentsSummary?.indexedDocuments)}
          caption={t("kpi.indexedDocumentsDescription")}
          icon="task_alt"
          loading={documentsQuery.isLoading}
          error={
            documentsQuery.isError
              ? getApiErrorMessage(documentsQuery.error)
              : null
          }
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
        <DashboardKpiCard
          title={t("kpi.totalChunks")}
          value={
            documentsSummary
              ? `${formatInteger(documentsSummary.totalChunks)}${documentsSummary.chunksEstimated ? "+" : ""}`
              : "N/A"
          }
          caption={
            documentsSummary?.chunksEstimated
              ? t("kpi.totalChunksNote")
              : t("kpi.totalChunksDescription")
          }
          icon="layers"
          loading={documentsQuery.isLoading}
          error={
            documentsQuery.isError
              ? getApiErrorMessage(documentsQuery.error)
              : null
          }
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
        <DashboardKpiCard
          title={t("kpi.questionsAsked")}
          value={formatInteger(questionsAsked)}
          caption={t("kpi.questionsAskedNote")}
          icon="quiz"
          loading={
            chatSummaryQuery.isLoading ||
            (showAdminUsage && usageQuery.isLoading)
          }
          error={
            chatSummaryQuery.isError
              ? getApiErrorMessage(chatSummaryQuery.error)
              : showAdminUsage && usageQuery.isError
                ? getApiErrorMessage(usageQuery.error)
                : null
          }
          onRetry={() => {
            if (showAdminUsage) {
              void usageQuery.refetch();
            } else {
              void chatSummaryQuery.refetch();
            }
          }}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <article className="overflow-hidden rounded-2xl border border-[#d8d5e8] bg-white shadow-sm lg:col-span-9">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#ebe8f7] px-5 py-4">
            <div>
              <h3 className="text-xl font-bold text-[#2d2a44]">
                {t("performance.title")}
              </h3>
              <p className="text-sm text-[#69657f]">
                {t("performance.description")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-[#f2effe] px-2 py-1 text-[10px] font-semibold tracking-wide text-[#5649bf] uppercase">
                <span className="h-2 w-2 rounded-full bg-[#4f46e5]" />
                {t("performance.quality")}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-[#f4f3fb] px-2 py-1 text-[10px] font-semibold tracking-wide text-[#5f5b74] uppercase">
                <span className="h-2 w-2 rounded-full bg-[#6e687f]" />
                {t("performance.efficiency")}
              </span>
            </div>
          </div>

          <div className="grid gap-4 p-5 md:grid-cols-[2fr_1fr]">
            <div className="rounded-xl border border-[#e3dff1] bg-[#fbfaff] p-4">
              {showAdminUsage && usageQuery.isLoading ? (
                <LoadingState
                  compact
                  className="rounded-lg border border-[#e3dff1] bg-white px-3 py-2 text-sm text-[#64617a]"
                  title={t("performance.loading")}
                />
              ) : null}
              {showAdminUsage && usageQuery.isError ? (
                <ErrorState
                  compact
                  description={getApiErrorMessage(usageQuery.error)}
                  onRetry={() => {
                    void usageQuery.refetch();
                  }}
                />
              ) : null}
              {!showAdminUsage || usageQuery.isSuccess ? (
                <div className="space-y-4">
                  <TrendBar
                    label={t("performance.averageConfidence")}
                    value={
                      averageConfidence == null ? null : averageConfidence * 100
                    }
                  />
                  <TrendBar
                    label={t("performance.indexingSuccess")}
                    value={
                      indexingSuccess == null ? null : indexingSuccess * 100
                    }
                  />
                  <TrendBar
                    label={t("performance.latencyScore")}
                    value={latencyScore}
                  />
                </div>
              ) : null}
            </div>

            <div className="space-y-4 border-t border-[#ebe8f7] pt-4 md:border-t-0 md:border-l md:border-[#ebe8f7] md:pt-0 md:pl-4">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.1em] text-[#6d6986] uppercase">
                  {t("performance.averageConfidence")}
                </p>
                <p className="mt-1 text-3xl font-black text-[#4d44e3]">
                  {formatPercentage(averageConfidence)}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-semibold tracking-[0.1em] text-[#6d6986] uppercase">
                  {t("performance.averageLatency")}
                </p>
                <p className="mt-1 text-3xl font-black text-[#2f2b47]">
                  {formatLatencyMs(averageLatencyMs)}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-semibold tracking-[0.1em] text-[#6d6986] uppercase">
                  {t("performance.indexingSuccess")}
                </p>
                <p className="mt-1 text-3xl font-black text-[#2f2b47]">
                  {formatPercentage(indexingSuccess)}
                </p>
              </div>
            </div>
          </div>
        </article>

        <div className="space-y-4 lg:col-span-3">
          <article className="relative overflow-hidden rounded-2xl bg-[#3525cd] p-5 text-white shadow-lg shadow-[#4d44e3]/25">
            <p className="text-[11px] font-semibold tracking-[0.12em] text-[#dad7ff] uppercase">
              {t("tokenCost.title")}
            </p>
            {showAdminUsage ? (
              <p className="mt-1 text-[10px] font-semibold tracking-[0.12em] text-[#c7c2ff] uppercase">
                {t("tokenCost.estimatedCost")}
              </p>
            ) : null}
            <p className="mt-2 text-4xl font-black">
              {formatUsd(estimatedCost)}
            </p>
            <p className="mt-1 text-sm text-[#dad7ff]">
              {showAdminUsage
                ? t("tokenCost.window", {
                    from: usageRange.from,
                    to: usageRange.to,
                  })
                : t("tokenCost.enableMetrics")}
            </p>

            <div className="mt-4 space-y-2">
              <div className="flex items-center justify-between gap-2 text-[11px] font-semibold tracking-wide uppercase">
                <span>{t("tokenCost.inputTokenShare")}</span>
                <span>
                  {tokenUsageRatio == null ? "N/A" : `${tokenUsageRatio}%`}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/20">
                <div
                  className="h-full rounded-full bg-white"
                  style={{ width: `${tokenUsageRatio ?? 0}%` }}
                />
              </div>
            </div>

            <MaterialIcon
              name="payments"
              className="absolute -right-3 -bottom-4 text-[96px] text-white/15"
            />
          </article>

          <article className="rounded-2xl border border-[#d8d5e8] bg-white p-4 shadow-sm">
            <h4 className="text-sm font-bold text-[#2f2b47]">
              {t("instances.title")}
            </h4>
            <div className="mt-3 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      apiInstanceStatusKey === "healthy"
                        ? "bg-emerald-500"
                        : apiInstanceStatusKey === "checking"
                          ? "bg-amber-500"
                          : "bg-rose-500"
                    }`}
                  />
                  <span className="text-sm text-[#3b3760]">
                    {t("instances.rudixApi")}
                  </span>
                </div>
                <span className="font-mono text-xs text-[#68647d]">
                  {apiInstanceStatus}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      isIngestionIdle ? "bg-emerald-500" : "bg-sky-500"
                    }`}
                  />
                  <span className="text-sm text-[#3b3760]">
                    {t("instances.ingestionJobs")}
                  </span>
                </div>
                <span className="font-mono text-xs text-[#68647d]">
                  {ingestionStatus}
                </span>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-10">
        <article className="flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-[#d8d5e8] bg-white shadow-sm lg:col-span-6">
          <div className="flex items-center justify-between gap-2 border-b border-[#ebe8f7] px-5 py-4">
            <h3 className="text-xl font-bold text-[#2d2a44]">
              {t("recentActivity")}
            </h3>
            <span className="text-[11px] font-semibold tracking-[0.12em] text-[#6d6986] uppercase">
              {t("activity.timeline")}
            </span>
          </div>

          <div className="hide-scrollbar flex-1 overflow-y-auto px-5 py-4">
            {recentActivityLoading ? (
              <LoadingState
                compact
                className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
                title={t("activity.loading")}
              />
            ) : null}
            {recentActivityError ? (
              <ErrorState
                compact
                description={recentActivityError}
                onRetry={() => {
                  void activityDocumentsQuery.refetch();
                  void recentChatSessionsQuery.refetch();
                  if (showAdminUsage) {
                    void auditActivityQuery.refetch();
                  }
                }}
              />
            ) : null}
            {!recentActivityLoading &&
            !recentActivityError &&
            recentActivityItems.length === 0 ? (
              <EmptyState
                compact
                className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
                title={t("activity.noActivity")}
              />
            ) : null}
            {!recentActivityLoading &&
            !recentActivityError &&
            recentActivityItems.length > 0 ? (
              <ul className="space-y-3">
                {paginatedRecentActivityItems.map((item) => {
                  const visual = activityVisual(item.category);
                  return (
                    <li
                      key={item.id}
                      className="flex gap-3 rounded-lg border border-[#e7e4f4] bg-[#fcfbff] p-3"
                    >
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${visual.toneClass}`}
                      >
                        <MaterialIcon
                          name={visual.icon}
                          className="text-[20px]"
                          filled
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm font-bold text-[#2f2a46]">
                            {item.title}
                          </p>
                          <p className="text-[11px] text-[#6d6985]">
                            {formatDateTime(item.timestamp)}
                          </p>
                        </div>
                        <p className="mt-1 text-sm text-[#5f5a74]">
                          {item.description}
                        </p>
                        {item.href ? (
                          <Link
                            href={item.href}
                            className="mt-2 inline-block text-xs font-semibold text-[#3525cd] hover:underline"
                          >
                            {t("activity.open")}
                          </Link>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {!recentActivityLoading &&
            !recentActivityError &&
            auditActivityBundle.unavailableReason ? (
              <p className="mt-3 text-xs text-[#6a6780]">
                {auditActivityBundle.unavailableReason}
              </p>
            ) : null}
          </div>

          {!recentActivityLoading &&
          !recentActivityError &&
          recentActivityItems.length > 0 ? (
            <DashboardPagination
              offset={recentActivityOffset}
              pageSize={RECENT_ACTIVITY_PAGE_SIZE}
              total={recentActivityItems.length}
              visibleCount={paginatedRecentActivityItems.length}
              itemLabel={t("activity.events")}
              onPrevious={() =>
                setRecentActivityOffset((current) =>
                  Math.max(0, current - RECENT_ACTIVITY_PAGE_SIZE),
                )
              }
              onNext={() =>
                setRecentActivityOffset(
                  (current) => current + RECENT_ACTIVITY_PAGE_SIZE,
                )
              }
            />
          ) : null}
        </article>

        <article className="flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-[#d8d5e8] bg-white shadow-sm lg:col-span-4">
          <div className="flex items-center justify-between gap-2 border-b border-[#ebe8f7] px-5 py-4">
            <h3 className="text-xl font-bold text-[#2d2a44]">
              {t("latestDocuments.title")}
            </h3>
            <Link
              href="/documents"
              className="rounded p-1 text-[#6d6986] transition hover:bg-[#f1eefc] hover:text-[#3525cd]"
              aria-label={t("latestDocuments.title")}
            >
              <MaterialIcon name="filter_list" className="text-[20px]" />
            </Link>
          </div>

          {latestDocumentsQuery.isLoading ? (
            <div className="px-5 py-4">
              <LoadingState
                compact
                className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
                title={t("latestDocuments.loading")}
              />
            </div>
          ) : null}

          {latestDocumentsQuery.isError ? (
            <div className="px-5 py-4">
              <ErrorState
                compact
                error={latestDocumentsQuery.error}
                description={getApiErrorMessage(latestDocumentsQuery.error)}
                onRetry={() => {
                  void latestDocumentsQuery.refetch();
                }}
              />
            </div>
          ) : null}

          {latestDocumentsQuery.isSuccess && latestDocuments.length === 0 ? (
            <div className="px-5 py-4">
              <EmptyState
                compact
                className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
                title={t("latestDocuments.noDocuments")}
              />
            </div>
          ) : null}

          {latestDocumentsQuery.isSuccess && latestDocuments.length > 0 ? (
            <div className="flex flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="min-w-full divide-y divide-[#ebe8f7]">
                  <thead className="bg-[#f7f5ff]">
                    <tr className="text-left text-[11px] font-semibold tracking-wide text-[#6d6986] uppercase">
                      <th className="px-4 py-2">
                        {t("latestDocuments.filename")}
                      </th>
                      <th className="px-4 py-2">
                        {t("latestDocuments.status")}
                      </th>
                      <th className="w-[1%] px-4 py-2 whitespace-nowrap">
                        {t("latestDocuments.action")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f1eefa]">
                    {latestDocuments.map((document) => (
                      <tr
                        key={document.document_id}
                        className="hover:bg-[#faf9ff]"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 text-sm font-semibold text-[#2f2b47]">
                            <MaterialIcon
                              name={
                                document.file_type === "pdf"
                                  ? "picture_as_pdf"
                                  : "description"
                              }
                              className="text-[18px] text-[#5d57c4]"
                            />
                            <span className="max-w-[180px] truncate">
                              {document.filename}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={documentStatusBadgeClass(
                              document.status,
                            )}
                          >
                            {document.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Link
                            href={`/documents?document_id=${encodeURIComponent(document.document_id)}`}
                            className="inline-flex rounded border border-[#cbc5e6] px-2 py-1 text-xs font-semibold whitespace-nowrap text-[#3e376f] hover:bg-[#f5f3ff]"
                          >
                            {t("latestDocuments.viewDocument")}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <DashboardPagination
                offset={latestDocumentsOffset}
                pageSize={LATEST_DOCUMENTS_PAGE_SIZE}
                total={
                  latestDocumentsQuery.data?.total ?? latestDocuments.length
                }
                visibleCount={latestDocuments.length}
                itemLabel={t("latestDocuments.paginatorLabel")}
                onPrevious={() =>
                  setLatestDocumentsOffset((current) =>
                    Math.max(0, current - LATEST_DOCUMENTS_PAGE_SIZE),
                  )
                }
                onNext={() =>
                  setLatestDocumentsOffset(
                    (current) => current + LATEST_DOCUMENTS_PAGE_SIZE,
                  )
                }
              />

              <div className="border-t border-[#e0ddef] bg-[#f8f6ff] px-3 py-2">
                <Link
                  href="/documents"
                  className="block text-center text-sm font-semibold text-[#615b7a] transition hover:text-[#3525cd]"
                >
                  {t("manageAll", {
                    count: formatInteger(
                      latestDocumentsQuery.data?.total ?? 0,
                    ),
                  })}
                </Link>
              </div>
            </div>
          ) : null}
        </article>
      </section>

      {showEmptyState ? (
        <EmptyState
          className="rounded-2xl border border-[#d8d5e8] bg-white p-6 shadow-sm"
          title={t("emptyState.title")}
          description={t("emptyState.description")}
          action={
            <div className="flex flex-wrap justify-center gap-3">
              <Link
                href="/documents"
                className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2d1fb1]"
              >
                {t("emptyState.uploadDocuments")}
              </Link>
              <Link
                href="/chat"
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                {t("emptyState.openChat")}
              </Link>
            </div>
          }
        />
      ) : null}

      {showAdminUsage ? (
        <section className="rounded-2xl border border-[#d8d5e8] bg-white p-5 shadow-sm">
          <h3 className="text-lg font-bold text-[#2d2a44]">
            {t("usageWindow.title")}
          </h3>
          <p className="mt-2 text-sm text-[#67637d]">
            {t("usageWindow.description", {
              from: usageRange.from,
              to: usageRange.to,
            })}
          </p>
          {usageQuery.isSuccess ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricRow
                label={t("usageWindow.inputTokens")}
                value={formatInteger(usageSummary?.totals.input_tokens)}
              />
              <MetricRow
                label={t("usageWindow.outputTokens")}
                value={formatInteger(usageSummary?.totals.output_tokens)}
              />
              <MetricRow
                label={t("usageWindow.usageEvents")}
                value={formatInteger(usageSummary?.totals.event_count)}
              />
              <MetricRow
                label={t("usageWindow.seriesPoints")}
                value={formatInteger(usageSummary?.series.length ?? 0)}
              />
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
      <p className="mb-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
        {label}
      </p>
      <p className="text-base font-semibold text-[#2a2640]">{value}</p>
    </div>
  );
}
