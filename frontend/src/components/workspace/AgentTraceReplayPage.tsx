"use client";

import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  exportAgentRunTrace,
  getAgentRunTrace,
  shareAgentRunTrace,
  type AgentTraceEvent,
  type AgentTraceResponse,
  type AgentTraceShareResponse,
} from "@/lib/api/agent";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

// ── Constants ─────────────────────────────────────────────────────────────────

const EVENT_TYPE_BADGE: Record<
  string,
  { label: string; color: string; icon: string }
> = {
  run_started: {
    label: "Run Started",
    color: "bg-[#ece8ff] text-[#3525cd] border-[#d7d4e8]",
    icon: "play_circle",
  },
  run_completed: {
    label: "Run Completed",
    color: "bg-emerald-100 text-emerald-800 border-emerald-200",
    icon: "check_circle",
  },
  run_failed: {
    label: "Run Failed",
    color: "bg-rose-100 text-rose-800 border-rose-200",
    icon: "error",
  },
  run_cancelled: {
    label: "Run Cancelled",
    color: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
    icon: "cancel",
  },
  step_started: {
    label: "Step Started",
    color: "bg-blue-50 text-blue-700 border-blue-200",
    icon: "arrow_forward",
  },
  step_completed: {
    label: "Step Done",
    color: "bg-emerald-50 text-emerald-700 border-emerald-200",
    icon: "task_alt",
  },
  step_failed: {
    label: "Step Failed",
    color: "bg-rose-50 text-rose-700 border-rose-200",
    icon: "close",
  },
  step_skipped: {
    label: "Skipped",
    color: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
    icon: "skip_next",
  },
  tool_called: {
    label: "Tool Called",
    color: "bg-amber-50 text-amber-800 border-amber-200",
    icon: "build",
  },
  tool_result: {
    label: "Tool Result",
    color: "bg-amber-100 text-amber-800 border-amber-200",
    icon: "output",
  },
  approval_requested: {
    label: "Approval Requested",
    color: "bg-orange-50 text-orange-700 border-orange-200",
    icon: "pending_actions",
  },
  approval_decided: {
    label: "Approval Decided",
    color: "bg-teal-50 text-teal-700 border-teal-200",
    icon: "gavel",
  },
};

