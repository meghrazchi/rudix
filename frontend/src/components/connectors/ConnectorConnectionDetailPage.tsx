"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { getApiErrorMessage, type ApiClientError } from "@/lib/api/errors";
import {
  deleteConnectorConnection,
  getConnectorConnection,
  refreshConnectorCredential,
} from "@/lib/api/connectors";
import {
  getSyncRun,
  listSyncJobs,
  listSyncRuns,
  triggerSyncNow,
  updateSyncJobStatus,
  type SyncJob,
  type SyncRun,
} from "@/lib/api/connector-sync";
import { queryKeys } from "@/lib/api/query";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDER_BRAND: Record<string, { color: string; initial: string }> = {
  confluence: { color: "#0052CC", initial: "C" },
  google_drive: { color: "#4285F4", initial: "G" },
  "microsoft-sharepoint-onedrive": { color: "#0078D4", initial: "M" },
  notion: { color: "#000000", initial: "N" },
  slack: { color: "#4A154B", initial: "S" },
  github: { color: "#24292E", initial: "G" },
  gitlab: { color: "#FC6D26", initial: "GL" },
};

const RUN_STATUS_BADGE: Record<string, string> = {
  queued: "bg-amber-100 text-amber-800",
  running: "bg-[#ece8ff] text-[#3525cd]",
  completed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-[#e4e1ee] text-[#464555]",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatRelative(date: string | null): string {
  if (!date) return "Never";
  const diff = Date.now() - new Date(date).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min${mins === 1 ? "" : "s"} ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hr${hrs === 1 ? "" : "s"} ago`;
  const days = Math.floor(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatDuration(startedAt: string | null, completedAt: string | null) {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ProviderAvatar({ providerKey }: { providerKey: string }) {
  const brand = PROVIDER_BRAND[providerKey] ?? { color: "#3525cd", initial: "?" };
  return (
    <div
      className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-[#d7d4e8]"
      style={{ backgroundColor: brand.color + "1a" }}
    >
      <div
        className="flex h-10 w-10 items-center justify-center rounded-lg text-lg font-bold text-white"
        style={{ backgroundColor: brand.color }}
      >
        {brand.initial}
      </div>
    </div>
  );
}

function ConnectionStatusBadge({ status }: { status: string }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-[11px] font-bold text-emerald-800 border border-emerald-200">
        <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }}>
          check_circle
        </span>
        Connected
      </span>
    );
  }
  if (status === "paused") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-[11px] font-bold text-amber-800 border border-amber-200">
        Paused
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-[11px] font-bold text-red-800 border border-red-200">
      {status.replace(/_/g, " ")}
    </span>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  const cls = RUN_STATUS_BADGE[status] ?? "bg-[#e4e1ee] text-[#464555]";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold ${cls}`}>
      {status}
    </span>
  );
}

function StatCard({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: string | number;
  icon: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
      <p className="text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase mb-3">
        {label}
      </p>
      <div className="flex items-end justify-between">
        <p className={`text-2xl font-extrabold ${accent ? "text-rose-600" : "text-[#2a2640]"}`}>
          {value}
        </p>
        <span className="material-symbols-outlined text-[24px] text-[#3525cd]/30">
          {icon}
        </span>
      </div>
    </div>
  );
}

