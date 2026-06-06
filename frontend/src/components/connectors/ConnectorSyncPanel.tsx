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
import { queryKeys } from "@/lib/api/query";

const STATUS_BADGE: Record<string, string> = {
  queued: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-700",
};

const JOB_STATUS_BADGE: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  paused: "bg-yellow-100 text-yellow-800",
  disabled: "bg-gray-100 text-gray-700",
};

function StatusBadge({
  status,
  badgeMap,
}: {
  status: string;
  badgeMap: Record<string, string>;
}) {
  const cls = badgeMap[status] ?? "bg-gray-100 text-gray-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}
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
    mutationFn: ({ jobId, status }: { jobId: string; status: "active" | "paused" }) =>
      updateSyncJobStatus(connectionId, jobId, status),
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

  const jobs: SyncJob[] = jobsQuery.data?.items ?? [];
  const runs: SyncRun[] = runsQuery.data?.items ?? [];
  const activeJob = jobs.find((j) => j.status === "active") ?? jobs[0];

  return (
    <div className="space-y-6">
      {errorMsg && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {/* Sync jobs section */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Sync schedule</h3>
          <div className="flex gap-2">
            {activeJob && (
              <button
                type="button"
                disabled={triggerMutation.isPending}
                onClick={() => triggerMutation.mutate({ jobId: activeJob.id })}
                className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {triggerMutation.isPending ? "Queuing…" : "Sync now"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setCreateJobOpen((v) => !v)}
              className="rounded border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              {createJobOpen ? "Cancel" : "Add schedule"}
            </button>
          </div>
        </div>

        {createJobOpen && (
          <div className="mb-3 flex gap-2">
            <input
              type="text"
              value={createJobName}
              onChange={(e) => setCreateJobName(e.target.value)}
              placeholder="Schedule name"
              className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
            <button
              type="button"
              disabled={createJobMutation.isPending}
              onClick={() => createJobMutation.mutate()}
              className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        )}

        {jobsQuery.isLoading && (
          <p className="text-sm text-gray-500">Loading schedules…</p>
        )}
        {jobs.length === 0 && !jobsQuery.isLoading && (
          <p className="text-sm text-gray-500">
            No sync schedules configured. Add one to start syncing automatically.
          </p>
        )}
        <div className="space-y-2">
          {jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-900">
                  {job.name}
                </p>
                <p className="mt-0.5 text-xs text-gray-500">
                  {job.schedule.type === "interval"
                    ? `Every ${job.schedule.interval_minutes ?? 60} min`
                    : job.schedule.type}
                  {job.last_run_at && (
                    <> · Last run {new Date(job.last_run_at).toLocaleString()}</>
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
                    className="text-xs text-gray-500 hover:text-gray-900"
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
                    className="text-xs text-indigo-600 hover:text-indigo-800"
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
      <div>
        <h3 className="mb-3 text-sm font-semibold text-gray-900">
          Recent runs
        </h3>
        {runsQuery.isLoading && (
          <p className="text-sm text-gray-500">Loading runs…</p>
        )}
        {runs.length === 0 && !runsQuery.isLoading && (
          <p className="text-sm text-gray-500">No sync runs yet.</p>
        )}
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">
                  Status
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">
                  Trigger
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500">
                  Seen
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500">
                  Upserted
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500">
                  Deleted
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">
                  Duration
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500">
                  Started
                </th>
                <th className="w-16 px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {runs.map((run) => (
                <tr key={run.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <StatusBadge status={run.status} badgeMap={STATUS_BADGE} />
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-600">
                    {run.trigger_type}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700">
                    {run.items_seen}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700">
                    {run.items_upserted}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700">
                    {run.items_deleted}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-600">
                    {formatDuration(run.started_at, run.completed_at)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {(run.status === "queued" || run.status === "running") && (
                      <button
                        type="button"
                        disabled={cancelMutation.isPending}
                        onClick={() => cancelMutation.mutate(run.id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Cancel
                      </button>
                    )}
                    {run.error_message && (
                      <span
                        title={run.error_message}
                        className="cursor-help text-xs text-gray-400"
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
      </div>
    </div>
  );
}
