"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getUsageSummary } from "@/lib/api/admin-usage";
import { listChatSessions } from "@/lib/api/chat";
import { getApiErrorMessage } from "@/lib/api/errors";
import { listDocuments } from "@/lib/api/documents";
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
import { useAuthSession } from "@/lib/use-auth-session";

const DOCUMENT_PAGE_SIZE = 200;
const CHAT_SESSION_PAGE_SIZE = 200;

function parsePositiveIntegerEnv(value: string | undefined, fallback: number): number {
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
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
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
    const pageLimit = Math.min(DOCUMENT_PAGE_SIZE, maxDocumentRows - fetchedRows);
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

    totalChunks += page.items.reduce((sum, item) => sum + Math.max(0, item.chunk_count), 0);
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
    const pageLimit = Math.min(CHAT_SESSION_PAGE_SIZE, maxSessionRows - fetchedRows);
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

function KpiCard({ title, value, caption, loading = false, error = null, onRetry }: KpiCardProps) {
  return (
    <article className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-[#6f6a8d]">{title}</p>
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

export function DashboardPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const adminUsageEnabled = isTruthyEnv(process.env.NEXT_PUBLIC_DASHBOARD_ENABLE_ADMIN_USAGE);
  const showAdminUsage = canViewAdminUsage(role) && adminUsageEnabled;

  const [rangePreset, setRangePreset] = useState<DashboardRangePreset>("30d");
  const usageRange = useMemo(() => resolveUsageDateRange(rangePreset), [rangePreset]);

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

  const documentsSummary = documentsQuery.data;
  const chatSummary = chatSummaryQuery.data;
  const usageSummary = usageQuery.data;

  const indexingSuccess = documentsSummary
    ? computeIndexingSuccess(documentsSummary.totalDocuments, documentsSummary.indexedDocuments)
    : null;

  const questionsAsked =
    usageSummary?.totals.event_count ??
    (chatSummary ? chatSummary.questionsAsked : null);

  const averageConfidence = usageSummary ? extractAverageConfidence(usageSummary) : null;
  const averageLatencyMs = usageSummary ? extractAverageLatencyMs(usageSummary) : null;
  const estimatedCost = usageSummary?.totals.cost_usd ?? null;

  const showEmptyState =
    !documentsQuery.isLoading &&
    !documentsQuery.isError &&
    !chatSummaryQuery.isLoading &&
    !chatSummaryQuery.isError &&
    (documentsSummary?.totalDocuments ?? 0) === 0 &&
    (chatSummary?.questionsAsked ?? 0) === 0;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Dashboard</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Organization Metrics Overview
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Monitor document indexing, retrieval performance, and usage trends with permission-aware KPI cards.
            </p>
          </div>

          {showAdminUsage ? (
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Usage range
              <select
                value={rangePreset}
                onChange={(event) => setRangePreset(event.target.value as DashboardRangePreset)}
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
          error={documentsQuery.isError ? getApiErrorMessage(documentsQuery.error) : null}
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
        <KpiCard
          title="Indexed documents"
          value={formatInteger(documentsSummary?.indexedDocuments)}
          caption="Documents ready for retrieval and chat."
          loading={documentsQuery.isLoading}
          error={documentsQuery.isError ? getApiErrorMessage(documentsQuery.error) : null}
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
          error={documentsQuery.isError ? getApiErrorMessage(documentsQuery.error) : null}
          onRetry={() => {
            void documentsQuery.refetch();
          }}
        />
        <KpiCard
          title="Questions asked"
          value={formatInteger(questionsAsked)}
          caption="Estimated from chat activity and usage events."
          loading={chatSummaryQuery.isLoading || (showAdminUsage && usageQuery.isLoading)}
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
          error={showAdminUsage && usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
          onRetry={() => {
            void usageQuery.refetch();
          }}
        />
        <KpiCard
          title="Average latency"
          value={formatLatencyMs(averageLatencyMs)}
          caption="Average end-to-end response latency, if reported by usage metrics."
          loading={showAdminUsage && usageQuery.isLoading}
          error={showAdminUsage && usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
          onRetry={() => {
            void usageQuery.refetch();
          }}
        />
        <KpiCard
          title="Indexing success"
          value={formatPercentage(indexingSuccess)}
          caption="Indexed documents divided by total documents."
          loading={documentsQuery.isLoading}
          error={documentsQuery.isError ? getApiErrorMessage(documentsQuery.error) : null}
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
            error={usageQuery.isError ? getApiErrorMessage(usageQuery.error) : null}
            onRetry={() => {
              void usageQuery.refetch();
            }}
          />
        ) : null}
      </div>

      {showEmptyState ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
          <h2 className="text-xl font-bold text-[#2a2640]">No activity yet</h2>
          <p className="mt-2 text-sm text-[#68647b]">
            No documents or chat questions were found for this workspace. Upload documents or start a chat to populate dashboard metrics.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
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
        </section>
      ) : null}

      {showAdminUsage ? (
        <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Usage window</h2>
          <p className="mt-2 text-sm text-[#68647b]">
            Showing usage from <span className="font-semibold">{usageRange.from}</span> to{" "}
            <span className="font-semibold">{usageRange.to}</span>.
          </p>
          {usageQuery.isSuccess ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricRow label="Input tokens" value={formatInteger(usageSummary?.totals.input_tokens)} />
              <MetricRow label="Output tokens" value={formatInteger(usageSummary?.totals.output_tokens)} />
              <MetricRow label="Usage events" value={formatInteger(usageSummary?.totals.event_count)} />
              <MetricRow label="Series points" value={formatInteger(usageSummary?.series.length ?? 0)} />
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
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">{label}</p>
      <p className="text-base font-semibold text-[#2a2640]">{value}</p>
    </div>
  );
}
