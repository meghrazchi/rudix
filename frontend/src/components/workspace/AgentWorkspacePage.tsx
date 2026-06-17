"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AgentApprovalQueuePanel } from "@/components/workspace/AgentApprovalQueuePanel";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  cancelAgentRun,
  createAgentRun,
  decideAgentRunApproval,
  getAgentRun,
  listAgentRuns,
  type AgentRunDetailResponse,
  type AgentRunListItem,
  type AgentRuntimeMode,
} from "@/lib/api/agent";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3_000;
const RUN_LIST_LIMIT = 20;

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

// ── Status helpers ─────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, string> = {
  queued: "bg-amber-100 text-amber-800 border-amber-200",
  running: "bg-[#ece8ff] text-[#3525cd] border-[#d7d4e8]",
  completed: "bg-emerald-100 text-emerald-800 border-emerald-200",
  failed: "bg-rose-100 text-rose-800 border-rose-200",
  cancelled: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
};

function StatusBadge({ status }: { status: string }) {
  const cls =
    STATUS_BADGE[status] ?? "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${cls}`}
    >
      {status}
    </span>
  );
}

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

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

function formatCost(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toFixed(6)}`;
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

// ── Mode selector ─────────────────────────────────────────────────────────────

const MODES: { value: AgentRuntimeMode; label: string; description: string }[] =
  [
    { value: "auto", label: "Auto", description: "Let the agent decide" },
    {
      value: "answer",
      label: "Answer",
      description: "Grounded answer from sources",
    },
    {
      value: "summarize",
      label: "Summarize",
      description: "Condense source material",
    },
    {
      value: "compare",
      label: "Compare",
      description: "Side-by-side comparison",
    },
  ];

// ── Sub-components ─────────────────────────────────────────────────────────────

function StepRow({ step }: { step: AgentRunDetailResponse["steps"][number] }) {
  const [expanded, setExpanded] = useState(false);
  const hasInputs = Object.keys(step.inputs ?? {}).length > 0;
  const hasOutputs = Object.keys(step.outputs ?? {}).length > 0;

  return (
    <div className="rounded-lg border border-[#e4e1f2] bg-white">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 p-3 text-left hover:bg-[#f5f2ff]"
        aria-expanded={expanded}
      >
        <span className="mt-0.5 shrink-0">
          {step.status === "completed" ? (
            <span className="material-symbols-outlined text-[18px] text-emerald-600">
              check_circle
            </span>
          ) : step.status === "failed" ? (
            <span className="material-symbols-outlined text-[18px] text-rose-500">
              error
            </span>
          ) : step.status === "running" ? (
            <span className="material-symbols-outlined animate-spin text-[18px] text-[#3525cd]">
              progress_activity
            </span>
          ) : (
            <span className="material-symbols-outlined text-[18px] text-[#b0adbe]">
              radio_button_unchecked
            </span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[#2a2640]">
              {step.step_name}
            </span>
            <StatusBadge status={step.status} />
            {step.duration_ms != null && (
              <span className="text-[11px] text-[#777587]">
                {formatDurationMs(step.duration_ms)}
              </span>
            )}
          </div>
          {step.error_message && (
            <p className="mt-1 text-[11px] text-rose-700">{step.error_message}</p>
          )}
        </div>
        <span className="material-symbols-outlined shrink-0 text-[16px] text-[#9993b0]">
          {expanded ? "expand_less" : "expand_more"}
        </span>
      </button>

      {expanded && (hasInputs || hasOutputs) && (
        <div className="border-t border-[#e4e1f2] px-3 pb-3 pt-2">
          {hasInputs && (
            <div className="mb-2">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
                Inputs
              </p>
              <div className="space-y-0.5">
                {safeObjectEntries(step.inputs).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex gap-2 font-mono text-[11px] text-[#464555]"
                  >
                    <span className="shrink-0 text-[#9993b0]">{k}:</span>
                    <span className="min-w-0 break-all">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {hasOutputs && (
            <div>
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
                Outputs
              </p>
              <div className="space-y-0.5">
                {safeObjectEntries(step.outputs).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex gap-2 font-mono text-[11px] text-[#464555]"
                  >
                    <span className="shrink-0 text-[#9993b0]">{k}:</span>
                    <span className="min-w-0 break-all">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolCallRow({
  toolCall,
}: {
  toolCall: AgentRunDetailResponse["tool_calls"][number];
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-[#e4e1f2] bg-white text-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 p-3 text-left hover:bg-[#f5f2ff]"
        aria-expanded={expanded}
      >
        <span className="material-symbols-outlined shrink-0 text-[16px] text-[#5d58a8]">
          build
        </span>
        <span className="flex-1 truncate font-mono text-[12px] font-semibold text-[#2a2640]">
          {toolCall.tool_name}
        </span>
        <StatusBadge status={toolCall.status} />
        {toolCall.latency_ms != null && (
          <span className="text-[11px] text-[#777587]">
            {formatDurationMs(toolCall.latency_ms)}
          </span>
        )}
        <span className="material-symbols-outlined shrink-0 text-[16px] text-[#9993b0]">
          {expanded ? "expand_less" : "expand_more"}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-[#e4e1f2] px-3 pb-3 pt-2 space-y-2">
          <div className="flex flex-wrap gap-3 text-[11px] text-[#68647b]">
            <span>
              Surface:{" "}
              <span className="font-semibold text-[#2a2640]">
                {toolCall.surface}
              </span>
            </span>
            <span>
              Effect:{" "}
              <span className="font-semibold text-[#2a2640]">
                {toolCall.effect_policy}
              </span>
            </span>
            {toolCall.input_size_bytes != null && (
              <span>
                In:{" "}
                <span className="font-semibold text-[#2a2640]">
                  {toolCall.input_size_bytes}B
                </span>
              </span>
            )}
            {toolCall.output_size_bytes != null && (
              <span>
                Out:{" "}
                <span className="font-semibold text-[#2a2640]">
                  {toolCall.output_size_bytes}B
                </span>
              </span>
            )}
          </div>
          {Object.keys(toolCall.output ?? {}).length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
                Output
              </p>
              <div className="space-y-0.5">
                {safeObjectEntries(toolCall.output).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex gap-2 font-mono text-[11px] text-[#464555]"
                  >
                    <span className="shrink-0 text-[#9993b0]">{k}:</span>
                    <span className="min-w-0 break-all">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {Object.keys(toolCall.error ?? {}).length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-rose-500">
                Error
              </p>
              <div className="space-y-0.5">
                {safeObjectEntries(toolCall.error).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex gap-2 font-mono text-[11px] text-rose-700"
                  >
                    <span className="shrink-0 opacity-70">{k}:</span>
                    <span className="min-w-0 break-all">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ApprovalRow({
  approval,
  runId,
  onDecided,
}: {
  approval: AgentRunDetailResponse["approvals"][number];
  runId: string;
  onDecided: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decideMutation = useMutation({
    mutationFn: ({
      decision,
    }: {
      decision: "approved" | "rejected";
    }) =>
      decideAgentRunApproval(runId, approval.approval_id, {
        status: decision,
        reason: reason.trim() || null,
      }),
    onSuccess: () => {
      setError(null);
      onDecided();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const isPending = approval.status === "pending";

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="material-symbols-outlined text-[18px] text-amber-600">
          pending_actions
        </span>
        <span className="text-sm font-semibold text-[#2a2640]">
          Approval required
        </span>
        <StatusBadge status={approval.status} />
      </div>
      {approval.request_summary && (
        <p className="mt-1 text-[12px] text-[#464555]">
          {approval.request_summary}
        </p>
      )}
      {isPending && (
        <div className="mt-2 space-y-2">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Optional reason…"
            maxLength={600}
            className="w-full rounded border border-[#d7d4e8] px-2 py-1 text-sm outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => decideMutation.mutate({ decision: "approved" })}
              disabled={decideMutation.isPending}
              className="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => decideMutation.mutate({ decision: "rejected" })}
              disabled={decideMutation.isPending}
              className="rounded border border-[#d7d4e8] px-3 py-1 text-xs font-semibold text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-60"
            >
              Reject
            </button>
          </div>
          {error && <p className="text-[11px] text-rose-700">{error}</p>}
        </div>
      )}
      {!isPending && approval.decision_reason && (
        <p className="mt-1 text-[11px] text-[#68647b]">
          Reason: {approval.decision_reason}
        </p>
      )}
    </div>
  );
}

// ── Run detail pane ────────────────────────────────────────────────────────────

function RunDetailPane({ runId }: { runId: string }) {
  const queryClient = useQueryClient();

  const runQuery = useQuery({
    queryKey: queryKeys.agent.run(runId),
    queryFn: () => getAgentRun(runId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return POLL_INTERVAL_MS;
      return isTerminal(data.status) ? false : POLL_INTERVAL_MS;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelAgentRun(runId),
    onSuccess: async () => {
      await invalidateAfterMutation(queryClient, "agent.run.cancel");
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agent.run(runId),
      });
    },
  });

  const run = runQuery.data;

  const outcome = (run?.outcome ?? {}) as Record<string, unknown>;
  const answer =
    typeof outcome.answer === "string" ? outcome.answer : null;
  const citations = Array.isArray(outcome.citations) ? outcome.citations : [];
  const confidence = (outcome.confidence ?? {}) as Record<string, unknown>;
  const notFound = outcome.not_found === true;

  if (runQuery.isLoading) {
    return <LoadingState title="Loading run…" />;
  }

  if (runQuery.isError) {
    return (
      <ErrorState
        error={runQuery.error}
        onRetry={() => void runQuery.refetch()}
      />
    );
  }

  if (!run) return null;

  const pendingApprovals = run.approvals.filter((a) => a.status === "pending");
  const canCancel = !isTerminal(run.status);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            {!isTerminal(run.status) && (
              <span className="material-symbols-outlined animate-spin text-[16px] text-[#3525cd]">
                progress_activity
              </span>
            )}
          </div>
          {run.objective && (
            <p className="mt-1 text-sm text-[#68647b]">{run.objective}</p>
          )}
        </div>
        {canCancel && (
          <button
            type="button"
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="shrink-0 rounded border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs font-semibold text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-60"
          >
            {cancelMutation.isPending ? "Cancelling…" : "Cancel run"}
          </button>
        )}
      </div>

      {cancelMutation.isError && (
        <p className="text-xs text-rose-700">
          {getApiErrorMessage(cancelMutation.error)}
        </p>
      )}

      {/* Metrics bar */}
      <div className="flex flex-wrap gap-4 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3 text-[12px] text-[#68647b]">
        <span>
          Steps:{" "}
          <span className="font-semibold text-[#2a2640]">
            {run.steps.length}
          </span>
        </span>
        <span>
          Tool calls:{" "}
          <span className="font-semibold text-[#2a2640]">
            {run.tool_calls.length}
          </span>
        </span>
        <span>
          Cost:{" "}
          <span className="font-semibold text-[#2a2640]">
            {formatCost(run.total_cost_usd ? Number(run.total_cost_usd) : null)}
          </span>
        </span>
        {run.trace_request_id && (
          <span className="font-mono">
            Trace:{" "}
            <span className="font-semibold text-[#2a2640]">
              {run.trace_request_id.slice(0, 12)}…
            </span>
          </span>
        )}
        <span>
          Started:{" "}
          <span className="font-semibold text-[#2a2640]">
            {formatTs(run.started_at)}
          </span>
        </span>
        {run.completed_at && (
          <span>
            Completed:{" "}
            <span className="font-semibold text-[#2a2640]">
              {formatTs(run.completed_at)}
            </span>
          </span>
        )}
        {run.cancelled_at && (
          <span>
            Cancelled:{" "}
            <span className="font-semibold text-[#2a2640]">
              {formatTs(run.cancelled_at)}
            </span>
          </span>
        )}
      </div>

      {/* Pending approvals */}
      {pendingApprovals.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
            Pending approvals ({pendingApprovals.length})
          </h3>
          <div className="space-y-2">
            {pendingApprovals.map((a) => (
              <ApprovalRow
                key={a.approval_id}
                approval={a}
                runId={runId}
                onDecided={() =>
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.agent.run(runId),
                  })
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* Error */}
      {run.status === "failed" && run.error_message && (
        <div
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-3"
        >
          <p className="text-sm font-semibold text-rose-800">Run failed</p>
          <p className="mt-1 text-[12px] text-rose-700">{run.error_message}</p>
          {run.trace_request_id && (
            <p className="mt-2 font-mono text-[11px] text-rose-600">
              Trace ID: {run.trace_request_id}
            </p>
          )}
        </div>
      )}

      {/* Final answer */}
      {run.status === "completed" && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
            Answer
          </h3>
          {notFound ? (
            <EmptyState
              title="No answer found"
              description="The agent could not find relevant information in the available sources."
              compact
            />
          ) : answer ? (
            <div className="rounded-lg border border-[#e4e1f2] bg-white p-4">
              <p className="whitespace-pre-wrap text-sm text-[#2a2640]">
                {answer}
              </p>
              {Object.keys(confidence).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-[#68647b]">
                  {safeObjectEntries(confidence).map(([k, v]) => (
                    <span key={k}>
                      {k}:{" "}
                      <span className="font-semibold text-[#2a2640]">{v}</span>
                    </span>
                  ))}
                </div>
              )}
              {citations.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-[#9993b0]">
                    Citations ({citations.length})
                  </p>
                  <ol className="space-y-1">
                    {citations.map((c, i) => {
                      const citation = c as Record<string, unknown>;
                      const title =
                        typeof citation.title === "string"
                          ? citation.title
                          : typeof citation.document_id === "string"
                            ? citation.document_id
                            : `Source ${i + 1}`;
                      const snippet =
                        typeof citation.snippet === "string"
                          ? citation.snippet
                          : null;
                      return (
                        <li key={i} className="flex gap-2">
                          <span className="shrink-0 text-[11px] font-bold text-[#9993b0]">
                            [{i + 1}]
                          </span>
                          <div className="min-w-0">
                            <p className="text-[12px] font-semibold text-[#2a2640]">
                              {title}
                            </p>
                            {snippet && (
                              <p className="mt-0.5 line-clamp-2 text-[11px] text-[#68647b]">
                                {snippet}
                              </p>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              )}
            </div>
          ) : null}
        </section>
      )}

      {/* Step timeline */}
      {run.steps.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
            Steps ({run.steps.length})
          </h3>
          <div className="space-y-1.5">
            {run.steps.map((step) => (
              <StepRow key={step.step_id} step={step} />
            ))}
          </div>
        </section>
      )}

      {/* Tool calls */}
      {run.tool_calls.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
            Tool calls ({run.tool_calls.length})
          </h3>
          <div className="space-y-1.5">
            {run.tool_calls.map((tc) => (
              <ToolCallRow key={tc.tool_call_id} toolCall={tc} />
            ))}
          </div>
        </section>
      )}

      {/* All approvals (for audit view) */}
      {run.approvals.filter((a) => a.status !== "pending").length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
            Approval history
          </h3>
          <div className="space-y-1.5">
            {run.approvals
              .filter((a) => a.status !== "pending")
              .map((a) => (
                <ApprovalRow
                  key={a.approval_id}
                  approval={a}
                  runId={runId}
                  onDecided={() => {}}
                />
              ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ── Run list sidebar ───────────────────────────────────────────────────────────

function RunListItem({
  run,
  isSelected,
  onSelect,
}: {
  run: AgentRunListItem;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        isSelected
          ? "border-[#3525cd] bg-[#f0ecf9]"
          : "border-[#e4e1f2] bg-white hover:border-[#c7c3e0] hover:bg-[#faf9ff]"
      }`}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12px] font-semibold text-[#2a2640]">
            {run.objective ?? "Untitled run"}
          </p>
          <p className="mt-0.5 text-[10px] text-[#9993b0]">
            {formatTs(run.created_at)}
          </p>
        </div>
        <StatusBadge status={run.status} />
      </div>
      {run.error_message && (
        <p className="mt-1 truncate text-[10px] text-rose-600">
          {run.error_message}
        </p>
      )}
    </button>
  );
}

