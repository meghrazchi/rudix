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
import { AnyPermissionGate } from "@/components/layout/PermissionGate";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  reindexDocument,
  retryDocumentOcr,
  updateDocumentTrustStatus,
} from "@/lib/api/documents";
import { updateCollection } from "@/lib/api/collections";
import { queryKeys } from "@/lib/api/query";
import {
  exportSourceHealth,
  getSourceHealthCharts,
  getSourceHealthError,
  getSourceHealthSummary,
  listSourceHealth,
} from "@/lib/api/source-health";
import type {
  SourceHealthQuery,
  SourceHealthRow,
  SourceType,
} from "@/lib/schemas/source-health";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

const PAGE_SIZE = 25;

const SOURCE_TYPE_OPTIONS: (SourceType | "")[] = [
  "",
  "file",
  "connector",
  "collection",
];
const FRESHNESS_OPTIONS = ["", "fresh", "stale", "expired"] as const;
const OCR_QUALITY_OPTIONS = [
  "",
  "high",
  "medium",
  "low",
  "failed",
  "not_required",
] as const;
const REVIEW_STATUS_OPTIONS = [
  "",
  "current",
  "trusted",
  "needs_review",
  "stale",
  "expired",
  "archived",
] as const;
const GRAPH_OPTIONS = ["", "yes", "no", "failed"] as const;

const ACTION_PERMISSION: Record<SourceType, string> = {
  file: "documents:manage",
  connector: "documents:manage",
  collection: "collections:manage",
};

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

function freshnessTone(freshness: string): "good" | "warn" | "bad" {
  if (freshness === "expired") return "bad";
  if (freshness === "stale") return "warn";
  return "good";
}

function statusTone(status: string): "good" | "warn" | "bad" | "neutral" {
  if (["indexed", "healthy"].includes(status)) return "good";
  if (
    ["failed", "extraction_failed", "infected", "blocked", "degraded"].includes(
      status,
    )
  )
    return "bad";
  if (
    ["uploaded", "processing", "pending_scan", "pending", "archived"].includes(
      status,
    )
  )
    return "warn";
  return "neutral";
}