function eventMeta(eventType: string) {
  return (
    EVENT_TYPE_BADGE[eventType] ?? {
      label: eventType,
      color: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
      icon: "info",
    }
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTs(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function safeObjectEntries(
  value: Record<string, unknown> | null | undefined,
): [string, string][] {
  if (!value || typeof value !== "object") return [];
  return Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => [
      k,
      typeof v === "object" ? JSON.stringify(v) : String(v),
    ]);
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function EventTypeBadge({ eventType }: { eventType: string }) {
  const meta = eventMeta(eventType);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${meta.color}`}
    >
      <span className="material-symbols-outlined text-[12px]">{meta.icon}</span>
      {meta.label}
    </span>
  );
}

function DataGrid({
  data,
}: {
  data: Record<string, unknown> | null | undefined;
}) {
  const entries = safeObjectEntries(data);
  if (entries.length === 0) return null;
  return (
    <div className="space-y-0.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2 font-mono text-[11px] text-[#464555]">
          <span className="shrink-0 text-[#9993b0]">{k}:</span>
          <span className="min-w-0 break-all">{v}</span>
        </div>
      ))}
    </div>
  );
}

function TraceEventRow({ event }: { event: AgentTraceEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasData = Object.keys(event.data ?? {}).length > 0;

  return (
    <div className="rounded-lg border border-[#e4e1f2] bg-white">
      <button
        type="button"
        onClick={() => hasData && setExpanded((v) => !v)}
        className={`flex w-full items-start gap-3 p-3 text-left ${hasData ? "hover:bg-[#f5f2ff]" : ""}`}
        aria-expanded={expanded}
      >
        <div className="mt-0.5 shrink-0 w-2 h-2 rounded-full bg-[#b0adbe] mt-1.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <EventTypeBadge eventType={event.event_type} />
            <span className="text-[11px] text-[#777587]">
              {formatTs(event.timestamp)}
            </span>
            {event.data?.step_name && (
              <span className="font-mono text-[11px] text-[#2a2640]">
                {String(event.data.step_name)}
              </span>
            )}
            {event.data?.tool_name && (
              <span className="font-mono text-[11px] font-semibold text-[#5d58a8]">
                {String(event.data.tool_name)}
              </span>
            )}
            {event.data?.duration_ms != null && (
              <span className="text-[11px] text-[#777587]">
                {formatDurationMs(event.data.duration_ms as number)}
              </span>
            )}
            {event.data?.latency_ms != null && (
              <span className="text-[11px] text-[#777587]">
                {formatDurationMs(event.data.latency_ms as number)}
              </span>
            )}
          </div>
          {event.data?.error_message && (
            <p className="mt-1 text-[11px] text-rose-700">
              {String(event.data.error_message)}
            </p>
          )}
        </div>
        {hasData && (
          <span className="material-symbols-outlined shrink-0 text-[16px] text-[#9993b0]">
            {expanded ? "expand_less" : "expand_more"}
          </span>
        )}
      </button>

      {expanded && hasData && (
        <div className="border-t border-[#e4e1f2] px-3 pb-3 pt-2">
          <DataGrid data={event.data as Record<string, unknown>} />
        </div>
      )}
    </div>
  );
}

function RunSummaryHeader({
  trace,
}: {
  trace: AgentTraceResponse;
}) {
  return (
    <div className="rounded-lg border border-[#e4e1f2] bg-white p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
            Objective
          </p>
          <p className="mt-0.5 text-sm font-medium text-[#2a2640]">
            {trace.objective ?? "(no objective)"}
          </p>
        </div>
        <div className="flex flex-wrap gap-4 text-[11px] text-[#68647b]">
          <span>
            Status:{" "}
            <span className="font-semibold text-[#2a2640]">{trace.status}</span>
          </span>
          <span>
            Surface:{" "}
            <span className="font-semibold text-[#2a2640]">{trace.surface}</span>
          </span>
          {trace.total_cost_usd && (
            <span>
              Cost:{" "}
              <span className="font-semibold text-[#2a2640]">
                ${parseFloat(trace.total_cost_usd).toFixed(6)}
              </span>
            </span>
          )}
          <span>
            Steps:{" "}
            <span className="font-semibold text-[#2a2640]">{trace.step_count}</span>
          </span>
          <span>
            Tool Calls:{" "}
            <span className="font-semibold text-[#2a2640]">{trace.tool_call_count}</span>
          </span>
        </div>
      </div>
      {trace.error_message && (
        <div className="mt-3 rounded-md bg-rose-50 border border-rose-200 px-3 py-2 text-[12px] text-rose-700">
          <span className="font-semibold">Error: </span>
          {trace.error_message}
        </div>
      )}
      {trace.redacted && (
        <div className="mt-3 flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] text-amber-700">
          <span className="material-symbols-outlined text-[14px]">privacy_tip</span>
          Some fields have been redacted by your organisation&apos;s trace retention policy.
        </div>
      )}
      {trace.shared_via_token && (
        <div className="mt-3 flex items-center gap-1.5 rounded-md bg-[#f0eeff] border border-[#d7d4e8] px-3 py-2 text-[11px] text-[#3525cd]">
          <span className="material-symbols-outlined text-[14px]">link</span>
          This trace was accessed via a share link. All sensitive fields are redacted.
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-[#777587]">
        <span>Started: {formatTs(trace.started_at)}</span>
        {trace.completed_at && (
          <span>Completed: {formatTs(trace.completed_at)}</span>
        )}
        {trace.cancelled_at && (
          <span>Cancelled: {formatTs(trace.cancelled_at)}</span>
        )}
        {trace.trace_request_id && (
          <span>
            Trace ID:{" "}
            <span className="font-mono">{trace.trace_request_id}</span>
          </span>
        )}
      </div>
    </div>
  );
}

function ShareModal({
  runId,
  onClose,
  onShared,
}: {
  runId: string;
  onClose: () => void;
  onShared: (result: AgentTraceShareResponse) => void;
}) {
  const [label, setLabel] = useState("");
  const [expiresInHours, setExpiresInHours] = useState(48);
  const [error, setError] = useState<string | null>(null);

  const shareMutation = useMutation({
    mutationFn: () =>
      shareAgentRunTrace(runId, {
        label: label.trim() || null,
        expires_in_hours: expiresInHours,
      }),
    onSuccess: onShared,
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Share trace"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-base font-semibold text-[#2a2640]">Share Trace</h2>
        <p className="mt-1 text-[12px] text-[#777587]">
          Generate a time-limited link for support review. All sensitive fields
          are fully redacted in shared traces.
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <label
              htmlFor="share-label"
              className="block text-[11px] font-bold uppercase tracking-wide text-[#9993b0]"
            >
              Label (optional)
            </label>
            <input
              id="share-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Support ticket #123"
              maxLength={200}
              className="mt-1 w-full rounded-md border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
            />
          </div>
          <div>
            <label
              htmlFor="share-expiry"
              className="block text-[11px] font-bold uppercase tracking-wide text-[#9993b0]"
            >
              Expires in
            </label>
            <select
              id="share-expiry"
              value={expiresInHours}
              onChange={(e) => setExpiresInHours(Number(e.target.value))}
              className="mt-1 w-full rounded-md border border-[#d7d4e8] bg-white px-3 py-1.5 text-sm text-[#2a2640] focus:border-[#3525cd] focus:outline-none"
            >
              <option value={24}>24 hours</option>
              <option value={48}>48 hours</option>
              <option value={168}>7 days</option>
              <option value={720}>30 days</option>
            </select>
          </div>
        </div>

        {error && (
          <p className="mt-3 text-[11px] text-rose-600">{error}</p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[#d7d4e8] px-4 py-1.5 text-sm text-[#464555] hover:bg-[#f5f2ff]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => shareMutation.mutate()}
            disabled={shareMutation.isPending}
            className="rounded-md bg-[#3525cd] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#2e1fb8] disabled:opacity-50"
          >
            {shareMutation.isPending ? "Creating…" : "Create Link"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ShareResultPanel({
  result,
  onClose,
}: {
  result: AgentTraceShareResponse;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    await navigator.clipboard.writeText(result.share_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Share link created"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center gap-2 text-emerald-700">
          <span className="material-symbols-outlined text-[20px]">check_circle</span>
          <h2 className="text-base font-semibold">Share Link Created</h2>
        </div>
        <p className="mt-2 text-[12px] text-[#777587]">
          This link expires at{" "}
          <span className="font-semibold">{formatTs(result.expires_at)}</span>.
          Share it with support — sensitive content is fully redacted.
        </p>
        <div className="mt-4 flex items-center gap-2 rounded-md border border-[#d7d4e8] bg-[#f9f8ff] px-3 py-2">
          <span className="flex-1 truncate font-mono text-[11px] text-[#2a2640]">
            {result.share_url}
          </span>
          <button
            type="button"
            onClick={copyLink}
            className="shrink-0 text-[#3525cd] hover:text-[#2e1fb8]"
            aria-label="Copy link"
          >
            <span className="material-symbols-outlined text-[18px]">
              {copied ? "check" : "content_copy"}
            </span>
          </button>
        </div>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-[#3525cd] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[#2e1fb8]"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function AgentTraceReplayPage({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareResult, setShareResult] = useState<AgentTraceShareResponse | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const {
    data: trace,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: queryKeys.agent.trace(runId),
    queryFn: () => getAgentRunTrace(runId),
    enabled: !!runId,
  });

  const exportMutation = useMutation({
    mutationFn: () => exportAgentRunTrace(runId),
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `trace-${runId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
    onError: (err) => setExportError(getApiErrorMessage(err)),
  });

  if (isLoading) return <LoadingState />;
  if (isError || !trace)
    return (
      <ErrorState message={getApiErrorMessage(error) ?? "Could not load trace."} />
    );

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-[#2a2640]">Trace Replay</h1>
          <p className="text-[11px] text-[#777587]">
            Run{" "}
            <span className="font-mono">{runId.slice(0, 8)}…</span>
          </p>
        </div>
        <div className="flex gap-2">
          {exportError && (
            <span className="text-[11px] text-rose-600">{exportError}</span>
          )}
          <button
            type="button"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
            className="flex items-center gap-1.5 rounded-md border border-[#d7d4e8] px-3 py-1.5 text-[12px] font-semibold text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[15px]">download</span>
            {exportMutation.isPending ? "Exporting…" : "Export"}
          </button>
          <button
            type="button"
            onClick={() => setShowShareModal(true)}
            className="flex items-center gap-1.5 rounded-md bg-[#3525cd] px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-[#2e1fb8]"
          >
            <span className="material-symbols-outlined text-[15px]">share</span>
            Share
          </button>
        </div>
      </div>

      {/* Run summary */}
      <RunSummaryHeader trace={trace} />

      {/* Timeline */}
      <div className="mt-6">
        <p className="mb-3 text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
          Timeline · {trace.total_events} events
        </p>

        {trace.timeline.length === 0 ? (
          <EmptyState message="No timeline events recorded for this run." />
        ) : (
          <div className="space-y-1.5 relative before:absolute before:left-[7px] before:top-0 before:bottom-0 before:w-px before:bg-[#e4e1f2]">
            {trace.timeline.map((event, idx) => (
              <TraceEventRow key={idx} event={event} />
            ))}
          </div>
        )}
      </div>

      {/* Share modals */}
      {showShareModal && !shareResult && (
        <ShareModal
          runId={runId}
          onClose={() => setShowShareModal(false)}
          onShared={(result) => {
            setShareResult(result);
            setShowShareModal(false);
          }}
        />
      )}
      {shareResult && (
        <ShareResultPanel
          result={shareResult}
          onClose={() => setShareResult(null)}
        />
      )}
    </div>
  );
}
