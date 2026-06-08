"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
  bulkRetryFailedJobs,
  cancelFailedJob,
  getFailedJob,
  listFailedJobs,
  resolveFailedJob,
  retryFailedJob,
  type FailedJobDetail,
  type FailedJobStatus,
  type FailedJobSummary,
  type FailedJobsQuery,
} from "@/lib/api/failed-jobs";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { useAuthSession } from "@/lib/use-auth-session";

const JOB_TYPE_OPTIONS = [
  { value: "", label: "All types" },
  { value: "extraction", label: "Extraction" },
  { value: "deletion_cleanup", label: "Deletion cleanup" },
  { value: "reindex", label: "Reindex" },
  { value: "evaluation", label: "Evaluation" },
];

const STATUS_OPTIONS: { value: FailedJobStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "failed", label: "Failed" },
  { value: "retrying", label: "Retrying" },
  { value: "resolved", label: "Resolved" },
  { value: "cancelled", label: "Cancelled" },
];

function statusBadgeClass(status: string): string {
  switch (status) {
    case "failed":
      return "bg-rose-100 text-rose-800";
    case "retrying":
      return "bg-amber-100 text-amber-800";
    case "resolved":
      return "bg-emerald-100 text-emerald-800";
    case "cancelled":
      return "bg-slate-200 text-slate-700";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${statusBadgeClass(status)}`}
    >
      {status}
    </span>
  );
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function JobDetailDrawer({
  jobId,
  onClose,
  onAction,
}: {
  jobId: string;
  onClose: () => void;
  onAction: () => void;
}) {
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: queryKeys.admin.failedJobDetail(jobId),
    queryFn: () => getFailedJob(jobId),
  });

  const retryMutation = useMutation({
    mutationFn: () => retryFailedJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobs(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobDetail(jobId),
      });
      onAction();
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelFailedJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobs(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobDetail(jobId),
      });
      onAction();
    },
  });

  const resolveMutation = useMutation({
    mutationFn: () => resolveFailedJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobs(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobDetail(jobId),
      });
      onAction();
    },
  });

  const job = detailQuery.data;
  const isBusy =
    retryMutation.isPending ||
    cancelMutation.isPending ||
    resolveMutation.isPending;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Job detail"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close drawer"
      />
      <aside className="relative z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-[#e4e1f2] px-5 py-4">
          <h2 className="text-lg font-bold text-[#2a2640]">Job detail</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#6d6985] hover:bg-[#f5f3ff] hover:text-[#2a2640]"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {detailQuery.isLoading ? (
          <LoadingState compact title="Loading job detail…" className="p-8" />
        ) : detailQuery.isError ? (
          <div className="p-5">
            <ErrorState
              compact
              error={detailQuery.error}
              description={getApiErrorMessage(detailQuery.error)}
              onRetry={() => void detailQuery.refetch()}
            />
          </div>
        ) : job ? (
          <div className="flex flex-1 flex-col gap-5 p-5">
            <section className="space-y-2">
              <dl className="space-y-1 text-sm">
                <DrawerRow label="Status">
                  <StatusBadge status={job.status} />
                </DrawerRow>
                <DrawerRow label="Job type">{job.job_type}</DrawerRow>
                <DrawerRow label="Task name">
                  <code className="rounded bg-[#f3f1ff] px-1 text-xs text-[#3525cd]">
                    {job.task_name}
                  </code>
                </DrawerRow>
                <DrawerRow label="Queue">{job.queue_name ?? "—"}</DrawerRow>
                <DrawerRow label="Attempts">{job.attempt_count}</DrawerRow>
                <DrawerRow label="Retryable">
                  {job.is_retryable ? "Yes" : "No — non-idempotent"}
                </DrawerRow>
                {job.entity_type ? (
                  <DrawerRow label={`Related ${job.entity_type}`}>
                    <span className="font-mono text-xs">{job.entity_id}</span>
                  </DrawerRow>
                ) : null}
                <DrawerRow label="Error code">
                  {job.error_code ?? "—"}
                </DrawerRow>
                <DrawerRow label="Last attempted">
                  {formatDateTime(job.last_attempted_at)}
                </DrawerRow>
                <DrawerRow label="Created">
                  {formatDateTime(job.created_at)}
                </DrawerRow>
                {job.resolved_at ? (
                  <DrawerRow label="Resolved">
                    {formatDateTime(job.resolved_at)}
                  </DrawerRow>
                ) : null}
              </dl>
            </section>

            {job.error_message ? (
              <section>
                <p className="mb-1 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                  Error message
                </p>
                <pre className="max-h-32 overflow-auto rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-xs whitespace-pre-wrap text-[#4f4b68]">
                  {job.error_message}
                </pre>
              </section>
            ) : null}

            <section className="flex flex-wrap gap-2">
              {job.status === "failed" && job.is_retryable ? (
                <button
                  type="button"
                  onClick={() => retryMutation.mutate()}
                  disabled={isBusy}
                  className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {retryMutation.isPending ? "Retrying…" : "Retry"}
                </button>
              ) : null}
              {job.status !== "cancelled" && job.status !== "resolved" ? (
                <button
                  type="button"
                  onClick={() => cancelMutation.mutate()}
                  disabled={isBusy}
                  className="rounded-lg border border-[#cbc5e6] px-4 py-2 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
                </button>
              ) : null}
              {job.status !== "resolved" ? (
                <button
                  type="button"
                  onClick={() => resolveMutation.mutate()}
                  disabled={isBusy}
                  className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {resolveMutation.isPending ? "Resolving…" : "Mark resolved"}
                </button>
              ) : null}
            </section>

            {retryMutation.isError ? (
              <ErrorNotice message={getApiErrorMessage(retryMutation.error)} />
            ) : null}
            {cancelMutation.isError ? (
              <ErrorNotice message={getApiErrorMessage(cancelMutation.error)} />
            ) : null}
            {resolveMutation.isError ? (
              <ErrorNotice
                message={getApiErrorMessage(resolveMutation.error)}
              />
            ) : null}

            {job.audit_log.length > 0 ? (
              <section>
                <p className="mb-2 text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                  Audit log
                </p>
                <ul className="space-y-1">
                  {job.audit_log.map((entry) => (
                    <li
                      key={entry.id}
                      className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs"
                    >
                      <span className="font-semibold text-[#2f2a46]">
                        {entry.action}
                      </span>
                      {entry.note ? (
                        <span className="ml-1 text-[#6d6985]">
                          ({entry.note})
                        </span>
                      ) : null}
                      <span className="ml-2 text-[#8d8aa3]">
                        {formatDateTime(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function DrawerRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2">
      <dt className="shrink-0 text-[#4f4b68]">{label}</dt>
      <dd className="text-right text-[#2f2a46]">{children}</dd>
    </div>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {message}
    </p>
  );
}

function JobRow({
  job,
  selected,
  onSelect,
  onOpen,
}: {
  job: FailedJobSummary;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <tr className="border-b border-[#e4e1f2] hover:bg-[#faf9ff]">
      <td className="px-3 py-2 text-center">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          aria-label={`Select job ${job.id}`}
          className="accent-[#3525cd]"
        />
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={job.status} />
      </td>
      <td className="px-3 py-2 text-sm text-[#2f2a46]">{job.job_type}</td>
      <td className="px-3 py-2">
        <code className="rounded bg-[#f3f1ff] px-1 text-xs text-[#3525cd]">
          {job.task_name}
        </code>
      </td>
      <td className="px-3 py-2 text-sm text-[#4f4b68]">
        {job.error_code ?? "—"}
      </td>
      <td className="px-3 py-2 text-center text-sm text-[#4f4b68]">
        {job.attempt_count}
      </td>
      <td className="px-3 py-2 text-sm text-[#6d6985]">
        {formatDateTime(job.created_at)}
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={onOpen}
          className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff]"
        >
          View
        </button>
      </td>
    </tr>
  );
}

export function AdminFailedJobsPage() {
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);

  const queryClient = useQueryClient();

  const [jobTypeFilter, setJobTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<FailedJobStatus | "">("");
  const [retryableOnly, setRetryableOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const query: FailedJobsQuery = {
    page,
    page_size: 25,
    ...(jobTypeFilter ? { job_type: jobTypeFilter } : {}),
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(retryableOnly ? { retryable_only: true } : {}),
  };

  const listQuery = useQuery({
    queryKey: queryKeys.admin.failedJobs(query as Record<string, unknown>),
    queryFn: () => listFailedJobs(query),
    enabled: isAdminUser,
  });

  const bulkRetryMutation = useMutation({
    mutationFn: () => bulkRetryFailedJobs(Array.from(selectedIds)),
    onSuccess: () => {
      setSelectedIds(new Set());
      setBulkError(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.failedJobs(),
      });
    },
    onError: (err) => {
      setBulkError(getApiErrorMessage(err));
    },
  });

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin access restricted"
          description="Only owner and admin roles can access the failed jobs dashboard."
          compact={false}
        />
      </section>
    );
  }

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 25));
  const allPageSelected =
    items.length > 0 && items.every((j) => selectedIds.has(j.id));

  function toggleAll(checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const j of items) {
        if (checked) next.add(j.id);
        else next.delete(j.id);
      }
      return next;
    });
  }

  function toggleOne(id: string, checked: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      {openJobId ? (
        <JobDetailDrawer
          jobId={openJobId}
          onClose={() => setOpenJobId(null)}
          onAction={() => setOpenJobId(null)}
        />
      ) : null}

      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
              Rudix Admin
            </p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
              Failed jobs
            </h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Inspect and safely retry failed background jobs — extraction,
              chunking, indexing, evaluation, and deletion tasks.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void listQuery.refetch()}
            disabled={listQuery.isFetching}
            className="rounded-lg border border-[#cbc5e6] px-3 py-1.5 text-sm font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {listQuery.isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
        <div className="flex flex-wrap items-end gap-3 border-b border-[#e4e1f2] px-5 py-4">
          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Job type
            <select
              value={jobTypeFilter}
              onChange={(e) => {
                setJobTypeFilter(e.target.value);
                setPage(1);
                setSelectedIds(new Set());
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {JOB_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs font-semibold text-[#4f4b68]">
            Status
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as FailedJobStatus | "");
                setPage(1);
                setSelectedIds(new Set());
              }}
              className="rounded-lg border border-[#cbc5e6] px-2 py-1.5 text-sm text-[#2f2a46] focus:border-[#3525cd] focus:outline-none"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm font-semibold text-[#4f4b68]">
            <input
              type="checkbox"
              checked={retryableOnly}
              onChange={(e) => {
                setRetryableOnly(e.target.checked);
                setPage(1);
                setSelectedIds(new Set());
              }}
              className="accent-[#3525cd]"
            />
            Retryable only
          </label>

          <div className="ml-auto flex items-center gap-2">
            {selectedIds.size > 0 ? (
              <button
                type="button"
                onClick={() => bulkRetryMutation.mutate()}
                disabled={bulkRetryMutation.isPending}
                className="rounded-lg bg-[#3525cd] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[#2a1db0] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {bulkRetryMutation.isPending
                  ? "Retrying…"
                  : `Bulk retry (${selectedIds.size})`}
              </button>
            ) : null}
          </div>
        </div>

        {bulkError ? (
          <div className="border-b border-[#e4e1f2] px-5 py-3">
            <ErrorNotice message={bulkError} />
          </div>
        ) : null}

        {listQuery.isLoading ? (
          <LoadingState
            compact
            title="Loading failed jobs…"
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
        ) : items.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-[#6d6985]">
            No failed jobs match the current filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#e4e1f2] bg-[#faf9ff] text-xs font-semibold tracking-wide text-[#5d58a8] uppercase">
                <tr>
                  <th className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      onChange={(e) => toggleAll(e.target.checked)}
                      aria-label="Select all on page"
                      className="accent-[#3525cd]"
                    />
                  </th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Task</th>
                  <th className="px-3 py-2">Error code</th>
                  <th className="px-3 py-2 text-center">Attempts</th>
                  <th className="px-3 py-2">Created</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    selected={selectedIds.has(job.id)}
                    onSelect={(checked) => toggleOne(job.id, checked)}
                    onOpen={() => setOpenJobId(job.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > 25 ? (
          <div className="flex items-center justify-between border-t border-[#e4e1f2] px-5 py-3">
            <p className="text-xs text-[#6d6985]">
              {total.toLocaleString()} total — page {page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                ← Prev
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded border border-[#cbc5e6] px-2 py-0.5 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next →
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
