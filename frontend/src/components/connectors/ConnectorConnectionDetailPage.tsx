"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { ConnectorConflictPanel } from "@/components/connectors/ConnectorConflictPanel";
import { ConnectorPermissionReviewPanel } from "@/components/connectors/ConnectorPermissionReviewPanel";
import {
  disconnectConnector,
  getConnectorConnection,
  refreshConnectorCredential,
} from "@/lib/api/connectors";
import {
  getSyncRun,
  listSyncJobs,
  listSyncRuns,
  retrySyncRun,
  triggerFullResync,
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

function relativeTimeValue(
  date: string | null,
): { value: number; unit: "minute" | "hour" | "day" } | null {
  if (!date) return null;
  const diff = Date.now() - new Date(date).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return { value: 0, unit: "minute" };
  if (mins < 60) return { value: -mins, unit: "minute" };
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return { value: -hrs, unit: "hour" };
  const days = Math.floor(hrs / 24);
  return { value: -days, unit: "day" };
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

function getSyncStatusLabel({
  connectionStatus,
  diagnosticsStatus,
  activeRun,
  latestRun,
  activeJob,
}: {
  connectionStatus: string;
  diagnosticsStatus: string | null;
  activeRun: SyncRun | undefined;
  latestRun: SyncRun | undefined;
  activeJob: SyncJob | undefined;
}): string {
  if (activeRun?.status === "running") {
    return "running";
  }
  if (activeRun?.status === "queued") {
    return "queued";
  }
  if (connectionStatus === "revoked" || connectionStatus === "disabled") {
    return "disconnected";
  }
  if (
    diagnosticsStatus === "error" ||
    diagnosticsStatus === "expired" ||
    diagnosticsStatus === "revoked"
  ) {
    return "needsAttention";
  }
  if (latestRun?.status === "failed") {
    return "lastSyncFailed";
  }
  if (activeJob?.status === "paused") {
    return "paused";
  }
  if (!activeJob) {
    return "noSchedule";
  }
  return "healthy";
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ProviderAvatar({ providerKey }: { providerKey: string }) {
  const brand = PROVIDER_BRAND[providerKey] ?? {
    color: "#3525cd",
    initial: "?",
  };
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
  const t = useTranslations("connectors.detail");
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-100 px-3 py-1 text-[11px] font-bold text-emerald-800">
        <span
          className="material-symbols-outlined text-[14px]"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          check_circle
        </span>
        {t("statuses.connected")}
      </span>
    );
  }
  if (status === "paused") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-100 px-3 py-1 text-[11px] font-bold text-amber-800">
        {t("statuses.paused")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-100 px-3 py-1 text-[11px] font-bold text-red-800">
      {t.has(`statuses.${status}`)
        ? t(`statuses.${status}`)
        : status.replace(/_/g, " ")}
    </span>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  const t = useTranslations("connectors.detail");
  const cls = RUN_STATUS_BADGE[status] ?? "bg-[#e4e1ee] text-[#464555]";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold ${cls}`}
    >
      {t.has(`statuses.${status}`) ? t(`statuses.${status}`) : status}
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
      <p className="mb-3 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
        {label}
      </p>
      <div className="flex items-end justify-between">
        <p
          className={`text-2xl font-extrabold ${accent ? "text-rose-600" : "text-[#2a2640]"}`}
        >
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
  const t = useTranslations("connectors.detail");
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
            <h4 className="text-lg font-bold text-[#2a2640]">
              {t("currentJob.title")}
            </h4>
            <p className="text-sm text-[#68647b] capitalize">
              {t("currentJob.inProgress", { trigger: run.trigger_type })}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-extrabold text-[#3525cd]">
              {progress !== null ? `${progress}%` : "—"}
            </p>
            <p className="text-[10px] font-bold tracking-widest text-[#777587] uppercase">
              {t("currentJob.progress")}
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
              {run.status === "running"
                ? t("currentJob.processing")
                : t("statuses.queued")}
            </span>
          </div>
          <span className="text-[#777587]">
            {t("table.seen")}:{" "}
            <span className="font-bold text-[#2a2640]">
              {run.items_seen.toLocaleString()}
            </span>{" "}
            · {t("table.upserted")}:{" "}
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
  const t = useTranslations("connectors.detail");
  const trustState =
    diagnostics.credential_status === "revoked" ||
    connectionStatus === "revoked"
      ? t("statuses.revoked")
      : diagnostics.credential_status === "error" ||
          connectionStatus === "error"
        ? t("statuses.needsAttention")
        : t("statuses.healthy");
  const isHealthy =
    diagnostics.credential_status !== "revoked" &&
    connectionStatus !== "revoked" &&
    diagnostics.credential_status !== "error" &&
    connectionStatus !== "error";

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h4 className="mb-5 text-lg font-bold text-[#2a2640]">
        {t("credentials.title")}
      </h4>
      <div className="space-y-4">
        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            {t("credentials.status")}
          </p>
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${isHealthy ? "bg-emerald-500" : "bg-rose-500"}`}
            />
            <span className="font-bold text-[#2a2640]">
              {diagnostics.credential_status
                ? t.has(`statuses.${diagnostics.credential_status}`)
                  ? t(`statuses.${diagnostics.credential_status}`)
                  : diagnostics.credential_status
                : t("statuses.unknown")}
            </span>
          </div>
        </div>

        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            {t("credentials.scopes")}
          </p>
          {diagnostics.scopes.length === 0 ? (
            <p className="text-sm text-[#68647b]">
              {t("credentials.noScopes")}
            </p>
          ) : (
            <div className="space-y-1">
              {diagnostics.scopes.map((scope) => (
                <p
                  key={scope}
                  className="rounded border border-[#d7d4e8] bg-[#f0ecf9] p-2 font-mono text-[11px] break-all text-[#3525cd]"
                >
                  {scope}
                </p>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#777587] uppercase">
            {t("credentials.trustState")}
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
  const t = useTranslations("connectors.detail");
  const badgeCls = !job
    ? "bg-[#e4e1ee] text-[#464555]"
    : job.status === "active"
      ? "bg-emerald-100 text-emerald-800"
      : job.status === "paused"
        ? "bg-amber-100 text-amber-800"
        : "bg-[#e4e1ee] text-[#464555]";

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <div className="mb-5 flex items-center justify-between">
        <h4 className="text-lg font-bold text-[#2a2640]">
          {t("schedule.title")}
        </h4>
        {job && (
          <span
            className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${badgeCls}`}
          >
            {t.has(`statuses.${job.status}`)
              ? t(`statuses.${job.status}`)
              : job.status}
          </span>
        )}
      </div>

      {job ? (
        <>
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[#d7d4e8] bg-[#f0ecf9]">
              <span className="material-symbols-outlined text-[#464555]">
                timer
              </span>
            </div>
            <div>
              <p className="text-2xl font-extrabold text-[#2a2640]">
                {job.schedule.type === "interval"
                  ? t("schedule.everyMinutes", {
                      count: job.schedule.interval_minutes ?? 60,
                    })
                  : t("schedule.manualOnly")}
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
            {job.status === "active"
              ? t("schedule.pause")
              : t("schedule.resume")}
          </button>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-[#d7d4e8] bg-[#faf9fe] p-4 text-sm text-[#68647b]">
          {t("schedule.none")}
        </div>
      )}
    </div>
  );
}

function RecentErrorsPanel({ runs }: { runs: SyncRun[] }) {
  const t = useTranslations("connectors.detail");
  const errorRuns = runs
    .filter((r) => r.status === "failed" && r.error_message)
    .slice(0, 5);

  return (
    <div className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
      <h4 className="mb-5 text-lg font-bold text-[#2a2640]">
        {t("errors.title")}
      </h4>
      {errorRuns.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-6 text-center">
          <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-full border border-emerald-200 bg-emerald-100 text-emerald-600">
            <span className="material-symbols-outlined text-[32px]">
              task_alt
            </span>
          </div>
          <p className="font-bold text-[#2a2640]">{t("errors.none")}</p>
          <p className="mt-1 px-4 text-sm text-[#777587]">
            {t("errors.healthy")}
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

function fmtTime(locale: string, date?: Date): string {
  return (date ?? new Date()).toLocaleTimeString(locale, {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function LiveExtractionLog({ run }: { run: SyncRun | undefined }) {
  const t = useTranslations("connectors.detail");
  const locale = useLocale();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);
  const prevRunIdRef = useRef<string | undefined>(undefined);
  const prevSeenRef = useRef(-1);
  const prevStatusRef = useRef<string | undefined>(undefined);
  const [, setTick] = useState(0);

  // Tick the cursor clock while a run is active
  const isActive = run?.status === "running" || run?.status === "queued";
  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
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

    const mk = (
      level: LogEntry["level"],
      message: string,
      dateStr?: string | null,
    ): LogEntry => ({
      id: idRef.current++,
      timestamp: fmtTime(locale, dateStr ? new Date(dateStr) : undefined),
      level,
      message,
    });

    const isNewRun = run.id !== prevRunIdRef.current;
    const statusChanged = run.status !== prevStatusRef.current;
    const seenChanged =
      run.items_seen !== prevSeenRef.current && run.items_seen > 0;
    const newEntries: LogEntry[] = [];

    if (isNewRun) {
      newEntries.push(
        mk(
          "INFO",
          t("log.starting", {
            trigger: run.trigger_type,
            version: run.sync_version,
          }),
          run.started_at,
        ),
      );
      if (run.items_seen > 0) {
        newEntries.push(
          mk("INFO", t("log.discovered", { count: run.items_seen })),
        );
      }
    } else if (statusChanged) {
      if (run.status === "completed") {
        newEntries.push(
          mk(
            "INFO",
            t("log.complete", {
              upserted: run.items_upserted,
              deleted: run.items_deleted,
            }),
            run.completed_at,
          ),
        );
      } else if (run.status === "failed") {
        newEntries.push(
          mk("ERROR", run.error_message ?? t("log.unknownError")),
        );
        for (const [key, val] of Object.entries(run.error_details ?? {})
          .filter(([, v]) => typeof v === "string" || typeof v === "number")
          .slice(0, 5)) {
          newEntries.push(mk("ERROR", `  ${key}: ${val}`));
        }
      } else if (run.status === "cancelled") {
        newEntries.push(mk("WARN", t("log.cancelled")));
      }
    } else if (seenChanged) {
      const prev = prevSeenRef.current > -1 ? prevSeenRef.current : 0;
      const delta = run.items_seen - prev;
      newEntries.push(
        mk(
          "INFO",
          delta > 0
            ? t("log.scanned", {
                delta,
                indexed: run.items_upserted,
              })
            : t("log.seen", {
                seen: run.items_seen,
                indexed: run.items_upserted,
              }),
        ),
      );
    }

    if (newEntries.length > 0) {
      queueMicrotask(() => {
        setEntries((prev) => [...prev, ...newEntries].slice(-200));
      });
    }

    prevRunIdRef.current = run.id;
    prevSeenRef.current = run.items_seen;
    prevStatusRef.current = run.status;
  }, [locale, run, t]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [entries]);

  function handleDownload() {
    const text = entries
      .map((e) => `[${e.timestamp}] ${e.level}: ${e.message}`)
      .join("\n");
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
        <h4 className="text-lg font-bold text-[#2a2640]">{t("log.title")}</h4>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={handleDownload}
            disabled={entries.length === 0}
            title={t("log.download")}
            className="rounded border border-[#d7d4e8] p-1.5 text-[#464555] transition-colors hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="material-symbols-outlined text-[18px]">
              download
            </span>
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? t("log.expand") : t("log.collapse")}
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
          style={{
            scrollbarWidth: "thin",
            scrollbarColor: "#777587 transparent",
          }}
        >
          {entries.length === 0 ? (
            <span className="text-slate-500">
              {isActive ? t("log.initializing") : t("log.empty")}
            </span>
          ) : (
            entries.map((entry) => (
              <div key={entry.id} className="mb-1">
                <span className="text-slate-500">[{entry.timestamp}]</span>{" "}
                <span
                  className={
                    entry.level === "ERROR"
                      ? "text-red-400"
                      : entry.level === "WARN"
                        ? "text-yellow-400"
                        : "text-emerald-400"
                  }
                >
                  {entry.level}:
                </span>{" "}
                {entry.message}
              </div>
            ))
          )}
          {isActive && (
            <div className="flex items-center gap-2 text-slate-400">
              <span className="text-slate-500">
                [{fmtTime(locale, new Date())}]
              </span>{" "}
              <span className="text-emerald-400">INFO:</span>{" "}
              {t("log.processing")}{" "}
              <span className="inline-block h-[14px] w-[7px] animate-pulse bg-slate-400 align-middle" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HeaderActionsMenu({
  onReconnect,
  reconnectPending,
  onFullResync,
  fullResyncPending,
  onDisconnect,
  disconnectPending,
}: {
  onReconnect: () => void;
  reconnectPending: boolean;
  onFullResync: () => void;
  fullResyncPending: boolean;
  onDisconnect: () => void;
  disconnectPending: boolean;
}) {
  const t = useTranslations("connectors.detail");
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
        className="inline-flex cursor-pointer items-center justify-center rounded-xl border border-[#d7d4e8] p-2.5 text-[#464555] transition-colors hover:bg-[#f5f2ff]"
        aria-label={t("actions.more")}
      >
        <span className="material-symbols-outlined text-[20px]">more_vert</span>
      </button>
      {open && (
        <div className="absolute top-full right-0 z-20 mt-1 w-44 overflow-hidden rounded-xl border border-[#d7d4e8] bg-white shadow-lg">
          <button
            type="button"
            disabled={reconnectPending}
            onClick={() => {
              setOpen(false);
              onReconnect();
            }}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#2a2640] hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">
              refresh
            </span>
            {reconnectPending
              ? t("actions.reconnecting")
              : t("actions.reconnect")}
          </button>
          <button
            type="button"
            disabled={fullResyncPending}
            onClick={() => {
              setOpen(false);
              onFullResync();
            }}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#2a2640] hover:bg-[#f5f2ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">
              restart_alt
            </span>
            {fullResyncPending ? t("actions.queuing") : t("actions.fullResync")}
          </button>
          <div className="mx-3 border-t border-[#e8e5f3]" />
          <button
            type="button"
            disabled={disconnectPending}
            onClick={() => {
              setOpen(false);
              onDisconnect();
            }}
            className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-sm font-medium text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">
              link_off
            </span>
            {disconnectPending
              ? t("actions.disconnecting")
              : t("actions.disconnect")}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Props = { connectionId: string };

export function ConnectorConnectionDetailPage({ connectionId }: Props) {
  const t = useTranslations("connectors.detail");
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

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
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      });
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const pauseMutation = useMutation({
    mutationFn: ({
      jobId,
      status,
    }: {
      jobId: string;
      status: "active" | "paused";
    }) => updateSyncJobStatus(connectionId, jobId, status),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncJobs(connectionId),
      });
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshConnectorCredential(connectionId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnection(connectionId),
      });
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const retryMutation = useMutation({
    mutationFn: (runId: string) => retrySyncRun(runId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnection(connectionId),
      });
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const fullResyncMutation = useMutation({
    mutationFn: (jobId?: string) => triggerFullResync(connectionId, jobId),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.connectorSyncRuns(connectionId),
      });
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const disconnectMutation = useMutation({
    mutationFn: () => disconnectConnector(connectionId),
    onSuccess: async () => {
      setActionError(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.connectorConnections,
      });
      router.push("/connectors");
    },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  });

  const connection = connectionQuery.data;
  const jobs: SyncJob[] = jobsQuery.data?.items ?? [];
  const runs: SyncRun[] = runsQuery.data?.items ?? [];

  const activeJob = jobs.find((j) => j.status === "active") ?? jobs[0];
  const activeRun = runs.find(
    (r) => r.status === "running" || r.status === "queued",
  );
  const latestRun = runs[0];
  const latestSuccessfulRun = runs.find((run) => run.status === "completed");
  const latestFailedRun = runs.find((run) => run.status === "failed");
  const indexedItemCount = connection?.indexed_document_count ?? 0;
  const syncStatusKey = getSyncStatusLabel({
    connectionStatus: connection?.status ?? "unknown",
    diagnosticsStatus: connection?.diagnostics?.credential_status ?? null,
    activeRun,
    latestRun,
    activeJob,
  });
  const nextSyncLabel = (() => {
    if (!activeJob) return t("time.notScheduled");
    if (activeJob.schedule.type === "manual_only") {
      return t("schedule.manualOnly");
    }
    const intervalMinutes = activeJob.schedule.interval_minutes ?? 60;
    const base = new Date(
      activeJob.last_run_at ?? activeJob.created_at,
    ).getTime();
    const nextDate = new Date(base + intervalMinutes * 60_000);
    return nextDate.toLocaleString(locale);
  })();
  const formatPastTime = (date: string | null): string => {
    const relative = relativeTimeValue(date);
    if (!relative) return t("time.never");
    if (relative.value === 0) return t("time.justNow");
    return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(
      relative.value,
      relative.unit,
    );
  };
  const lastSyncLabel = connection?.last_sync_at
    ? formatPastTime(connection.last_sync_at)
    : latestSuccessfulRun?.completed_at
      ? formatPastTime(latestSuccessfulRun.completed_at)
      : t("time.never");
  const lastError =
    connection?.error_message ?? latestFailedRun?.error_message ?? null;

  // Poll the individual run at 2 s when active — gives finer-grained item-count updates
  // than the 4 s list poll, and is the source of truth for the live log.
  const activeRunDetailQuery = useQuery({
    queryKey: queryKeys.connectorSyncRun(activeRun?.id ?? ""),
    queryFn: () => getSyncRun(activeRun!.id),
    enabled: Boolean(activeRun?.id),
    refetchInterval: 2000,
  });
  const liveRun = activeRunDetailQuery.data ?? activeRun;

  const hasActiveRun = Boolean(activeRun);

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
        <LoadingState title={t("loading")} />
      </div>
    );
  }

  if (connectionQuery.isError || !connection) {
    return (
      <div className="max-w-7xl space-y-4 p-8">
        <ErrorState
          error={connectionQuery.error}
          onRetry={() => void connectionQuery.refetch()}
        />
        <Link
          href="/connectors"
          className="inline-flex items-center gap-2 rounded-xl border border-[#d7d4e8] px-4 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f2ff]"
        >
          <span className="material-symbols-outlined text-[18px]">
            arrow_back
          </span>
          {t("back")}
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
                {t("eyebrow")}
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
                    {t("credentials.badge", {
                      status: safeDiagnostics.credential_status,
                    })}
                  </span>
                )}
                {safeDiagnostics.expires_at && (
                  <span className="text-[11px] font-medium text-[#777587]">
                    {t("credentials.expires", {
                      date: new Date(
                        safeDiagnostics.expires_at!,
                      ).toLocaleString(locale),
                    })}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Link
              href={`/chat?connection_id=${encodeURIComponent(connection.id)}&scope_mode=connectors`}
              className="inline-flex items-center gap-2 rounded-xl border border-[#d7d4e8] bg-white px-4 py-2.5 text-sm font-semibold text-[#3e376f] transition-colors hover:bg-[#f5f2ff]"
            >
              <span className="material-symbols-outlined text-[18px]">
                forum
              </span>
              {t("actions.askInChat")}
            </Link>
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
              {hasActiveRun
                ? t("actions.syncing")
                : syncMutation.isPending
                  ? t("actions.starting")
                  : t("actions.syncNow")}
            </button>
            <HeaderActionsMenu
              onReconnect={() => refreshMutation.mutate()}
              reconnectPending={refreshMutation.isPending}
              onFullResync={() => fullResyncMutation.mutate(activeJob?.id)}
              fullResyncPending={fullResyncMutation.isPending}
              onDisconnect={() => disconnectMutation.mutate()}
              disconnectPending={disconnectMutation.isPending}
            />
          </div>
        </div>

        {(actionError || lastError) && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {actionError ?? lastError}
          </div>
        )}
      </div>

      {/* ── Stats grid ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label={t("stats.syncStatus")}
          value={t(`syncStates.${syncStatusKey}`)}
          icon="sync"
        />
        <StatCard
          label={t("stats.indexedItems")}
          value={indexedItemCount.toLocaleString()}
          icon="dataset"
        />
        <StatCard
          label={t("stats.lastSync")}
          value={lastSyncLabel}
          icon="update"
        />
        <StatCard
          label={t("stats.nextSync")}
          value={nextSyncLabel}
          icon="schedule"
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
                  {t("runs.title")}
                </h3>
                <p className="text-sm text-[#68647b]">
                  {t("runs.description")}
                </p>
              </div>
            </div>

            {runsQuery.isLoading ? (
              <div className="px-6 py-4">
                <LoadingState compact title={t("runs.loading")} />
              </div>
            ) : runs.length === 0 ? (
              <div className="px-6 py-6">
                <EmptyState
                  compact
                  title={t("runs.emptyTitle")}
                  description={t("runs.emptyDescription")}
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead className="bg-[#f5f2ff] text-[11px]">
                    <tr>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.status")}
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.trigger")}
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.seen")}
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.upserted")}
                      </th>
                      <th className="px-6 py-3 text-right font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.deleted")}
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.duration")}
                      </th>
                      <th className="px-6 py-3 text-left font-bold tracking-[0.14em] text-[#777587] uppercase">
                        {t("table.started")}
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
                          <div className="flex items-center justify-end gap-3">
                            {run.status === "failed" && (
                              <button
                                type="button"
                                disabled={retryMutation.isPending}
                                onClick={() => retryMutation.mutate(run.id)}
                                className="text-xs font-semibold text-[#3525cd] hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {t("actions.retry")}
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
                          </div>
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
          <ConnectorConflictPanel connectionId={connection.id} />

          <ConnectorPermissionReviewPanel connectionId={connection.id} />

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