function ocrTone(
  ocr: string | null | undefined,
): "good" | "warn" | "bad" | "neutral" {
  if (!ocr || ocr === "not_required") return "neutral";
  if (ocr === "high") return "good";
  if (ocr === "medium") return "warn";
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

function MetricCard({ label, value }: { label: string; value: number }) {
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
}: {
  title: string;
  data: Array<{ label: string; value: number }>;
}) {
  const t = useTranslations("adminSourceHealth");
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
                width={110}
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#5f5b72", fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{ borderRadius: 8, borderColor: "#dfdced" }}
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

function ErrorDetailDrawer({
  sourceType,
  sourceId,
  onClose,
}: {
  sourceType: SourceType;
  sourceId: string;
  onClose: () => void;
}) {
  const t = useTranslations("adminSourceHealth");
  const detailQuery = useQuery({
    queryKey: queryKeys.admin.sourceHealthError(sourceType, sourceId),
    queryFn: () => getSourceHealthError(sourceType, sourceId),
  });
  const detail = detailQuery.data;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={t("drawer.errorTitle")}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label={t("actions.close")}
      />
      <aside className="relative z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-[#e4e1f2] px-5 py-4">
          <h2 className="text-lg font-bold text-[#2a2640]">
            {t("drawer.errorTitle")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#6d6985] hover:bg-[#f5f3ff] hover:text-[#2a2640]"
            aria-label={t("actions.close")}
          >
            ✕
          </button>
        </header>
        <div className="flex-1 space-y-4 p-5">
          {detailQuery.isLoading ? (
            <LoadingState compact title={t("states.loadingDetail")} />
          ) : detailQuery.isError ? (
            <ErrorState
              compact
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => void detailQuery.refetch()}
            />
          ) : detail ? (
            <>
              <p className="text-sm font-semibold text-[#2f2a46]">
                {detail.source_name}
              </p>
              {detail.error_message ? (
                <section>
                  <p className="mb-1 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                    {t("drawer.errorMessage")}
                  </p>
                  <pre className="max-h-32 overflow-auto rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-xs whitespace-pre-wrap text-[#4f4b68]">
                    {detail.error_message}
                  </pre>
                </section>
              ) : null}
              {detail.extraction_warnings.length > 0 ? (
                <section>
                  <p className="mb-1 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                    {t("drawer.extractionWarnings")}
                  </p>
                  <ul className="list-disc space-y-1 ps-5 text-xs text-[#4f4b68]">
                    {detail.extraction_warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {detail.table_warnings.length > 0 ? (
                <section>
                  <p className="mb-1 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                    {t("drawer.tableWarnings")}
                  </p>
                  <ul className="space-y-1">
                    {detail.table_warnings.map((warning) => (
                      <li
                        key={warning.chunk_id}
                        className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#4f4b68]"
                      >
                        {t("drawer.tableWarningLine", {
                          page: warning.page_number ?? "—",
                          confidence:
                            warning.confidence != null
                              ? Math.round(warning.confidence * 100)
                              : "—",
                        })}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {!detail.error_message &&
              detail.extraction_warnings.length === 0 &&
              detail.table_warnings.length === 0 ? (
                <p className="text-sm text-[#6d6985]">{t("drawer.noIssues")}</p>
              ) : null}
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function AssignReviewerDialog({
  row,
  onClose,
  onSaved,
}: {
  row: SourceHealthRow;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("adminSourceHealth");
  const [reviewerId, setReviewerId] = useState(row.owner_id ?? "");
  const [dueDate, setDueDate] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      if (row.source_type === "collection") {
        return updateCollection(row.source_id, {
          review_owner_id: reviewerId || null,
          review_due_date: dueDate || null,
        });
      }
      return updateDocumentTrustStatus(row.source_id, {
        trust_status: row.trust_status ?? "current",
        review_owner_id: reviewerId || null,
        review_due_date: dueDate || null,
      });
    },
    onSuccess: onSaved,
  });

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("dialog.assignReviewerTitle")}
    >
      <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl">
        <h2 className="mb-3 text-lg font-bold text-[#2a2640]">
          {t("dialog.assignReviewerTitle")}
        </h2>
        <p className="mb-3 text-sm text-[#6d6985]">{row.source_name}</p>
        <label className="mb-3 flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
          {t("dialog.reviewerId")}
          <input
            type="text"
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            placeholder={t("dialog.reviewerIdPlaceholder")}
            className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
          />
        </label>
        <label className="mb-4 flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
          {t("dialog.dueDate")}
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
          />
        </label>
        {mutation.isError ? (
          <p className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {getApiErrorMessage(mutation.error)}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            {t("actions.close")}
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {mutation.isPending ? t("actions.saving") : t("actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}

function SourceRow({
  row,
  onChanged,
  onViewError,
  onAssignReviewer,
}: {
  row: SourceHealthRow;
  onChanged: () => void;
  onViewError: () => void;
  onAssignReviewer: () => void;
}) {
  const t = useTranslations("adminSourceHealth");
  const [actionError, setActionError] = useState<string | null>(null);

  const reindexMutation = useMutation({
    mutationFn: () => reindexDocument(row.source_id),
    onSuccess: () => {
      setActionError(null);
      onChanged();
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });
  const ocrRetryMutation = useMutation({
    mutationFn: () => retryDocumentOcr(row.source_id),
    onSuccess: () => {
      setActionError(null);
      onChanged();
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });
  const markMutation = useMutation({
    mutationFn: async (verdict: "verified" | "deprecated") => {
      if (row.source_type === "collection") {
        return updateCollection(row.source_id, {
          review_status: verdict === "verified" ? "trusted" : "archived",
        });
      }
      return updateDocumentTrustStatus(row.source_id, {
        trust_status: verdict,
      });
    },
    onSuccess: () => {
      setActionError(null);
      onChanged();
    },
    onError: (err) => setActionError(getApiErrorMessage(err)),
  });

  const permission = ACTION_PERMISSION[row.source_type];
  const actions = new Set(row.available_actions);
  const openHref =
    row.source_type === "collection"
      ? "/collections"
      : `/documents/${row.source_id}`;

  return (
    <tr className="border-b border-[#e4e1f2] align-top hover:bg-[#faf9ff]">
      <td className="px-3 py-2">
        <p className="text-sm font-semibold text-[#2f2a46]">
          {row.source_name}
        </p>
        {row.connector_name ? (
          <p className="text-xs text-[#8d8aa3]">{row.connector_name}</p>
        ) : null}
        {actionError ? (
          <p className="mt-1 text-xs text-rose-700">{actionError}</p>
        ) : null}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {t(`sourceTypes.${row.source_type}`)}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.collection_name ?? "—"}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.owner_name ?? "—"}
      </td>
      <td className="px-3 py-2">
        <Badge label={row.status} tone={statusTone(row.status)} />
        {row.missing_metadata ? (
          <span className="ms-1">
            <Badge label={t("badges.missingMetadata")} tone="warn" />
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-[#6d6985]">
        {formatDateTime(row.last_indexed_at)}
      </td>
      <td className="px-3 py-2 text-xs text-[#6d6985]">
        {formatDateTime(row.last_updated_at)}
      </td>
      <td className="px-3 py-2">
        <Badge label={row.freshness} tone={freshnessTone(row.freshness)} />
      </td>
      <td className="px-3 py-2">
        {row.ocr_quality ? (
          <Badge label={row.ocr_quality} tone={ocrTone(row.ocr_quality)} />
        ) : (
          <span className="text-xs text-[#8d8aa3]">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {row.review_status ?? "—"}
      </td>
      <td className="px-3 py-2">
        <AnyPermissionGate anyOf={[permission]}>
          <div className="flex flex-wrap gap-1.5">
            {actions.has("reindex") ? (
              <button
                type="button"
                onClick={() => reindexMutation.mutate()}
                disabled={reindexMutation.isPending}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:opacity-60"
              >
                {t("actions.reindex")}
              </button>
            ) : null}
            {actions.has("ocr_retry") ? (
              <button
                type="button"
                onClick={() => ocrRetryMutation.mutate()}
                disabled={ocrRetryMutation.isPending}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:opacity-60"
              >
                {t("actions.ocrRetry")}
              </button>
            ) : null}
            {actions.has("assign_reviewer") ? (
              <button
                type="button"
                onClick={onAssignReviewer}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
              >
                {t("actions.assignReviewer")}
              </button>
            ) : null}
            {actions.has("mark_verified") ? (
              <button
                type="button"
                onClick={() => markMutation.mutate("verified")}
                disabled={markMutation.isPending}
                className="rounded border border-emerald-300 px-2 py-0.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
              >
                {t("actions.markVerified")}
              </button>
            ) : null}
            {actions.has("mark_deprecated") ? (
              <button
                type="button"
                onClick={() => markMutation.mutate("deprecated")}
                disabled={markMutation.isPending}
                className="rounded border border-amber-300 px-2 py-0.5 text-xs font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-60"
              >
                {t("actions.markDeprecated")}
              </button>
            ) : null}
          </div>
        </AnyPermissionGate>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          <Link
            href={openHref}
            className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
          >
            {t("actions.open")}
          </Link>
          {actions.has("view_error") ? (
            <button
              type="button"
              onClick={onViewError}
              className="rounded border border-rose-300 px-2 py-0.5 text-xs font-semibold text-rose-700 hover:bg-rose-50"
            >
              {t("actions.viewError")}
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

export function AdminSourceHealthPage() {
  const t = useTranslations("adminSourceHealth");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const queryClient = useQueryClient();

  const [sourceType, setSourceType] = useState<SourceType | "">("");
  const [status, setStatus] = useState("");
  const [freshness, setFreshness] =
    useState<(typeof FRESHNESS_OPTIONS)[number]>("");
  const [ocrQuality, setOcrQuality] =
    useState<(typeof OCR_QUALITY_OPTIONS)[number]>("");
  const [reviewStatus, setReviewStatus] =
    useState<(typeof REVIEW_STATUS_OPTIONS)[number]>("");
  const [graphIndexed, setGraphIndexed] =
    useState<(typeof GRAPH_OPTIONS)[number]>("");
  const [missingMetadataOnly, setMissingMetadataOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [errorTarget, setErrorTarget] = useState<{
    sourceType: SourceType;
    sourceId: string;
  } | null>(null);
  const [reviewerTarget, setReviewerTarget] = useState<SourceHealthRow | null>(
    null,
  );
  const [exportError, setExportError] = useState<string | null>(null);

  const query: SourceHealthQuery = {
    page,
    page_size: PAGE_SIZE,
    ...(sourceType ? { source_type: sourceType } : {}),
    ...(status ? { status } : {}),
    ...(freshness ? { freshness } : {}),
    ...(ocrQuality ? { ocr_quality: ocrQuality } : {}),
    ...(reviewStatus ? { review_status: reviewStatus } : {}),
    ...(graphIndexed ? { graph_indexed: graphIndexed } : {}),
    ...(missingMetadataOnly ? { missing_metadata: true } : {}),
    ...(search.trim() ? { q: search.trim() } : {}),
  };

  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.sourceHealthSummary,
    queryFn: getSourceHealthSummary,
    enabled: isAdminUser,
  });
  const chartsQuery = useQuery({
    queryKey: queryKeys.admin.sourceHealthCharts,
    queryFn: getSourceHealthCharts,
    enabled: isAdminUser,
  });
  const listQuery = useQuery({
    queryKey: queryKeys.admin.sourceHealthSources(
      query as Record<string, unknown>,
    ),
    queryFn: () => listSourceHealth(query),
    enabled: isAdminUser,
  });

  function invalidateAll() {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.sourceHealthSummary,
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.sourceHealthCharts,
    });
    void queryClient.invalidateQueries({
      queryKey: ["admin", "source-health", "sources"],
    });
  }

  function resetPage() {
    setPage(1);
  }

  async function handleExport() {
    try {
      setExportError(null);
      const blob = await exportSourceHealth(query);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "source-health.csv";
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
  const rows = listQuery.data?.rows ?? [];
  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {errorTarget ? (
        <ErrorDetailDrawer
          sourceType={errorTarget.sourceType}
          sourceId={errorTarget.sourceId}
          onClose={() => setErrorTarget(null)}
        />
      ) : null}
      {reviewerTarget ? (
        <AssignReviewerDialog
          row={reviewerTarget}
          onClose={() => setReviewerTarget(null)}
          onSaved={() => {
            setReviewerTarget(null);
            invalidateAll();
          }}
        />
      ) : null}

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
            <button
              type="button"
              onClick={() => void handleExport()}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
            >
              {t("actions.export")}
            </button>
            <button
              type="button"
              onClick={() => void listQuery.refetch()}
              disabled={listQuery.isFetching}
              className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {listQuery.isFetching
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
            label={t("metrics.totalSources")}
            value={summary.total_sources}
          />
          <MetricCard label={t("metrics.indexed")} value={summary.indexed} />
          <MetricCard
            label={t("metrics.failedIndexing")}
            value={summary.failed_indexing}
          />
          <MetricCard label={t("metrics.pending")} value={summary.pending} />
          <MetricCard
            label={t("metrics.ocrRequired")}
            value={summary.ocr_required}
          />
          <MetricCard
            label={t("metrics.ocrLowConfidence")}
            value={summary.ocr_low_confidence}
          />
          <MetricCard
            label={t("metrics.tableExtractionWarnings")}
            value={summary.table_extraction_warnings}
          />
          <MetricCard
            label={t("metrics.missingMetadata")}
            value={summary.missing_metadata}
          />
          <MetricCard label={t("metrics.stale")} value={summary.stale} />
          <MetricCard
            label={t("metrics.deprecated")}
            value={summary.deprecated}
          />
          <MetricCard label={t("metrics.expired")} value={summary.expired} />
          <MetricCard
            label={t("metrics.unreviewed")}
            value={summary.unreviewed}
          />
          <MetricCard
            label={t("metrics.needsReview")}
            value={summary.needs_review}
          />
        </div>
      ) : null}

      {chartsQuery.isLoading ? (
        <LoadingState compact title={t("states.loadingCharts")} />
      ) : charts ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <ChartCard
            title={t("charts.statusDistribution")}
            data={charts.status_distribution.map((item) => ({
              label: item.status,
              value: item.count,
            }))}
          />
          <ChartCard
            title={t("charts.indexingFailures")}
            data={charts.indexing_failures.map((item) => ({
              label: item.date.slice(5),
              value: item.failed_count,
            }))}
          />
          <ChartCard
            title={t("charts.staleByCollection")}
            data={charts.stale_by_collection.map((item) => ({
              label: item.collection_name,
              value: item.stale_count,
            }))}
          />
          <ChartCard
            title={t("charts.ocrQuality")}
            data={charts.ocr_quality_distribution.map((item) => ({
              label: item.ocr_quality_status,
              value: item.count,
            }))}
          />
          <ChartCard
            title={t("charts.reviewNeedsByOwner")}
            data={charts.review_needs_by_owner.map((item) => ({
              label: item.owner_name,
              value: item.needs_review_count,
            }))}
          />
          <ChartCard
            title={t("charts.connectorFreshness")}
            data={charts.connector_freshness.map((item) => ({
              label: item.connector_name,
              value: item.days_since_last_sync ?? 0,
            }))}
          />
        </div>
      ) : null}

      <div className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e1f2] px-5 py-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.sourceType")}
            <select
              value={sourceType}
              onChange={(e) => {
                setSourceType(e.target.value as SourceType | "");
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {SOURCE_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? t(`sourceTypes.${value}`) : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.freshness")}
            <select
              value={freshness}
              onChange={(e) => {
                setFreshness(
                  e.target.value as (typeof FRESHNESS_OPTIONS)[number],
                );
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {FRESHNESS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.ocrQuality")}
            <select
              value={ocrQuality}
              onChange={(e) => {
                setOcrQuality(
                  e.target.value as (typeof OCR_QUALITY_OPTIONS)[number],
                );
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {OCR_QUALITY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.reviewStatus")}
            <select
              value={reviewStatus}
              onChange={(e) => {
                setReviewStatus(
                  e.target.value as (typeof REVIEW_STATUS_OPTIONS)[number],
                );
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {REVIEW_STATUS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.graphIndexed")}
            <select
              value={graphIndexed}
              onChange={(e) => {
                setGraphIndexed(
                  e.target.value as (typeof GRAPH_OPTIONS)[number],
                );
                resetPage();
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {GRAPH_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value ? value : t("filters.all")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm font-semibold text-[#4f4b68]">
            <input
              type="checkbox"
              checked={missingMetadataOnly}
              onChange={(e) => {
                setMissingMetadataOnly(e.target.checked);
                resetPage();
              }}
              className="accent-[#3525cd]"
            />
            {t("filters.missingMetadataOnly")}
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
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
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            {t("filters.status")}
            <input
              type="text"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                resetPage();
              }}
              placeholder={t("filters.statusPlaceholder")}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            />
          </label>
        </div>

        {listQuery.isLoading ? (
          <LoadingState
            compact
            title={t("states.loadingList")}
            className="px-5 py-8"
          />
        ) : listQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={listQuery.error}
              description={getApiErrorMessage(listQuery.error)}
              onRetry={() => void listQuery.refetch()}
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
                  <th className="px-3 py-2">{t("table.sourceName")}</th>
                  <th className="px-3 py-2">{t("table.sourceType")}</th>
                  <th className="px-3 py-2">{t("table.collection")}</th>
                  <th className="px-3 py-2">{t("table.owner")}</th>
                  <th className="px-3 py-2">{t("table.status")}</th>
                  <th className="px-3 py-2">{t("table.lastIndexed")}</th>
                  <th className="px-3 py-2">{t("table.lastUpdated")}</th>
                  <th className="px-3 py-2">{t("table.freshness")}</th>
                  <th className="px-3 py-2">{t("table.ocrQuality")}</th>
                  <th className="px-3 py-2">{t("table.reviewStatus")}</th>
                  <th className="px-3 py-2">{t("table.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <SourceRow
                    key={`${row.source_type}-${row.source_id}`}
                    row={row}
                    onChanged={invalidateAll}
                    onViewError={() =>
                      setErrorTarget({
                        sourceType: row.source_type,
                        sourceId: row.source_id,
                      })
                    }
                    onAssignReviewer={() => setReviewerTarget(row)}
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
