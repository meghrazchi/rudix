"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "@/lib/api/errors";
import {
  cancelSyncRun,
  createSyncJob,
  listSyncJobs,
  listSyncRuns,
  triggerSyncNow,
  updateSyncJobStatus,
  type SyncJob,
  type SyncRun,
} from "@/lib/api/connector-sync";
import { getPermissionReview } from "@/lib/api/connectors";
import { queryKeys } from "@/lib/api/query";

const RUN_STATUS_BADGE: Record<string, string> = {
  queued: "bg-amber-100 text-amber-800",
  running: "bg-[#ece8ff] text-[#3525cd]",
  completed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-[#e4e1ee] text-[#464555]",
};

const JOB_STATUS_BADGE: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  paused: "bg-amber-100 text-amber-800",
  disabled: "bg-[#e4e1ee] text-[#464555]",
};

function StatusBadge({
  status,
  badgeMap,
}: {
  status: string;
  badgeMap: Record<string, string>;
}) {
  const cls = badgeMap[status] ?? "bg-[#e4e1ee] text-[#464555]";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}
    >
      {status}
    </span>
  );
}

function formatDuration(startedAt: string | null, completedAt: string | null) {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

type Props = {
  connectionId: string;
};

export function ConnectorSyncPanel({ connectionId }: Props) {
  const queryClient = useQueryClient();
  const [createJobName, setCreateJobName] = useState("");
  const [createJobOpen, setCreateJobOpen] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: queryKeys.connectorSyncJobs(connectionId),
    queryFn: () => listSyncJobs(connectionId),
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.connectorSyncRuns(connectionId),
    queryFn: () => listSyncRuns(connectionId, 10),
    refetchInterval: (data) => {
      const items = data?.state?.data?.items;
      const hasActive =
        Array.isArray(items) &&
        items.some((r) => r.status === "queued" || r.status === "running");
      return hasActive ? 4000 : false;
    },
  });

  const triggerMutation = useMutation({
    mutationFn: ({ jobId }: { jobId?: string }) =>
      triggerSyncNow(connectionId, jobId),
    onSuccess: () => {
      setErrorMsg(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      });
    },
    onError: (err) => setErrorMsg(getApiErrorMessage(err)),
  });

  const pauseMutation = useMutation({
    mutationFn: ({
      jobId,
      status,
    }: {
      jobId: string;
      status: "active" | "paused";
    }) => updateSyncJobStatus(connectionId, jobId, status),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncJobs(connectionId),
      }),
    onError: (err) => setErrorMsg(getApiErrorMessage(err)),
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => cancelSyncRun(runId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      }),
    onError: (err) => setErrorMsg(getApiErrorMessage(err)),
  });

  const createJobMutation = useMutation({
    mutationFn: () =>
      createSyncJob(connectionId, {
        name: createJobName.trim() || "Default sync",
        schedule: { type: "interval", interval_minutes: 60 },
      }),
    onSuccess: () => {
      setCreateJobOpen(false);
      setCreateJobName("");
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncJobs(connectionId),
      });
    },
    onError: (err) => setErrorMsg(getApiErrorMessage(err)),
  });

  const permissionReviewQuery = useQuery({
    queryKey: queryKeys.connectorPermissionReview(connectionId),
    queryFn: () => getPermissionReview(connectionId),
  });

  const jobs: SyncJob[] = jobsQuery.data?.items ?? [];
  const runs: SyncRun[] = runsQuery.data?.items ?? [];
  const activeJob = jobs.find((j) => j.status === "active") ?? jobs[0];
  const reviewConfirmed = permissionReviewQuery.data?.is_confirmed ?? false;
  const reviewLoaded = !permissionReviewQuery.isLoading;

  return (
    <div className="space-y-6">
      {/* Permission review gate */}
      {reviewLoaded && !reviewConfirmed && (
        <div
          className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4"
          data-testid="permission-review-gate"
        >
          <span className="material-symbols-outlined mt-0.5 shrink-0 text-[22px] text-amber-600">
            lock
          </span>
          <div>
            <div className="text-sm font-semibold text-amber-900">
              Sync blocked — permission review required
            </div>
            <p className="mt-0.5 text-sm text-amber-800">
              An admin must review and confirm the connector permission scope
              before indexing can begin. Use the Permission review panel above to
              confirm.
            </p>
          </div>
        </div>
      )}

      {errorMsg && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {errorMsg}
        </div>
      )}

      {/* Sync schedule */}
      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-[#2a2640]">Sync schedule</h3>
            <p className="text-sm text-[#68647b]">
              Configure automated sync cadence and trigger manual runs.
            </p>
          </div>
          <div className="flex gap-2">
            {activeJob && (
              <button
                type="button"
                disabled={triggerMutation.isPending || !reviewConfirmed}
                title={
                  !reviewConfirmed
                    ? "Confirm permission review before syncing"
                    : undefined
                }
                onClick={() => triggerMutation.mutate({ jobId: activeJob.id })}
                className="rounded-xl bg-[#3525cd] px-4 py-2 text-xs font-bold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {triggerMutation.isPending ? "Queuing…" : "Sync now"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setCreateJobOpen((v) => !v)}
              className="rounded-xl border border-[#d7d4e8] px-4 py-2 text-xs font-semibold text-[#3525cd] transition-colors hover:bg-[#f5f2ff]"
            >
              {createJobOpen ? "Cancel" : "Add schedule"}
            </button>
          </div>
        </div>

        {createJobOpen && (
          <div className="mb-4 flex gap-2">
            <input
              type="text"
              value={createJobName}
              onChange={(e) => setCreateJobName(e.target.value)}
              placeholder="Schedule name"
              className="flex-1 rounded-xl border border-[#d7d4e8] bg-white px-3 py-2 text-sm text-[#2a2640] focus:border-[#3525cd] focus:ring-2 focus:ring-[#3525cd]/20 focus:outline-none"
            />
            <button
              type="button"
              disabled={createJobMutation.isPending}
              onClick={() => createJobMutation.mutate()}
              className="rounded-xl bg-[#3525cd] px-4 py-2 text-xs font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        )}

        {jobsQuery.isLoading && (
          <p className="text-sm text-[#68647b]">Loading schedules…</p>
        )}
        {jobs.length === 0 && !jobsQuery.isLoading && (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
            No sync schedules configured. Add one to start syncing
            automatically.
          </div>
        )}

        <div className="space-y-2">
          {jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between rounded-xl border border-[#e8e5f3] bg-[#faf9fe] px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[#2a2640]">
                  {job.name}
                </p>
                <p className="mt-0.5 text-xs text-[#68647b]">
                  {job.schedule.type === "interval"
                    ? `Every ${job.schedule.interval_minutes ?? 60} min`
                    : job.schedule.type}
                  {job.last_run_at && (
                    <>
                      {" "}
                      · Last run {new Date(job.last_run_at).toLocaleString()}
                    </>
                  )}
                </p>
              </div>
              <div className="ml-4 flex shrink-0 items-center gap-2">
                <StatusBadge status={job.status} badgeMap={JOB_STATUS_BADGE} />
                {job.status === "active" && (
                  <button
                    type="button"
                    disabled={pauseMutation.isPending}
                    onClick={() =>
                      pauseMutation.mutate({ jobId: job.id, status: "paused" })
                    }
                    className="text-xs font-semibold text-[#464555] hover:text-[#2a2640] disabled:opacity-50"
                  >
                    Pause
                  </button>
                )}
                {job.status === "paused" && (
                  <button
                    type="button"
                    disabled={pauseMutation.isPending}
                    onClick={() =>
                      pauseMutation.mutate({ jobId: job.id, status: "active" })
                    }
                    className="text-xs font-semibold text-[#3525cd] hover:opacity-80 disabled:opacity-50"
                  >
                    Resume
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent runs */}
      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="mb-4">
          <h3 className="text-lg font-bold text-[#2a2640]">Recent sync runs</h3>
          <p className="text-sm text-[#68647b]">
            History of sync executions with item counts and error details.
          </p>
        </div>

        {runsQuery.isLoading && (
          <p className="text-sm text-[#68647b]">Loading runs…</p>
        )}
        {runs.length === 0 && !runsQuery.isLoading && (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
            No sync runs yet.
          </div>
        )}

        {runs.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-[#e8e5f3]">
            <table className="min-w-full divide-y divide-[#e8e5f3] text-sm">
              <thead className="bg-[#f5f2ff]">
                <tr>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Status
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Trigger
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Seen
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Upserted
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Deleted
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Duration
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold tracking-[0.14em] text-[#6a6780] uppercase">
                    Started
                  </th>
                  <th className="w-16 px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e8e5f3] bg-white">
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className="transition-colors hover:bg-[#faf9fe]"
                  >
                    <td className="px-4 py-2.5">
                      <StatusBadge
                        status={run.status}
                        badgeMap={RUN_STATUS_BADGE}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[#4b4860]">
                      {run.trigger_type}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[#2a2640] tabular-nums">
                      {run.items_seen}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[#2a2640] tabular-nums">
                      {run.items_upserted}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-[#2a2640] tabular-nums">
                      {run.items_deleted}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[#4b4860]">
                      {formatDuration(run.started_at, run.completed_at)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[#68647b]">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {(run.status === "queued" ||
                        run.status === "running") && (
                        <button
                          type="button"
                          disabled={cancelMutation.isPending}
                          onClick={() => cancelMutation.mutate(run.id)}
                          className="text-xs font-semibold text-rose-600 hover:text-rose-800 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      )}
                      {run.error_message && (
                        <span
                          title={run.error_message}
                          className="cursor-help text-xs text-[#68647b]"
                        >
                          ⚠
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
