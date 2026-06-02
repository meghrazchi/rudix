"use client";

import { useState } from "react";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  listAdminDocumentDeletion,
  retryDeleteDocument,
  type AdminDocumentDeletionItem,
} from "@/lib/api/documents";
import type { DocumentStatus } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";

const PAGE_LIMIT = 50;

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function statusBadgeClass(status: DocumentStatus): string {
  if (status === "delete_requested") {
    return "bg-rose-50 text-rose-600";
  }
  if (status === "deleting") {
    return "bg-slate-200 text-slate-700";
  }
  if (status === "retained_by_policy") {
    return "bg-yellow-100 text-yellow-800";
  }
  if (status === "failed") {
    return "bg-rose-100 text-rose-800";
  }
  return "bg-slate-100 text-slate-600";
}

function isRetryable(item: AdminDocumentDeletionItem): boolean {
  return (
    item.status === "delete_requested" ||
    item.status === "deleting" ||
    item.status === "failed"
  );
}

type DeletionStatusSummary = {
  delete_requested: number;
  deleting: number;
  retained_by_policy: number;
  failed: number;
};

export function AdminDeletionStatusPage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();

  const [offset, setOffset] = useState(0);
  const [includeFailed, setIncludeFailed] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackRequestId, setFeedbackRequestId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const canView = canViewAdminUsage(state.session?.role);

  const queryOpts = {
    include_failed: includeFailed,
    limit: PAGE_LIMIT,
    offset,
  };

  const listQuery = useQuery({
    queryKey: [...queryKeys.documents.all, "admin-deletion", queryOpts] as const,
    queryFn: () => listAdminDocumentDeletion(queryOpts),
    enabled: canView,
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
  });

  const retryMutation = useMutation({
    mutationFn: (documentId: string) => retryDeleteDocument(documentId),
    onSuccess: async (result) => {
      setFeedback(
        `Retry queued for document ${result.document_id}. Status: ${result.status}.`,
      );
      setFeedbackRequestId(null);
      setRetryingId(null);
      await queryClient.invalidateQueries({
        queryKey: [...queryKeys.documents.all, "admin-deletion"],
      });
    },
    onError: (error) => {
      setFeedback(getApiErrorMessage(error));
      setFeedbackRequestId(extractRequestIdFromError(error));
      setRetryingId(null);
    },
  });

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;

  const summary = items.reduce<DeletionStatusSummary>(
    (acc, item) => {
      const key = item.status as keyof DeletionStatusSummary;
      if (key in acc) acc[key] += 1;
      return acc;
    },
    { delete_requested: 0, deleting: 0, retained_by_policy: 0, failed: 0 },
  );

  const listForbidden = isForbiddenError(listQuery.error);
  const canGoPrev = offset > 0;
  const canGoNext = total > offset + PAGE_LIMIT;

  if (!canView) {
    return (
      <ForbiddenState
        title="Admin access required"
        description="You do not have permission to view the deletion status dashboard."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-[#1b1b24]">
            Document deletion status
          </h1>
          <p className="mt-1 text-sm text-[#6a6780]">
            Documents in deletion lifecycle states. Retry stuck or failed
            cleanups.
          </p>
        </div>
        <Link
          href="/documents"
          className="rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9]"
        >
          All documents
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {(
          [
            {
              key: "delete_requested",
              label: "Delete requested",
              color: "text-rose-600",
            },
            { key: "deleting", label: "Deleting", color: "text-slate-700" },
            {
              key: "retained_by_policy",
              label: "Retained",
              color: "text-yellow-700",
            },
            { key: "failed", label: "Failed cleanup", color: "text-rose-800" },
          ] as const
        ).map(({ key, label, color }) => (
          <div
            key={key}
            className="rounded-xl border border-[#e5e3f1] bg-white p-4 shadow-sm"
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              {label}
            </p>
            <p className={`mt-1 text-2xl font-bold ${color}`}>
              {summary[key as keyof DeletionStatusSummary]}
            </p>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-[#505f76]">
          <input
            type="checkbox"
            checked={includeFailed}
            onChange={(e) => {
              setIncludeFailed(e.target.checked);
              setOffset(0);
            }}
            className="h-4 w-4 rounded border-[#c9c6dc] accent-[#3525cd]"
          />
          Include documents with failed cleanup
        </label>
        {feedback ? (
          <p
            role="status"
            className="rounded-lg border border-[#ddd7f6] bg-[#f3f1ff] px-3 py-1.5 text-sm text-[#3f3778]"
          >
            {feedback}
            {feedbackRequestId ? ` (Trace: ${feedbackRequestId})` : ""}
          </p>
        ) : null}
      </div>

      {listQuery.isLoading ? (
        <LoadingState title="Loading deletion status..." />
      ) : null}

      {listQuery.isError && listForbidden ? (
        <ForbiddenState
          compact
          title="Access denied"
          description="You do not have permission to view document deletion status."
          requestId={extractRequestIdFromError(listQuery.error)}
        />
      ) : null}

      {listQuery.isError && !listForbidden ? (
        <ErrorState
          error={listQuery.error}
          description={getApiErrorMessage(listQuery.error)}
          onRetry={() => void listQuery.refetch()}
        />
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && items.length === 0 ? (
        <EmptyState
          title="No documents in deletion states"
          description="All document deletions have completed cleanly. No pending or stuck operations."
        />
      ) : null}

      {!listQuery.isLoading && !listQuery.isError && items.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-[#e5e3f1]">
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse bg-white text-left text-sm">
              <thead className="border-b border-[#e5e3f1] bg-[#f8f7ff]">
                <tr className="text-[11px] font-semibold tracking-wide text-[#6a6780] uppercase">
                  <th className="px-4 py-3">Filename</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Requested at</th>
                  <th className="px-4 py-3">Hold / error</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#ece9f6]">
                {items.map((item) => (
                  <tr
                    key={item.document_id}
                    className="align-top hover:bg-[#faf9ff]"
                  >
                    <td className="px-4 py-3">
                      <p className="font-semibold text-[#1b1b24]">
                        {item.filename}
                      </p>
                      <p className="text-xs text-[#7a768f]">
                        {item.document_id}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-xs font-medium uppercase text-[#505f76]">
                      {item.file_type}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2 py-1 text-xs font-bold uppercase tracking-wide ${statusBadgeClass(item.status)}`}
                      >
                        {item.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-[#68647b]">
                      {formatDate(item.deletion_requested_at)}
                    </td>
                    <td className="px-4 py-3 max-w-xs">
                      {item.deletion_hold_reason ? (
                        <p className="text-xs text-yellow-700">
                          {item.deletion_hold_reason}
                        </p>
                      ) : null}
                      {item.error_message ? (
                        <p className="text-xs text-rose-700 break-all">
                          {item.error_message}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {isRetryable(item) ? (
                        <button
                          type="button"
                          disabled={
                            retryMutation.isPending &&
                            retryingId === item.document_id
                          }
                          onClick={() => {
                            setRetryingId(item.document_id);
                            setFeedback(null);
                            retryMutation.mutate(item.document_id);
                          }}
                          className="inline-flex items-center gap-1 rounded-lg bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2a1ea3] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <span className="material-symbols-outlined text-[14px]">
                            refresh
                          </span>
                          Retry
                        </button>
                      ) : (
                        <span className="text-xs text-[#9e9bb5]">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-[#e5e3f1] bg-[#fcfbff] px-4 py-3">
            <button
              type="button"
              disabled={!canGoPrev}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_LIMIT))}
              className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="material-symbols-outlined text-[18px]">
                chevron_left
              </span>
              Previous
            </button>
            <p className="text-sm text-[#6a6780]">
              {offset + 1}–{Math.min(offset + PAGE_LIMIT, total)} of {total}
            </p>
            <button
              type="button"
              disabled={!canGoNext}
              onClick={() => setOffset((o) => o + PAGE_LIMIT)}
              className="flex items-center gap-1 rounded-lg border border-[#d2cee6] px-3 py-1.5 text-sm font-semibold text-[#2f2c45] hover:bg-[#f1eff9] disabled:cursor-not-allowed disabled:opacity-60"
            >
              Next
              <span className="material-symbols-outlined text-[18px]">
                chevron_right
              </span>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