function CurrentJobPanel({ run }: { run: SyncRun }) {
  const progress =
    run.items_seen > 0
      ? Math.min(Math.round((run.items_upserted / run.items_seen) * 100), 99)
      : null;

  return (
    <div className="relative overflow-hidden rounded-2xl border-2 border-[#3525cd]/20 bg-white shadow-sm">
      <div className="absolute top-0 left-0 h-full w-1 bg-[#3525cd]" />
      <div className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h4 className="text-lg font-bold text-[#2a2640]">Current Sync Job</h4>
            <p className="text-sm text-[#68647b] capitalize">
              {run.trigger_type} sync in progress
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-extrabold text-[#3525cd]">
              {progress !== null ? `${progress}%` : "—"}
            </p>
            <p className="text-[10px] font-bold tracking-widest text-[#777587] uppercase">
              Progress
            </p>
          </div>
        </div>

        <div className="mb-3 h-3 w-full overflow-hidden rounded-full bg-[#f0ecf9]">
          {progress !== null ? (
            <div
              className="h-full rounded-full bg-[#3525cd] transition-all duration-1000"
              style={{ width: `${progress}%` }}
            />
          ) : (
            <div className="h-full w-1/2 animate-pulse rounded-full bg-[#3525cd]" />
          )}
        </div>

        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-[#3525cd]" />
            <span className="font-medium text-[#2a2640]">
              {run.status === "running" ? "Processing items…" : "Queued"}
            </span>
          </div>
          <span className="text-[#777587]">
            Seen:{" "}
            <span className="font-bold text-[#2a2640]">
              {run.items_seen.toLocaleString()}
            </span>{" "}
            · Upserted:{" "}
            <span className="font-bold text-[#2a2640]">
              {run.items_upserted.toLocaleString()}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

function CredentialPanel({
  diagnostics,
  connectionStatus,
}: {
  diagnostics: {
    credential_status: string | null;
    scopes: string[];
    expires_at: string | null;
  };
  connectionStatus: string;
}) {
  const trustState =
    diagnostics.credential_status === "revoked" || connectionStatus === "revoked"
      ? "Revoked"
      : diagnostics.credential_status === "error" || connectionStatus === "error"
        ? "Needs attention"
        : "Healthy";
  const isHealthy = trustState === "Healthy";

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h4 className="mb-5 text-lg font-bold text-[#2a2640]">
        Credential diagnostics
      </h4>
      <div className="space-y-4">
        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            Credential Status
          </p>
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${isHealthy ? "bg-emerald-500" : "bg-rose-500"}`}
            />
            <span className="font-bold text-[#2a2640]">
              {diagnostics.credential_status ?? "unknown"}
            </span>
          </div>
        </div>

        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            Granted Scopes
          </p>
          {diagnostics.scopes.length === 0 ? (
            <p className="text-sm text-[#68647b]">No scopes cached.</p>
          ) : (
            <div className="space-y-1">
              {diagnostics.scopes.map((scope) => (
                <p
                  key={scope}
                  className="break-all rounded border border-[#d7d4e8] bg-[#f0ecf9] p-2 font-mono text-[11px] text-[#3525cd]"
                >
                  {scope}
                </p>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            Trust State
          </p>
          <div
            className={`flex items-center gap-2 font-bold ${
              isHealthy ? "text-emerald-700" : "text-rose-700"
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">
              shield_lock
            </span>
            <span>{trustState}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SchedulePanel({
  job,
  onPause,
  onResume,
  isPending,
}: {
  job: SyncJob | undefined;
  onPause: () => void;
  onResume: () => void;
  isPending: boolean;
}) {
  const badgeCls =
    !job
      ? "bg-[#e4e1ee] text-[#464555]"
      : job.status === "active"
        ? "bg-emerald-100 text-emerald-800"
        : job.status === "paused"
          ? "bg-amber-100 text-amber-800"
          : "bg-[#e4e1ee] text-[#464555]";

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-5 flex items-center justify-between">
        <h4 className="text-lg font-bold text-[#2a2640]">Sync Schedule</h4>
        {job && (
          <span
            className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${badgeCls}`}
          >
            {job.status}
          </span>
        )}
      </div>

      {job ? (
        <>
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[#d7d4e8] bg-[#f0ecf9]">
              <span className="material-symbols-outlined text-[#464555]">timer</span>
            </div>
            <div>
              <p className="text-2xl font-extrabold text-[#2a2640]">
                {job.schedule.type === "interval"
                  ? `Every ${job.schedule.interval_minutes ?? 60} min`
                  : "Manual only"}
              </p>
              <p className="text-sm text-[#68647b]">{job.name}</p>
            </div>
          </div>
          <button
            type="button"
            disabled={isPending}
            onClick={job.status === "active" ? onPause : onResume}
            className="mt-5 w-full rounded-xl border border-[#d7d4e8] py-2 text-sm font-bold text-[#464555] transition-colors hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {job.status === "active" ? "Pause schedule" : "Resume schedule"}
          </button>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
          No sync schedule configured.
        </div>
      )}
    </div>
  );
}

function RecentErrorsPanel({ runs }: { runs: SyncRun[] }) {
  const errorRuns = runs
    .filter((r) => r.status === "failed" && r.error_message)
    .slice(0, 5);

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h4 className="mb-5 text-lg font-bold text-[#2a2640]">Recent Errors</h4>
      {errorRuns.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-6 text-center">
          <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-full border border-emerald-200 bg-emerald-100 text-emerald-600">
            <span className="material-symbols-outlined text-[32px]">task_alt</span>
          </div>
          <p className="font-bold text-[#2a2640]">No recent errors</p>
          <p className="mt-1 px-4 text-sm text-[#777587]">
            Your connection is healthy.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {errorRuns.map((run) => (
            <div
              key={run.id}
              className="rounded-xl border border-rose-200 bg-rose-50 p-3"
            >
              <p className="text-[11px] font-semibold text-rose-700">
                {run.started_at
                  ? new Date(run.started_at).toLocaleString()
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-rose-800">{run.error_message}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Live Extraction Log ───────────────────────────────────────────────────────

type LogEntry = {
  id: number;
  timestamp: string;
  level: "INFO" | "WARN" | "ERROR";
  message: string;
};

function fmtTime(date?: Date): string {
  return (date ?? new Date()).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function LiveExtractionLog({ run }: { run: SyncRun | undefined }) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);
  const prevRunIdRef = useRef<string | undefined>(undefined);
  const prevSeenRef = useRef(-1);
  const prevStatusRef = useRef<string | undefined>(undefined);
  const nowRef = useRef(new Date());
  const [, setTick] = useState(0);

  // Tick the cursor clock while a run is active
  const isActive = run?.status === "running" || run?.status === "queued";
  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
      nowRef.current = new Date();
      setTick((n) => (n + 1) % 10_000);
    }, 1000);
    return () => clearInterval(id);
  }, [isActive]);

  // Accumulate log entries from run state changes
  useEffect(() => {
    if (!run) {
      prevRunIdRef.current = undefined;
      prevSeenRef.current = -1;
      prevStatusRef.current = undefined;
      return;
    }

    const mk = (level: LogEntry["level"], message: string, dateStr?: string | null): LogEntry => ({
      id: idRef.current++,
      timestamp: fmtTime(dateStr ? new Date(dateStr) : undefined),
      level,
      message,
    });

    const isNewRun = run.id !== prevRunIdRef.current;
    const statusChanged = run.status !== prevStatusRef.current;
    const seenChanged = run.items_seen !== prevSeenRef.current && run.items_seen > 0;
    const newEntries: LogEntry[] = [];

    if (isNewRun) {
      newEntries.push(mk("INFO", `Starting ${run.trigger_type} sync (v${run.sync_version})…`, run.started_at));
      if (run.items_seen > 0) {
        newEntries.push(mk("INFO", `${run.items_seen.toLocaleString()} items discovered, indexing…`));
      }
    } else if (statusChanged) {
      if (run.status === "completed") {
        newEntries.push(mk("INFO", `Sync complete — ${run.items_upserted.toLocaleString()} upserted, ${run.items_deleted.toLocaleString()} deleted.`, run.completed_at));
      } else if (run.status === "failed") {
        newEntries.push(mk("ERROR", run.error_message ?? "Sync failed with an unknown error."));
        for (const [key, val] of Object.entries(run.error_details ?? {})
          .filter(([, v]) => typeof v === "string" || typeof v === "number")
          .slice(0, 5)) {
          newEntries.push(mk("ERROR", `  ${key}: ${val}`));
        }
      } else if (run.status === "cancelled") {
        newEntries.push(mk("WARN", "Sync was cancelled."));
      }
    } else if (seenChanged) {
      const prev = prevSeenRef.current > -1 ? prevSeenRef.current : 0;
      const delta = run.items_seen - prev;
      newEntries.push(
        mk("INFO", delta > 0
          ? `+${delta.toLocaleString()} items scanned — ${run.items_upserted.toLocaleString()} indexed so far…`
          : `${run.items_seen.toLocaleString()} items seen — ${run.items_upserted.toLocaleString()} indexed…`,
        ),
      );
    }

    if (newEntries.length > 0) {
      setEntries((prev) => [...prev, ...newEntries].slice(-200));
    }

    prevRunIdRef.current = run.id;
    prevSeenRef.current = run.items_seen;
    prevStatusRef.current = run.status;
  }, [run]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [entries]);

  function handleDownload() {
    const text = entries.map((e) => `[${e.timestamp}] ${e.level}: ${e.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "sync-extraction-log.txt";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-lg font-bold text-[#2a2640]">Live Extraction Log</h4>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={handleDownload}
            disabled={entries.length === 0}
            title="Download log"
            className="rounded border border-[#d7d4e8] p-1.5 text-[#464555] transition-colors hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="material-symbols-outlined text-[18px]">download</span>
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand" : "Collapse"}
            className="rounded border border-[#d7d4e8] p-1.5 text-[#464555] transition-colors hover:bg-[#f5f2ff]"
          >
            <span className="material-symbols-outlined text-[18px]">
              {collapsed ? "open_in_full" : "close_fullscreen"}
            </span>
          </button>
        </div>
      </div>

      {!collapsed && (
        <div
          ref={logRef}
          className="h-64 overflow-y-auto rounded-lg bg-slate-900 p-4 font-mono text-[13px] leading-5 text-slate-300"
          style={{ scrollbarWidth: "thin", scrollbarColor: "#777587 transparent" }}
        >
          {entries.length === 0 ? (
            <span className="text-slate-500">
              {isActive ? "Initializing…" : "No sync activity yet. Start a sync to see logs here."}
            </span>
          ) : (
            entries.map((entry) => (
              <div key={entry.id} className="mb-1">
                <span className="text-slate-500">[{entry.timestamp}]</span>{" "}
                <span className={entry.level === "ERROR" ? "text-red-400" : entry.level === "WARN" ? "text-yellow-400" : "text-emerald-400"}>
                  {entry.level}:
                </span>{" "}
                {entry.message}
              </div>
            ))
          )}
          {isActive && (
            <div className="flex items-center gap-2 text-slate-400">
              <span className="text-slate-500">[{fmtTime(nowRef.current)}]</span>{" "}
              <span className="text-emerald-400">INFO:</span>{" "}
              Processing…{" "}
              <span className="inline-block h-[14px] w-[7px] animate-pulse bg-slate-400 align-middle" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PageErrorPanel({ error }: { error: ApiClientError }) {
  const label =
    error.status === 403
      ? "Permission denied"
      : error.status === 404
        ? "Connection not found"
        : "Unable to load connection";
  return (
    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900">
      <p className="font-semibold">{label}</p>
      <p className="mt-1">{getApiErrorMessage(error)}</p>
    </div>
  );
}

function HeaderActionsMenu({
  onReconnect,
  reconnectPending,
  onDisconnect,
  disconnectPending,
}: {
  onReconnect: () => void;
  reconnectPending: boolean;
  onDisconnect: () => void;
  disconnectPending: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="cursor-pointer inline-flex items-center justify-center rounded-xl border border-[#d7d4e8] p-2.5 text-[#464555] transition-colors hover:bg-[#f5f2ff]"
        aria-label="More actions"
      >
        <span className="material-symbols-outlined text-[20px]">more_vert</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-xl border border-[#d7d4e8] bg-white shadow-lg">
          <button
            type="button"
            disabled={reconnectPending}
            onClick={() => { setOpen(false); onReconnect(); }}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#2a2640] hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">refresh</span>
            {reconnectPending ? "Reconnecting…" : "Reconnect"}
          </button>
          <div className="mx-3 border-t border-[#e8e5f3]" />
          <button
            type="button"
            disabled={disconnectPending}
            onClick={() => { setOpen(false); onDisconnect(); }}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">link_off</span>
            {disconnectPending ? "Disconnecting…" : "Disconnect"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Props = { connectionId: string };

export function ConnectorConnectionDetailPage({ connectionId }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const connectionQuery = useQuery({
    queryKey: queryKeys.connectorConnection(connectionId),
    queryFn: () => getConnectorConnection(connectionId),
  });

  const jobsQuery = useQuery({
    queryKey: queryKeys.connectorSyncJobs(connectionId),
    queryFn: () => listSyncJobs(connectionId),
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.connectorSyncRuns(connectionId),
    queryFn: () => listSyncRuns(connectionId, 20),
    refetchInterval: (data) => {
      const items = data?.state?.data?.items;
      const hasActive =
        Array.isArray(items) &&
        items.some((r) => r.status === "queued" || r.status === "running");
      return hasActive ? 4000 : false;
    },
  });

  const syncMutation = useMutation({
    mutationFn: (jobId?: string) => triggerSyncNow(connectionId, jobId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      }),
  });

  const pauseMutation = useMutation({
    mutationFn: ({ jobId, status }: { jobId: string; status: "active" | "paused" }) =>
      updateSyncJobStatus(connectionId, jobId, status),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncJobs(connectionId),
      }),
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshConnectorCredential(connectionId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnection(connectionId),
      }),
  });

  const disconnectMutation = useMutation({
    mutationFn: () => deleteConnectorConnection(connectionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnections,
      });
      router.push("/connectors");
    },
  });

  const connection = connectionQuery.data;
  const jobs: SyncJob[] = jobsQuery.data?.items ?? [];
  const runs: SyncRun[] = runsQuery.data?.items ?? [];

  const activeJob = jobs.find((j) => j.status === "active") ?? jobs[0];
  const activeRun = runs.find(
    (r) => r.status === "running" || r.status === "queued",
  );

  // Poll the individual run at 2 s when active — gives finer-grained item-count updates
  // than the 4 s list poll, and is the source of truth for the live log.
  const activeRunDetailQuery = useQuery({
    queryKey: queryKeys.connectorSyncRun(activeRun?.id ?? ""),
    queryFn: () => getSyncRun(activeRun!.id),
    enabled: Boolean(activeRun?.id),
    refetchInterval: 2000,
  });
  const liveRun = activeRunDetailQuery.data ?? activeRun;

  const failedRunsCount = runs.filter((r) => r.status === "failed").length;
  const hasActiveRun = Boolean(activeRun);

  const itemsIndexed =
    connection?.source_count && connection.source_count > 0
      ? connection.source_count
      : (runs.find((r) => r.status === "completed")?.items_seen ?? 0);
  const syncRunsTotal = runsQuery.data?.total ?? runs.length;

  const prevHasActiveRunRef = useRef(false);
  useEffect(() => {
    if (prevHasActiveRunRef.current && !hasActiveRun) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnection(connectionId),
      });
    }
    prevHasActiveRunRef.current = hasActiveRun;
  }, [hasActiveRun, connectionId, queryClient]);

  if (connectionQuery.isLoading) {
    return (
      <div className="max-w-7xl p-8">
        <div className="rounded-2xl border border-dashed border-[#d7d4e8] bg-white p-6 text-sm text-[#68647b]">
          Loading connector details…
        </div>
      </div>
    );
  }

  if (connectionQuery.isError || !connection) {
    return (
      <div className="max-w-7xl space-y-4 p-8">
        <PageErrorPanel error={connectionQuery.error as ApiClientError} />
        <Link
          href="/connectors"
          className="inline-flex items-center gap-2 rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
        >
          <span className="material-symbols-outlined text-[18px]">arrow_back</span>
          Back to connectors
        </Link>
      </div>
    );
  }

  const safeDiagnostics = connection.diagnostics ?? {
    credential_status: null,
    scopes: [],
    expires_at: null,
  };

  return (
    <div className="max-w-7xl space-y-6 p-8">
      {/* ── Header card ── */}
      <div className="rounded-2xl border border-[#d7d4e8] bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex gap-5">
            <ProviderAvatar providerKey={connection.provider_key} />
            <div>
              <p className="mb-1 text-[11px] font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
                Connector Details
              </p>
              <h1 className="text-3xl font-extrabold text-[#2a2640]">
                {connection.display_name}
              </h1>
              <p className="mt-1 text-sm text-[#68647b]">
                {connection.provider.display_name}
                {connection.external_account_id
                  ? ` · ${connection.external_account_id}`
                  : ""}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <ConnectionStatusBadge status={connection.status} />
                {safeDiagnostics.credential_status && (
                  <span className="rounded-full border border-[#c3c0ff]/30 bg-[#c3c0ff]/20 px-3 py-1 text-[11px] font-bold text-[#3525cd]">
                    Credential {safeDiagnostics.credential_status}
                  </span>
                )}
                {safeDiagnostics.expires_at && (
                  <span className="text-[11px] font-medium text-[#777587]">
                    Expires{" "}
                    {new Date(safeDiagnostics.expires_at!).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => syncMutation.mutate(activeJob?.id)}
              disabled={syncMutation.isPending || hasActiveRun}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-[#3525cd] px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span
                className={`material-symbols-outlined text-[20px] ${syncMutation.isPending || hasActiveRun ? "animate-spin" : ""}`}
              >
                sync
              </span>
              {hasActiveRun ? "Syncing…" : syncMutation.isPending ? "Starting…" : "Sync now"}
            </button>
            <HeaderActionsMenu
              onReconnect={() => refreshMutation.mutate()}
              reconnectPending={refreshMutation.isPending}
              onDisconnect={() => disconnectMutation.mutate()}
              disconnectPending={disconnectMutation.isPending}
            />
          </div>
        </div>

        {connection.error_message && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {connection.error_message}
          </div>
        )}
      </div>

      {/* ── Stats grid ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Items Indexed"
          value={itemsIndexed.toLocaleString()}
          icon="article"
        />
        <StatCard
          label="Sync Jobs"
          value={syncRunsTotal}
          icon="repeat"
        />
        <StatCard
          label="Failed Runs"
          value={failedRunsCount}
          icon="error_outline"
          accent={failedRunsCount > 0}
        />
        <StatCard
          label="Last Successful Sync"
          value={formatRelative(connection.last_sync_at)}
          icon="update"
        />
      </div>

      {/* ── Main 2-col layout ── */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left column */}
        <div className="space-y-6 lg:col-span-2">
          {activeRun && <CurrentJobPanel run={activeRun} />}

          <LiveExtractionLog run={liveRun} />

          {/* ── Recent sync runs table ── */}
          <div className="overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-[#e8e5f3] px-6 py-4">
              <div>
                <h3 className="text-lg font-bold text-[#2a2640]">
                  Recent sync runs
                </h3>
                <p className="text-sm text-[#68647b]">
                  History of sync executions with item counts and error details.
                </p>
              </div>
            </div>

            {runsQuery.isLoading ? (
              <p className="px-6 py-5 text-sm text-[#68647b]">Loading runs…</p>
            ) : runs.length === 0 ? (
              <div className="px-6 py-10 text-center text-sm text-[#68647b]">
                No sync runs yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead className="bg-[#f5f2ff] text-[11px]">
                    <tr>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Trigger
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Seen
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Upserted
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Deleted
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Duration
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        Started
                      </th>
                      <th className="w-16 px-6 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e8e5f3]">
                    {runs.map((run) => (
                      <tr
                        key={run.id}
                        className="transition-colors hover:bg-[#faf9fe]"
                      >
                        <td className="px-6 py-3">
                          <RunStatusBadge status={run.status} />
                        </td>
                        <td className="px-6 py-3 text-[#4b4860]">
                          {run.trigger_type}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-[13px] text-[#2a2640] tabular-nums">
                          {run.items_seen}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-[13px] text-[#2a2640] tabular-nums">
                          {run.items_upserted}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-[13px] text-[#2a2640] tabular-nums">
                          {run.items_deleted}
                        </td>
                        <td className="px-6 py-3 text-[#4b4860]">
                          {formatDuration(run.started_at, run.completed_at)}
                        </td>
                        <td className="px-6 py-3 text-[#68647b]">
                          {run.started_at
                            ? new Date(run.started_at).toLocaleString()
                            : "—"}
                        </td>
                        <td className="px-6 py-3 text-right">
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

        {/* Right column */}
        <div className="space-y-6">
          <CredentialPanel
            diagnostics={safeDiagnostics}
            connectionStatus={connection.status}
          />

          <SchedulePanel
            job={activeJob}
            onPause={() =>
              activeJob &&
              pauseMutation.mutate({ jobId: activeJob.id, status: "paused" })
            }
            onResume={() =>
              activeJob &&
              pauseMutation.mutate({ jobId: activeJob.id, status: "active" })
            }
            isPending={pauseMutation.isPending}
          />

          <RecentErrorsPanel runs={runs} />
        </div>
      </div>
    </div>
  );
}
