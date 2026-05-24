"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  getUsageSummary,
  listAuditLogs,
  type AuditLogListItemResponse,
} from "@/lib/api/admin-usage";
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
  formatInteger,
  formatLatencyMs,
  formatPercentage,
  formatUsd,
  resolveUsageDateRange,
  type DashboardRangePreset,
} from "@/lib/dashboard";
import { resolveDocumentCapabilities } from "@/lib/documents-ui";
import { useAuthSession } from "@/lib/use-auth-session";

const DOCUMENT_PAGE_SIZE = 200;
const CHAT_SESSION_PAGE_SIZE = 200;
const LATEST_DOCUMENTS_PAGE_SIZE = 5;
const RECENT_ACTIVITY_PAGE_SIZE = 5;
const RECENT_ACTIVITY_FETCH_LIMIT = 50;
const AUDIT_ACTIVITY_FETCH_LIMIT = 50;

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
  const sessions = [];

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

type KpiCardProps = {
  title: string;
  value: string;
  caption: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

function KpiCard({
  title,
  value,
  caption,
  loading = false,
  error = null,
  onRetry,
}: KpiCardProps) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="mb-1 text-xs font-bold tracking-[0.16em] text-[#6f6a8d] uppercase">
        {title}
      </p>
      {loading ? (
        <p className="text-2xl font-extrabold text-[#2a2640]">Loading...</p>
      ) : error ? (
        <div>
          <p className="text-sm font-semibold text-rose-700">Unable to load</p>
          <p className="mt-1 text-xs text-rose-700">{error}</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 rounded border border-rose-300 bg-white px-2 py-1 text-xs font-semibold text-rose-800 hover:bg-rose-50"
            >
              Retry
            </button>
          ) : null}
        </div>
      ) : (
        <p className="text-2xl font-extrabold text-[#2a2640]">{value}</p>
      )}
      <p className="mt-2 text-xs text-[#6a6780]">{caption}</p>
    </article>
  );
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function getDocumentStatusBadgeClass(status: DocumentStatus): string {
  if (status === "indexed") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (status === "processing") {
    return "rounded-full bg-blue-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-blue-800";
  }
  if (status === "uploaded") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  if (status === "failed") {
    return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
  }
  if (status === "deleting") {
    return "rounded-full bg-slate-200 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-700";
  }
  return "rounded-full bg-slate-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-slate-600";
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

function buildDocumentActivityItems(
  documents: DocumentListItemResponse[],
): DashboardRecentActivityItem[] {
  return documents.map((document) => {
    if (document.status === "uploaded") {
      return {
        id: `doc-upload:${document.document_id}`,
        category: "upload" as const,
        title: "Document uploaded",
        description: document.filename,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    if (document.status === "processing") {
      return {
        id: `doc-processing:${document.document_id}`,
        category: "processing" as const,
        title: "Document processing",
        description: document.filename,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    if (document.status === "failed") {
      return {
        id: `doc-failure:${document.document_id}`,
        category: "failure" as const,
        title: "Document failed",
        description: `${document.filename}${document.error_message ? ` — ${document.error_message}` : ""}`,
        timestamp: document.updated_at,
        href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
      };
    }
    return {
      id: `doc-updated:${document.document_id}`,
      category: "document" as const,
      title: "Document updated",
      description: document.filename,
      timestamp: document.updated_at,
      href: `/documents?document_id=${encodeURIComponent(document.document_id)}`,
    };
  });
}

function buildChatActivityItems(
  sessions: ChatSessionResponse[],
): DashboardRecentActivityItem[] {
  return sessions
    .filter((session) => session.message_count > 0)
    .map((session) => ({
      id: `chat:${session.session_id}`,
      category: "chat" as const,
      title: "Chat questions",
      description: `${session.message_count} messages in ${session.title ?? "Untitled session"}`,
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
  if (total <= pageSize) {
    return null;
  }

  const canGoPrevious = offset > 0;
  const canGoNext = offset + visibleCount < total;

  return (
    <div className="mt-3 flex items-center justify-between gap-3">
      <p className="text-xs text-[#6e6a86]">
        Showing {offset + 1}-{offset + visibleCount} of {total} {itemLabel}.
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!canGoPrevious}
          onClick={onPrevious}
          className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={!canGoNext}
          onClick={onNext}
          className="rounded border border-[#cbc5e6] px-3 py-1 text-xs font-semibold text-[#3e376f] disabled:cursor-not-allowed disabled:opacity-60"
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function DashboardPage() {
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
        unavailableReason:
          "Admin activity is only available for owner/admin roles.",
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
        ...buildDocumentActivityItems(activityDocuments),
        ...buildChatActivityItems(recentSessions),
        ...buildAuditActivityItems(auditActivityBundle.items),
      ]),
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

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Dashboard
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Organization Metrics Overview
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Monitor document indexing, retrieval performance, and usage trends
              with permission-aware KPI cards.
            </p>
          </div>

          {showAdminUsage ? (
            <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
              Usage range
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
          ) : null}
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          title="Total documents"
          value={formatInteger(documentsSummary?.totalDocuments)}
          caption="Documents currently scoped to your organization."
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
        <KpiCard
          title="Indexed documents"
          value={formatInteger(documentsSummary?.indexedDocuments)}
          caption="Documents ready for retrieval and chat."
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
        <KpiCard
          title="Total chunks"
          value={
            documentsSummary
              ? `${formatInteger(documentsSummary.totalChunks)}${documentsSummary.chunksEstimated ? "+" : ""}`
              : "N/A"
          }
          caption={
            documentsSummary?.chunksEstimated
              ? "Chunk count is estimated from sampled documents."
              : "Total indexed chunks across fetched organization documents."
          }
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
        <KpiCard
          title="Questions asked"
          value={formatInteger(questionsAsked)}
          caption="Estimated from chat activity and usage events."
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
        <KpiCard
          title="Average confidence"
          value={formatPercentage(averageConfidence)}
          caption="Mean answer confidence from usage analytics, when exposed."
          loading={showAdminUsage && usageQuery.isLoading}
          error={
            showAdminUsage && usageQuery.isError
              ? getApiErrorMessage(usageQuery.error)
              : null
          }
          onRetry={() => {
            void usageQuery.refetch();
          }}
        />
        <KpiCard
          title="Average latency"
          value={formatLatencyMs(averageLatencyMs)}
          caption="Average end-to-end response latency, if reported by usage metrics."
          loading={showAdminUsage && usageQuery.isLoading}
          error={
            showAdminUsage && usageQuery.isError
              ? getApiErrorMessage(usageQuery.error)
              : null
          }
          onRetry={() => {
            void usageQuery.refetch();
          }}
        />
        <KpiCard
          title="Indexing success"
          value={formatPercentage(indexingSuccess)}
          caption="Indexed documents divided by total documents."
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
        {showAdminUsage ? (
          <KpiCard
            title="Estimated cost"
            value={formatUsd(estimatedCost)}
            caption="Aggregated LLM usage cost in the selected range."
            loading={usageQuery.isLoading}
            error={
              usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null
            }
            onRetry={() => {
              void usageQuery.refetch();
            }}
          />
        ) : null}
      </div>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Quick actions</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {documentCapabilities.canUpload ? (
            <Link
              href="/documents"
              className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
            >
              Upload document
            </Link>
          ) : (
            <span className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-500">
              Upload document
            </span>
          )}
          <Link
            href="/chat"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            New chat
          </Link>
          {viewDocumentHref ? (
            <Link
              href={viewDocumentHref}
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              View document
            </Link>
          ) : (
            <span className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-500">
              View document
            </span>
          )}
          <Link
            href="/evaluations"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Evaluation run
          </Link>
          <Link
            href="/rag-pipeline"
            className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            Pipeline explorer
          </Link>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Latest documents</h2>
          {latestDocumentsQuery.isLoading ? (
            <LoadingState
              compact
              className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
              title="Loading latest documents..."
            />
          ) : null}
          {latestDocumentsQuery.isError ? (
            <div className="mt-3">
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
            <EmptyState
              compact
              className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
              title="No documents have been uploaded yet."
            />
          ) : null}
          {latestDocumentsQuery.isSuccess && latestDocuments.length > 0 ? (
            <div className="mt-4 overflow-x-auto rounded-xl border border-[#e4e1f2]">
              <table className="min-w-full divide-y divide-[#e7e4f4] text-sm">
                <thead className="bg-[#faf9ff]">
                  <tr className="text-left text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                    <th className="px-3 py-3">Filename</th>
                    <th className="px-3 py-3">Status</th>
                    <th className="px-3 py-3">Chunks</th>
                    <th className="px-3 py-3">Updated</th>
                    <th className="w-[1%] px-3 py-3 whitespace-nowrap">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f0edf8]">
                  {latestDocuments.map((document) => (
                    <tr key={document.document_id} className="text-[#2a2640]">
                      <td className="px-3 py-3 font-semibold">
                        {document.filename}
                      </td>
                      <td className="px-3 py-3">
                        <span
                          className={getDocumentStatusBadgeClass(
                            document.status,
                          )}
                        >
                          {document.status}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        {formatInteger(document.chunk_count)}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#6a6780]">
                        {formatDateTime(document.updated_at)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Link
                          href={`/documents?document_id=${encodeURIComponent(document.document_id)}`}
                          className="inline-flex rounded border border-[#cbc5e6] px-2 py-1 text-xs font-semibold whitespace-nowrap text-[#3e376f] hover:bg-[#f5f3ff]"
                        >
                          View document
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {latestDocumentsQuery.isSuccess && latestDocuments.length > 0 ? (
            <DashboardPagination
              offset={latestDocumentsOffset}
              pageSize={LATEST_DOCUMENTS_PAGE_SIZE}
              total={latestDocumentsQuery.data?.total ?? latestDocuments.length}
              visibleCount={latestDocuments.length}
              itemLabel="documents"
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
          ) : null}
        </section>

        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Recent activity</h2>
          {recentActivityLoading ? (
            <LoadingState
              compact
              className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-sm text-[#5f5b72]"
              title="Loading recent activity..."
            />
          ) : null}
          {recentActivityError ? (
            <div className="mt-3">
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
            </div>
          ) : null}
          {!recentActivityLoading &&
          !recentActivityError &&
          recentActivityItems.length === 0 ? (
            <EmptyState
              compact
              className="mt-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2"
              title="No recent activity available yet."
            />
          ) : null}
          {!recentActivityLoading &&
          !recentActivityError &&
          recentActivityItems.length > 0 ? (
            <>
              <ul className="mt-4 space-y-2">
                {paginatedRecentActivityItems.map((item) => (
                  <li
                    key={item.id}
                    className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-3"
                  >
                    <p className="text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
                      {item.category}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-[#2f2a46]">
                      {item.title}
                    </p>
                    <p className="mt-1 text-sm text-[#5f5a74]">
                      {item.description}
                    </p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-xs text-[#6a6780]">
                        {formatDateTime(item.timestamp)}
                      </p>
                      {item.href ? (
                        <Link
                          href={item.href}
                          className="text-xs font-semibold text-[#3525cd] hover:underline"
                        >
                          Open
                        </Link>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
              <DashboardPagination
                offset={recentActivityOffset}
                pageSize={RECENT_ACTIVITY_PAGE_SIZE}
                total={recentActivityItems.length}
                visibleCount={paginatedRecentActivityItems.length}
                itemLabel="events"
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
            </>
          ) : null}
          {!recentActivityLoading &&
          !recentActivityError &&
          auditActivityBundle.unavailableReason ? (
            <p className="mt-3 text-xs text-[#6a6780]">
              {auditActivityBundle.unavailableReason}
            </p>
          ) : null}
        </section>
      </div>

      {showEmptyState ? (
        <EmptyState
          className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm"
          title="No activity yet"
          description="No documents or chat questions were found for this workspace. Upload documents or start a chat to populate dashboard metrics."
          action={
            <div className="flex flex-wrap justify-center gap-3">
              <Link
                href="/documents"
                className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
              >
                Upload documents
              </Link>
              <Link
                href="/chat"
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                Open chat
              </Link>
            </div>
          }
        />
      ) : null}

      {showAdminUsage ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Usage window</h2>
          <p className="mt-2 text-sm text-[#68647b]">
            Showing usage from{" "}
            <span className="font-semibold">{usageRange.from}</span> to{" "}
            <span className="font-semibold">{usageRange.to}</span>.
          </p>
          {usageQuery.isSuccess ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricRow
                label="Input tokens"
                value={formatInteger(usageSummary?.totals.input_tokens)}
              />
              <MetricRow
                label="Output tokens"
                value={formatInteger(usageSummary?.totals.output_tokens)}
              />
              <MetricRow
                label="Usage events"
                value={formatInteger(usageSummary?.totals.event_count)}
              />
              <MetricRow
                label="Series points"
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