// ── New run form ───────────────────────────────────────────────────────────────

type NewRunFormProps = {
  onRunCreated: (runId: string) => void;
};

function NewRunForm({ onRunCreated }: NewRunFormProps) {
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState<AgentRuntimeMode>("auto");
  const [maxSteps, setMaxSteps] = useState(12);
  const [maxToolCalls, setMaxToolCalls] = useState(30);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      createAgentRun({
        agentic_mode: true,
        request: {
          objective: objective.trim(),
          mode,
          budget: {
            max_steps: maxSteps,
            max_tool_calls: maxToolCalls,
          },
        },
      }),
    onSuccess: (data) => {
      setObjective("");
      setError(null);
      onRunCreated(data.run.run_id);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const canSubmit =
    objective.trim().length >= 3 && !createMutation.isPending;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) createMutation.mutate();
      }}
      className="space-y-3"
    >
      <div>
        <label
          htmlFor="agent-objective"
          className="mb-1 block text-[11px] font-bold uppercase tracking-wide text-[#9993b0]"
        >
          Objective
        </label>
        <textarea
          id="agent-objective"
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          rows={3}
          maxLength={4000}
          placeholder="Describe what the agent should accomplish…"
          className="w-full resize-none rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm text-[#2a2640] outline-none placeholder:text-[#b0adbe] focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
        />
        <p className="mt-0.5 text-right text-[10px] text-[#b0adbe]">
          {objective.length}/4000
        </p>
      </div>

      <div>
        <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
          Mode
        </p>
        <div className="flex flex-wrap gap-1.5">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => setMode(m.value)}
              title={m.description}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                mode === m.value
                  ? "border-[#3525cd] bg-[#3525cd] text-white"
                  : "border-[#d7d4e8] bg-white text-[#464555] hover:border-[#3525cd] hover:text-[#3525cd]"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <details className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff]">
        <summary className="cursor-pointer px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-[#9993b0] select-none hover:bg-[#f0ecf9]">
          Budget controls
        </summary>
        <div className="space-y-3 px-3 pb-3 pt-2">
          <div>
            <label
              htmlFor="max-steps"
              className="mb-1 block text-[11px] text-[#68647b]"
            >
              Max steps: <span className="font-semibold">{maxSteps}</span>
            </label>
            <input
              id="max-steps"
              type="range"
              min={1}
              max={50}
              value={maxSteps}
              onChange={(e) => setMaxSteps(Number(e.target.value))}
              className="w-full accent-[#3525cd]"
            />
          </div>
          <div>
            <label
              htmlFor="max-tool-calls"
              className="mb-1 block text-[11px] text-[#68647b]"
            >
              Max tool calls:{" "}
              <span className="font-semibold">{maxToolCalls}</span>
            </label>
            <input
              id="max-tool-calls"
              type="range"
              min={1}
              max={100}
              value={maxToolCalls}
              onChange={(e) => setMaxToolCalls(Number(e.target.value))}
              className="w-full accent-[#3525cd]"
            />
          </div>
        </div>
      </details>

      {error && (
        <p role="alert" className="text-xs text-rose-700">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-lg bg-[#3525cd] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#2a1da8] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {createMutation.isPending ? "Starting run…" : "Start agent run"}
      </button>
    </form>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function AgentWorkspacePage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const runsQuery = useQuery({
    queryKey: queryKeys.agent.runs({ limit: RUN_LIST_LIMIT }),
    queryFn: () => listAgentRuns({ limit: RUN_LIST_LIMIT }),
    refetchInterval: POLL_INTERVAL_MS,
  });

  const handleRunCreated = useCallback((runId: string) => {
    setSelectedRunId(runId);
    setTimeout(() => {
      detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  }, []);

  const runs = runsQuery.data?.runs ?? [];

  useEffect(() => {
    if (selectedRunId === null && runs.length > 0) {
      setSelectedRunId(runs[0]!.run_id);
    }
  }, [runs, selectedRunId]);

  return (
    <div className="flex min-h-0 flex-col gap-4 px-4 py-6 sm:px-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-extrabold text-[#2a2640]">
          Agent Workspace
        </h1>
        <p className="mt-1 text-sm text-[#68647b]">
          Run agentic tasks, inspect step-by-step plans, tool calls, and
          grounded answers.
        </p>
      </div>

      {/* Approval queue — shown when there are pending items */}
      <AgentApprovalQueuePanel />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        {/* Left: form + run list */}
        <div className="space-y-4">
          {/* New run form */}
          <section className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
              New run
            </h2>
            <NewRunForm onRunCreated={handleRunCreated} />
          </section>

          {/* Run list */}
          <section className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wide text-[#9993b0]">
              Recent runs
              {runsQuery.data && (
                <span className="ml-1 font-normal normal-case text-[#b0adbe]">
                  ({runsQuery.data.total} total)
                </span>
              )}
            </h2>

            {runsQuery.isLoading && (
              <LoadingState title="Loading runs…" compact />
            )}
            {runsQuery.isError && (
              <ErrorState
                error={runsQuery.error}
                onRetry={() => void runsQuery.refetch()}
                compact
              />
            )}
            {!runsQuery.isLoading && !runsQuery.isError && runs.length === 0 && (
              <EmptyState
                title="No runs yet"
                description="Start your first agent run above."
                compact
              />
            )}
            {runs.length > 0 && (
              <div className="space-y-1.5">
                {runs.map((run) => (
                  <RunListItem
                    key={run.run_id}
                    run={run}
                    isSelected={selectedRunId === run.run_id}
                    onSelect={() => setSelectedRunId(run.run_id)}
                  />
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right: run detail */}
        <div ref={detailRef}>
          {selectedRunId ? (
            <section className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
              <RunDetailPane key={selectedRunId} runId={selectedRunId} />
            </section>
          ) : (
            <section className="rounded-xl border border-[#d7d4e8] bg-[#faf9ff] p-8 text-center shadow-sm">
              <span className="material-symbols-outlined text-[48px] text-[#d7d4e8]">
                robot_2
              </span>
              <p className="mt-2 text-sm font-semibold text-[#9993b0]">
                Select or start a run to inspect it here
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
