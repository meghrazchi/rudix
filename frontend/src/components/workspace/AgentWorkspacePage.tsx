"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { AgentApprovalQueuePanel } from "@/components/workspace/AgentApprovalQueuePanel";
import { EffectivePolicyPanel } from "@/components/admin/agent-policy/EffectivePolicyPanel";
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
import { listCollections } from "@/lib/api/collections";
import { listAvailableConnectorConnections } from "@/lib/api/connectors";
import { listDocuments } from "@/lib/api/documents";
import {
  previewWorkflowPlan,
  type WorkflowPlanPreviewResponse,
  type WorkflowType,
} from "@/lib/api/workflow-planner";
import type { ChatSourceScopeRequest } from "@/lib/api/chat";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { SourceScopeSelector } from "@/components/chat/SourceScopeSelector";

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3_000;
const RUN_LIST_LIMIT = 20;

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

const WORKFLOW_MODE_OPTIONS = [
  { value: "auto" },
  { value: "answer" },
  { value: "summarize" },
  { value: "compare" },
] as const;

type WorkflowScopeMode =
  | "all"
  | "documents"
  | "collection"
  | "connectors"
  | "none";

const WORKFLOW_PRESETS: {
  workflowType: WorkflowType;
  mode: AgentRuntimeMode;
  rerank: boolean;
}[] = [
  {
    workflowType: "audit_evidence_pack",
    mode: "compare",
    rerank: true,
  },
  {
    workflowType: "policy_comparison",
    mode: "compare",
    rerank: true,
  },
  {
    workflowType: "contract_obligation_analysis",
    mode: "compare",
    rerank: true,
  },
  {
    workflowType: "onboarding_faq_preparation",
    mode: "summarize",
    rerank: false,
  },
  {
    workflowType: "connector_content_summarization",
    mode: "summarize",
    rerank: true,
  },
  {
    workflowType: "low_confidence_answer_investigation",
    mode: "answer",
    rerank: true,
  },
];

// ── Status helpers ─────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, string> = {
  queued: "bg-amber-100 text-amber-800 border-amber-200",
  running: "bg-[#ece8ff] text-[#3525cd] border-[#d7d4e8]",
  completed: "bg-emerald-100 text-emerald-800 border-emerald-200",
  failed: "bg-rose-100 text-rose-800 border-rose-200",
  cancelled: "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]",
};

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("agentWorkspace");
  const cls =
    STATUS_BADGE[status] ?? "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${cls}`}
    >
      {t(`statuses.${status}`)}
    </span>
  );
}

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

function formatTs(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(locale);
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

function findWorkflowPreset(workflowType: WorkflowType) {
  return (
    WORKFLOW_PRESETS.find((preset) => preset.workflowType === workflowType) ??
    WORKFLOW_PRESETS[0]
  );
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

function formatMoney(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toFixed(2)}`;
}

function getWorkflowPresetIcon(workflowType: WorkflowType): string {
  switch (workflowType) {
    case "audit_evidence_pack":
      return "assignment_turned_in";
    case "policy_comparison":
      return "compare_arrows";
    case "contract_obligation_analysis":
      return "description";
    case "onboarding_faq_preparation":
      return "quiz";
    case "connector_content_summarization":
      return "hub";
    case "low_confidence_answer_investigation":
      return "verified";
    default:
      return "smart_toy";
  }
}

function getBudgetEstimate(
  objective: string,
  maxSteps: number,
  maxTotalCostUsd: number,
): { steps: number; costUsd: number } {
  const trimmed = objective.trim();
  const contentFactor = trimmed.length > 0 ? Math.ceil(trimmed.length / 80) : 4;
  const steps = Math.min(maxSteps, Math.max(4, contentFactor));
  const rawCost = Math.max(0.4, steps * 0.15);
  const costUsd = Math.min(maxTotalCostUsd, Math.round(rawCost * 100) / 100);
  return {
    steps,
    costUsd,
  };
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StepRow({ step }: { step: AgentRunDetailResponse["steps"][number] }) {
  const t = useTranslations("agentWorkspace");
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
            <p className="mt-1 text-[11px] text-rose-700">
              {step.error_message}
            </p>
          )}
        </div>
        <span className="material-symbols-outlined shrink-0 text-[16px] text-[#9993b0]">
          {expanded ? "expand_less" : "expand_more"}
        </span>
      </button>

      {expanded && (hasInputs || hasOutputs) && (
        <div className="border-t border-[#e4e1f2] px-3 pt-2 pb-3">
          {hasInputs && (
            <div className="mb-2">
              <p className="mb-1 text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("inputs")}
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
              <p className="mb-1 text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("outputs")}
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
  const t = useTranslations("agentWorkspace");
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
        <div className="space-y-2 border-t border-[#e4e1f2] px-3 pt-2 pb-3">
          <div className="flex flex-wrap gap-3 text-[11px] text-[#68647b]">
            <span>
              {t("surface")}:{" "}
              <span className="font-semibold text-[#2a2640]">
                {toolCall.surface}
              </span>
            </span>
            <span>
              {t("effect")}:{" "}
              <span className="font-semibold text-[#2a2640]">
                {toolCall.effect_policy}
              </span>
            </span>
            {toolCall.input_size_bytes != null && (
              <span>
                {t("inputShort")}:{" "}
                <span className="font-semibold text-[#2a2640]">
                  {toolCall.input_size_bytes}B
                </span>
              </span>
            )}
            {toolCall.output_size_bytes != null && (
              <span>
                {t("outputShort")}:{" "}
                <span className="font-semibold text-[#2a2640]">
                  {toolCall.output_size_bytes}B
                </span>
              </span>
            )}
          </div>
          {Object.keys(toolCall.output ?? {}).length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("outputs")}
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
              <p className="mb-1 text-[10px] font-bold tracking-wide text-rose-500 uppercase">
                {t("error")}
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
  const t = useTranslations("agentWorkspace");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decideMutation = useMutation({
    mutationFn: ({ decision }: { decision: "approved" | "rejected" }) =>
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
          {t("approval.required")}
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
            placeholder={t("approval.optionalReason")}
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
              {t("approval.approve")}
            </button>
            <button
              type="button"
              onClick={() => decideMutation.mutate({ decision: "rejected" })}
              disabled={decideMutation.isPending}
              className="rounded border border-[#d7d4e8] px-3 py-1 text-xs font-semibold text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-60"
            >
              {t("approval.reject")}
            </button>
          </div>
          {error && <p className="text-[11px] text-rose-700">{error}</p>}
        </div>
      )}
      {!isPending && approval.decision_reason && (
        <p className="mt-1 text-[11px] text-[#68647b]">
          {t("approval.reason")}: {approval.decision_reason}
        </p>
      )}
    </div>
  );
}

// ── Run detail pane ────────────────────────────────────────────────────────────

function RunDetailPane({ runId }: { runId: string }) {
  const t = useTranslations("agentWorkspace");
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"reasoning" | "tools" | "policy">(
    "reasoning",
  );

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

  if (runQuery.isLoading) {
    return <LoadingState title={t("loadingRun")} />;
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
  const historicalApprovals = run.approvals.filter(
    (a) => a.status !== "pending",
  );
  const canCancel = !isTerminal(run.status);
  const completedAnswer = run.status === "completed";
  const outcome = (run.outcome ?? {}) as Record<string, unknown>;
  const answer = typeof outcome.answer === "string" ? outcome.answer : null;
  const citations = Array.isArray(outcome.citations) ? outcome.citations : [];
  const confidence = (outcome.confidence ?? {}) as Record<string, unknown>;
  const notFound = outcome.not_found === true;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#e4e1f2] pb-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            {!isTerminal(run.status) && (
              <span className="material-symbols-outlined animate-spin text-[16px] text-[#3525cd]">
                progress_activity
              </span>
            )}
            {run.trace_request_id && (
              <span className="rounded-full border border-[#d7d4e8] bg-[#faf9ff] px-2 py-0.5 font-mono text-[10px] font-semibold text-[#68647b]">
                Trace {run.trace_request_id.slice(0, 12)}…
              </span>
            )}
          </div>
          <h2 className="mt-2 text-[22px] font-extrabold tracking-tight text-[#2a2640]">
            {run.objective ?? t("untitledRun")}
          </h2>
          {run.objective && (
            <p className="mt-1 max-w-3xl text-sm leading-6 text-[#68647b]">
              {run.objective}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Link
            href={`/workspace/agent/${encodeURIComponent(runId)}/trace`}
            className="flex items-center gap-1 rounded-full border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
          >
            <span className="material-symbols-outlined text-[14px]">
              timeline
            </span>
            {t("viewTrace")}
          </Link>
          {canCancel && (
            <button
              type="button"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="rounded-full border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs font-semibold text-[#464555] hover:bg-[#f5f2ff] disabled:opacity-60"
            >
              {cancelMutation.isPending ? t("cancelling") : t("cancelRun")}
            </button>
          )}
        </div>
      </div>

      {cancelMutation.isError && (
        <p className="text-xs text-rose-700">
          {getApiErrorMessage(cancelMutation.error)}
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
          <p className="text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("steps")}
          </p>
          <p className="mt-1 text-lg font-bold text-[#2a2640]">
            {run.steps.length}
          </p>
        </div>
        <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
          <p className="text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("toolCalls")}
          </p>
          <p className="mt-1 text-lg font-bold text-[#2a2640]">
            {run.tool_calls.length}
          </p>
        </div>
        <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
          <p className="text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("cost")}
          </p>
          <p className="mt-1 text-lg font-bold text-[#2a2640]">
            {formatCost(run.total_cost_usd ? Number(run.total_cost_usd) : null)}
          </p>
        </div>
        <div className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] px-4 py-3">
          <p className="text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("started")}
          </p>
          <p className="mt-1 text-sm font-semibold text-[#2a2640]">
            {formatTs(run.started_at, locale)}
          </p>
        </div>
      </div>

      {/* Pending approvals */}
      {pendingApprovals.length > 0 && (
        <section>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-amber-600">
                  verified_user
                </span>
                <div>
                  <p className="text-sm font-bold text-amber-950">
                    {t("approval.humanRequired")}
                  </p>
                  <p className="text-[12px] text-amber-900">
                    {t("approval.waiting", { count: pendingApprovals.length })}
                  </p>
                </div>
              </div>
            </div>
            <div className="mt-3 space-y-2">
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
          </div>
        </section>
      )}

      {/* Error */}
      {run.status === "failed" && run.error_message && (
        <div
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-3"
        >
          <p className="text-sm font-semibold text-rose-800">
            {t("runFailed")}
          </p>
          <p className="mt-1 text-[12px] text-rose-700">{run.error_message}</p>
          {run.trace_request_id && (
            <p className="mt-2 font-mono text-[11px] text-rose-600">
              {t("traceId")}: {run.trace_request_id}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-b border-[#e4e1f2] pb-1">
        <button
          type="button"
          onClick={() => setActiveTab("reasoning")}
          className={`rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
            activeTab === "reasoning"
              ? "border border-b-0 border-[#3525cd] bg-white text-[#3525cd]"
              : "text-[#68647b] hover:text-[#2a2640]"
          }`}
        >
          {t("reasoningTimeline")}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("tools")}
          className={`rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
            activeTab === "tools"
              ? "border border-b-0 border-[#3525cd] bg-white text-[#3525cd]"
              : "text-[#68647b] hover:text-[#2a2640]"
          }`}
        >
          {t("toolCallLog")}
          <span className="ml-2 rounded-full bg-[#ece8ff] px-2 py-0.5 text-[10px] font-bold text-[#3525cd]">
            {run.tool_calls.length}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("policy")}
          className={`rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
            activeTab === "policy"
              ? "border border-b-0 border-[#3525cd] bg-white text-[#3525cd]"
              : "text-[#68647b] hover:text-[#2a2640]"
          }`}
        >
          {t("effectivePolicy")}
        </button>
      </div>

      {activeTab === "reasoning" ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-[#e4e1f2] bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("finalAnswer")}
              </h3>
              {completedAnswer && (
                <span className="text-[11px] text-[#777587]">
                  {notFound ? t("noResponse") : t("statuses.completed")}
                </span>
              )}
            </div>
            {notFound ? (
              <EmptyState
                title={t("noAnswer.title")}
                description={t("noAnswer.description")}
                compact
              />
            ) : answer ? (
              <div className="mt-3">
                <p className="text-sm leading-6 whitespace-pre-wrap text-[#2a2640]">
                  {answer}
                </p>
                {Object.keys(confidence).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-[#68647b]">
                    {safeObjectEntries(confidence).map(([k, v]) => (
                      <span key={k}>
                        {k}:{" "}
                        <span className="font-semibold text-[#2a2640]">
                          {v}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
                {citations.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
                      {t("citations", { count: citations.length })}
                    </p>
                    <ol className="space-y-2">
                      {citations.map((c, i) => {
                        const citation = c as Record<string, unknown>;
                        const title =
                          typeof citation.title === "string"
                            ? citation.title
                            : typeof citation.document_id === "string"
                              ? citation.document_id
                              : t("source", { number: i + 1 });
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
          </div>

          {run.steps.length > 0 && (
            <div>
              <h3 className="mb-2 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("reasoningTimeline")}
              </h3>
              <div className="space-y-1.5">
                {run.steps.map((step) => (
                  <StepRow key={step.step_id} step={step} />
                ))}
              </div>
            </div>
          )}
        </section>
      ) : activeTab === "tools" ? (
        <section>
          <h3 className="mb-2 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("toolCallLog")}
          </h3>
          {run.tool_calls.length > 0 ? (
            <div className="space-y-1.5">
              {run.tool_calls.map((tc) => (
                <ToolCallRow key={tc.tool_call_id} toolCall={tc} />
              ))}
            </div>
          ) : (
            <EmptyState
              title={t("noTools.title")}
              description={t("noTools.description")}
              compact
            />
          )}
        </section>
      ) : (
        <section>
          <h3 className="mb-2 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("effectivePolicy")}
          </h3>
          <EffectivePolicyPanel runId={runId} />
        </section>
      )}

      {/* All approvals (for audit view) */}
      {historicalApprovals.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("approval.history")}
          </h3>
          <div className="space-y-1.5">
            {historicalApprovals.map((a) => (
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
  const t = useTranslations("agentWorkspace");
  const locale = useLocale();
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-2xl border p-3 text-left transition-colors ${
        isSelected
          ? "border-[#3525cd] bg-[#f0ecf9] shadow-sm"
          : "border-[#e4e1f2] bg-white hover:border-[#c7c3e0] hover:bg-[#faf9ff]"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12px] font-semibold text-[#2a2640]">
            {run.objective ?? t("untitledRun")}
          </p>
          <p className="mt-0.5 text-[10px] text-[#9993b0]">
            {formatTs(run.created_at, locale)}
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
  const t = useTranslations("agentWorkspace");
  const [workflowType, setWorkflowType] = useState<WorkflowType>(
    "audit_evidence_pack",
  );
  const [objective, setObjective] = useState("");
  const [scopeMode, setScopeMode] = useState<WorkflowScopeMode>("all");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>(
    [],
  );
  const [selectedConnectorIds, setSelectedConnectorIds] = useState<string[]>(
    [],
  );
  const [selectedProviderSourceIds, setSelectedProviderSourceIds] = useState<
    string[]
  >([]);
  const [mode, setMode] = useState<AgentRuntimeMode>("compare");
  const [maxSteps, setMaxSteps] = useState(12);
  const [maxToolCalls, setMaxToolCalls] = useState(30);
  const [maxTotalCostUsd, setMaxTotalCostUsd] = useState(2.5);
  const [presetMenuOpen, setPresetMenuOpen] = useState(false);
  const [preview, setPreview] = useState<WorkflowPlanPreviewResponse | null>(
    null,
  );
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);

  const preset = findWorkflowPreset(workflowType);
  const presetLabel = t(`presets.${workflowType}.label`);
  const presetDescription = t(`presets.${workflowType}.description`);
  const presetObjective = t(`presets.${workflowType}.objective`);
  const indexedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: 30,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: 30,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });
  const collectionsQuery = useQuery({
    queryKey: [...queryKeys.collections.all, "workspace-workflow-scope"],
    queryFn: () => listCollections({ limit: 200 }),
  });
  const connectorConnectionsQuery = useQuery({
    queryKey: [...queryKeys.connectorConnections, "workspace-workflow-scope"],
    queryFn: () => listAvailableConnectorConnections(),
  });
  const indexedDocuments = useMemo(
    () => indexedDocumentsQuery.data?.items ?? [],
    [indexedDocumentsQuery.data?.items],
  );
  const collections = useMemo(
    () => collectionsQuery.data?.items ?? [],
    [collectionsQuery.data?.items],
  );
  const connectorConnections = useMemo(
    () => connectorConnectionsQuery.data?.items ?? [],
    [connectorConnectionsQuery.data?.items],
  );
  const budgetEstimate = getBudgetEstimate(
    objective || presetObjective,
    maxSteps,
    maxTotalCostUsd,
  );

  const scopeSummary = useMemo(() => {
    const connectorCount =
      selectedConnectorIds.length + selectedProviderSourceIds.length;
    if (scopeMode === "none") return t("scope.noRag");
    if (scopeMode === "documents" && selectedDocumentIds.length > 0)
      return t("scope.selectedDocuments", {
        count: selectedDocumentIds.length,
      });
    if (scopeMode === "collection" && selectedCollectionIds.length > 0)
      return t("scope.selectedCollections", {
        count: selectedCollectionIds.length,
      });
    if (scopeMode === "connectors" && connectorCount > 0)
      return t("scope.selectedConnectors", { count: connectorCount });
    if (scopeMode === "collection") return t("scope.collections");
    if (scopeMode === "connectors") return t("scope.connectors");
    return t("scope.allDocuments");
  }, [
    scopeMode,
    selectedCollectionIds.length,
    selectedConnectorIds.length,
    selectedProviderSourceIds.length,
    selectedDocumentIds.length,
    t,
  ]);

  const buildSourceScopePayload = (): ChatSourceScopeRequest | null => {
    if (scopeMode === "none") {
      return null;
    }
    if (scopeMode === "collection" && selectedCollectionIds.length > 0) {
      return {
        mode: "collections",
        collection_ids: selectedCollectionIds,
      };
    }
    if (
      scopeMode === "connectors" &&
      (selectedConnectorIds.length > 0 || selectedProviderSourceIds.length > 0)
    ) {
      return {
        mode: "connector_sources",
        connection_ids: selectedConnectorIds,
        provider_source_ids: selectedProviderSourceIds,
      };
    }
    return null;
  };

  const buildRequest = () => ({
    objective: objective.trim() || presetObjective,
    mode,
    question: objective.trim() || presetObjective,
    document_query: objective.trim() || presetObjective,
    document_ids:
      scopeMode === "documents" && selectedDocumentIds.length > 0
        ? selectedDocumentIds
        : undefined,
    source_scope: buildSourceScopePayload() ?? undefined,
    rerank: preset.rerank,
    budget: {
      max_steps: maxSteps,
      max_tool_calls: maxToolCalls,
      max_total_cost_usd: maxTotalCostUsd,
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewWorkflowPlan({
        workflow_type: workflowType,
        request: buildRequest(),
      }),
    onSuccess: (data) => {
      setPreview(data);
      setPreviewError(null);
      setExecutionError(null);
    },
    onError: (err) => setPreviewError(getApiErrorMessage(err)),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createAgentRun({
        agentic_mode: true,
        request: preview?.request ?? buildRequest(),
      }),
    onSuccess: (data) => {
      setObjective("");
      setPreview(null);
      setPreviewError(null);
      setExecutionError(null);
      onRunCreated(data.run.run_id);
    },
    onError: (err) => setExecutionError(getApiErrorMessage(err)),
  });

  const canPreview =
    (objective.trim().length >= 3 || Boolean(preview?.request.objective)) &&
    !previewMutation.isPending;
  const canExecute = Boolean(preview) && !createMutation.isPending;

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[#d7d4e8] bg-[#faf9ff] p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold tracking-wide text-[#9993b0] uppercase">
              {t("builder.knowledgeSource")}
            </p>
            <p className="mt-1 text-sm font-semibold text-[#2a2640]">
              {t("scope.allDocuments")}
            </p>
            <p className="text-[11px] text-[#68647b]">
              {t("builder.organizationScope")}
            </p>
          </div>
          <span className="material-symbols-outlined text-[#3525cd]">
            database
          </span>
        </div>
      </div>

      <SourceScopeSelector
        headingLabel={t("scope.title")}
        triggerLabel={scopeSummary}
        labels={{
          triggerAriaLabel: t("scope.selectScope"),
          scopeAllDocuments: t("scope.allDocuments"),
          scopeCollection: t("scope.collection"),
          scopeConnectors: t("scope.connectors"),
          scopeNoRag: t("scope.noRag"),
          selectDocuments: t("scope.files"),
          documentSearchPlaceholder: t("scope.searchDocuments"),
          selectCollections: t("scope.collections"),
          selectConnectors: t("scope.connectors"),
          loadingDocuments: t("scope.loadingDocuments"),
          loadingCollections: t("scope.loadingCollections"),
          loadingConnectors: t("scope.loadingConnectors"),
          noDocumentsAvailable: t("scope.noDocuments"),
          noDocumentsMatch: t("scope.noDocuments"),
          noCollections: t("scope.noCollections"),
          noConnectors: t("scope.noConnectors"),
          documentSelected: t("scope.selected"),
          documentSelect: t("scope.select"),
          allDocumentsHint: t("scope.allHint"),
          cancel: t("cancel"),
          apply: t("apply"),
        }}
        scopeMode={scopeMode}
        onScopeModeChange={(nextScopeMode) => {
          setScopeMode(nextScopeMode);
          setPreview(null);
          setPreviewError(null);
          setExecutionError(null);
          if (nextScopeMode !== "documents") {
            setSelectedDocumentIds([]);
          }
          if (nextScopeMode !== "collection") {
            setSelectedCollectionIds([]);
          }
          if (nextScopeMode !== "connectors") {
            setSelectedConnectorIds([]);
            setSelectedProviderSourceIds([]);
          }
        }}
        selectedCollectionIds={selectedCollectionIds}
        selectedConnectorConnectionIds={selectedConnectorIds}
        selectedProviderSourceIds={selectedProviderSourceIds}
        selectedDocumentIds={selectedDocumentIds}
        collections={collections}
        connectorConnections={connectorConnections}
        indexedDocuments={indexedDocuments}
        isCollectionsLoading={collectionsQuery.isLoading}
        isConnectorsLoading={connectorConnectionsQuery.isLoading}
        isDocumentsLoading={indexedDocumentsQuery.isLoading}
        onToggleCollection={(collectionId) => {
          setSelectedCollectionIds((previous) =>
            previous.includes(collectionId)
              ? previous.filter((id) => id !== collectionId)
              : [...previous, collectionId],
          );
          setPreview(null);
          setPreviewError(null);
          setExecutionError(null);
        }}
        onToggleConnectorConnection={(connectionId) => {
          setSelectedConnectorIds((previous) =>
            previous.includes(connectionId)
              ? previous.filter((id) => id !== connectionId)
              : [...previous, connectionId],
          );
          setPreview(null);
          setPreviewError(null);
          setExecutionError(null);
        }}
        onToggleProviderSource={(providerSourceId) => {
          setSelectedProviderSourceIds((previous) =>
            previous.includes(providerSourceId)
              ? previous.filter((id) => id !== providerSourceId)
              : [...previous, providerSourceId],
          );
          setPreview(null);
          setPreviewError(null);
          setExecutionError(null);
        }}
        onToggleDocument={(documentId) => {
          setSelectedDocumentIds((previous) =>
            previous.includes(documentId)
              ? previous.filter((id) => id !== documentId)
              : [...previous, documentId],
          );
          setPreview(null);
          setPreviewError(null);
          setExecutionError(null);
        }}
      />

      <div className="relative">
        <p className="mb-1 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
          {t("builder.workflowPreset")}
        </p>
        <button
          type="button"
          onClick={() => setPresetMenuOpen((value) => !value)}
          className={`flex w-full items-center justify-between rounded-t-2xl border px-4 py-3 text-left transition-colors ${
            presetMenuOpen
              ? "border-[#3525cd] bg-white"
              : "border-[#d7d4e8] bg-white hover:border-[#3525cd]/50"
          }`}
        >
          <div className="flex min-w-0 items-center gap-3">
            <span className="material-symbols-outlined text-[#3525cd]">
              {getWorkflowPresetIcon(workflowType)}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-[#2a2640]">
                {presetLabel}
              </p>
              <p className="truncate text-[11px] text-[#68647b]">
                {presetDescription}
              </p>
            </div>
          </div>
          <span
            className={`material-symbols-outlined text-[#3525cd] transition-transform ${
              presetMenuOpen ? "rotate-180" : ""
            }`}
          >
            expand_more
          </span>
        </button>
        {presetMenuOpen && (
          <div className="absolute top-full left-0 z-20 w-full rounded-b-2xl border-x border-b border-[#d7d4e8] bg-white p-2 shadow-lg">
            <div className="space-y-1">
              {WORKFLOW_PRESETS.map((workflow) => {
                const active = workflow.workflowType === workflowType;
                return (
                  <button
                    key={workflow.workflowType}
                    type="button"
                    onClick={() => {
                      setWorkflowType(workflow.workflowType);
                      setMode(workflow.mode);
                      setObjective(
                        t(`presets.${workflow.workflowType}.objective`),
                      );
                      setPreview(null);
                      setPreviewError(null);
                      setExecutionError(null);
                      setPresetMenuOpen(false);
                    }}
                    className={`flex w-full items-start gap-3 rounded-xl p-2 text-left transition-colors ${
                      active ? "bg-[#f0ecf9]" : "hover:bg-[#faf9ff]"
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined mt-0.5 text-[18px] ${
                        active ? "text-[#3525cd]" : "text-[#777587]"
                      }`}
                    >
                      {getWorkflowPresetIcon(workflow.workflowType)}
                    </span>
                    <div className="min-w-0">
                      <p
                        className={`text-[11px] font-bold ${
                          active ? "text-[#3525cd]" : "text-[#2a2640]"
                        }`}
                      >
                        {t(`presets.${workflow.workflowType}.label`)}
                      </p>
                      <p className="text-[10px] leading-4 text-[#68647b]">
                        {t(`presets.${workflow.workflowType}.description`)}
                      </p>
                    </div>
                    <span className="ml-auto text-[10px] font-semibold text-[#777587] uppercase">
                      {t(`modes.${workflow.mode}.label`)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div>
        <label
          htmlFor="agent-objective"
          className="mb-1 block text-[11px] font-bold tracking-wide text-[#9993b0] uppercase"
        >
          {t("builder.objective")}
        </label>
        <textarea
          id="agent-objective"
          value={objective}
          onChange={(e) => {
            setObjective(e.target.value);
            setPreview(null);
            setPreviewError(null);
            setExecutionError(null);
          }}
          rows={4}
          maxLength={4000}
          placeholder={t("builder.objectivePlaceholder")}
          className="w-full resize-none rounded-2xl border border-[#d7d4e8] bg-white px-4 py-3 text-sm text-[#2a2640] outline-none placeholder:text-[#b0adbe] focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
        />
        <p className="mt-1 text-right text-[10px] text-[#b0adbe]">
          {objective.length}/4000
        </p>
      </div>

      <div>
        <p className="mb-1 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
          {t("builder.executionMode")}
        </p>
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-[#d7d4e8] bg-[#faf9ff] p-1 sm:grid-cols-4">
          {WORKFLOW_MODE_OPTIONS.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => {
                setMode(m.value);
                setPreview(null);
                setPreviewError(null);
                setExecutionError(null);
              }}
              title={t(`modes.${m.value}.description`)}
              className={`flex min-h-12 items-center justify-center rounded-md px-2 py-1.5 text-center text-[11px] font-semibold transition-colors ${
                mode === m.value
                  ? "bg-[#3525cd] text-white shadow-sm"
                  : "text-[#68647b] hover:bg-white hover:text-[#2a2640]"
              }`}
            >
              <span>{t(`modes.${m.value}.label`)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-[#e4e1f2] bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
            {t("builder.budgetControls")}
          </p>
          <span className="text-[10px] font-semibold text-[#777587] uppercase">
            {t("builder.softCaps")}
          </span>
        </div>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-[#68647b]">
              <span>{t("builder.maxSteps")}</span>
              <span className="font-semibold text-[#3525cd]">{maxSteps}</span>
            </div>
            <input
              type="range"
              min={1}
              max={50}
              value={maxSteps}
              onChange={(e) => {
                setMaxSteps(Number(e.target.value));
                setPreview(null);
                setPreviewError(null);
                setExecutionError(null);
              }}
              className="w-full accent-[#3525cd]"
            />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-[#68647b]">
              <span>{t("builder.maxToolCalls")}</span>
              <span className="font-semibold text-[#3525cd]">
                {maxToolCalls}
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={100}
              value={maxToolCalls}
              onChange={(e) => {
                setMaxToolCalls(Number(e.target.value));
                setPreview(null);
                setPreviewError(null);
                setExecutionError(null);
              }}
              className="w-full accent-[#3525cd]"
            />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-[#68647b]">
              <span>{t("builder.maxCost")}</span>
              <span className="font-semibold text-[#3525cd]">
                {formatMoney(maxTotalCostUsd)}
              </span>
            </div>
            <input
              type="range"
              min={0.5}
              max={10}
              step={0.5}
              value={maxTotalCostUsd}
              onChange={(e) => {
                setMaxTotalCostUsd(Number(e.target.value));
                setPreview(null);
                setPreviewError(null);
                setExecutionError(null);
              }}
              className="w-full accent-[#3525cd]"
            />
          </div>
          <div className="rounded-xl border border-[#d7d4e8] bg-[#faf9ff] p-3">
            <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold text-[#3525cd]">
              <span className="material-symbols-outlined text-[14px]">
                info
              </span>
              {t("builder.estimate")}
            </div>
            <p className="text-[11px] leading-5 text-[#68647b]">
              {t("builder.estimateSummary", {
                steps: budgetEstimate.steps,
                cost: formatMoney(budgetEstimate.costUsd),
              })}
            </p>
          </div>
        </div>
      </div>

      {preview ? (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm sm:p-5">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
            <div className="min-w-0">
              <p className="text-[10px] font-bold tracking-wide text-emerald-800 uppercase">
                {t("builder.planPreview")}
              </p>
              <p className="mt-1 text-sm font-semibold text-emerald-950 sm:text-base">
                {preview.workflow_type
                  ? t(`presets.${preview.workflow_type}.label`)
                  : presetLabel}
              </p>
            </div>
            <div className="inline-flex w-fit max-w-full items-center rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
              strategy {preview.planner_strategy}
            </div>
          </div>
          <p className="mt-3 max-w-none text-[12px] leading-5 text-emerald-900 sm:text-sm">
            {preview.objective}
          </p>
          {preview.requires_approval ? (
            <p className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900">
              {t("builder.approvalGated")}
            </p>
          ) : null}
          <div className="mt-4 space-y-2">
            {preview.plan.map((step, index) => (
              <div
                key={`${step.step_name}:${index}`}
                className="rounded-xl border border-emerald-100 bg-white px-3 py-2 sm:px-4 sm:py-3"
              >
                <div className="flex flex-col gap-1.5">
                  <span className="w-fit rounded-full bg-emerald-100 px-2 py-0.5 font-mono text-[10px] font-semibold tracking-wide text-emerald-800 uppercase">
                    {step.tool_name}
                  </span>
                  <p className="min-w-0 text-sm leading-5 font-semibold break-words text-[#2a2640]">
                    {step.step_name}
                  </p>
                </div>
                {step.rationale ? (
                  <p className="mt-1 text-[11px] leading-5 text-[#68647b] sm:text-[12px]">
                    {step.rationale}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {previewError ? (
        <p role="alert" className="text-xs text-rose-700">
          {previewError}
        </p>
      ) : null}

      {executionError ? (
        <p role="alert" className="text-xs text-rose-700">
          {executionError}
        </p>
      ) : null}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => previewMutation.mutate()}
          disabled={!canPreview}
          className="flex-1 rounded-full border border-[#d7d4e8] bg-white px-4 py-3 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {previewMutation.isPending
            ? t("builder.buildingPlan")
            : t("builder.previewPlan")}
        </button>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!canExecute}
          className="flex-1 rounded-full bg-[#3525cd] px-4 py-3 text-sm font-semibold text-white hover:bg-[#2a1da8] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {createMutation.isPending
            ? t("builder.startingRun")
            : t("builder.executeWorkflow")}
        </button>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function AgentWorkspacePage() {
  const t = useTranslations("agentWorkspace");
  const [explicitSelectedRunId, setExplicitSelectedRunId] = useState<
    string | null
  >(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const runsQuery = useQuery({
    queryKey: queryKeys.agent.runs({ limit: RUN_LIST_LIMIT }),
    queryFn: () => listAgentRuns({ limit: RUN_LIST_LIMIT }),
    refetchInterval: POLL_INTERVAL_MS,
  });

  const handleRunCreated = useCallback((runId: string) => {
    setExplicitSelectedRunId(runId);
    setTimeout(() => {
      if (typeof detailRef.current?.scrollIntoView === "function") {
        detailRef.current.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    }, 100);
  }, []);

  const runs = runsQuery.data?.runs ?? [];
  const selectedRunId = explicitSelectedRunId ?? runs[0]?.run_id ?? null;

  return (
    <div className="flex min-h-0 flex-col gap-4 px-4 py-6 sm:px-6">
      <div className="rounded-3xl border border-[#d7d4e8] bg-gradient-to-r from-white via-[#faf9ff] to-[#f4f2ff] px-5 py-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold tracking-[0.25em] text-[#777587] uppercase">
              {t("page.eyebrow")}
            </p>
            <h1 className="mt-1 text-3xl font-black tracking-tight text-[#2a2640]">
              {t("page.title")}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#68647b]">
              {t("page.description")}
            </p>
          </div>
        </div>
      </div>

      <AgentApprovalQueuePanel />

      <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
        <aside className="space-y-4">
          <section className="rounded-3xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
              {t("newRun")}
            </h2>
            <NewRunForm onRunCreated={handleRunCreated} />
          </section>
        </aside>

        <main ref={detailRef} className="min-h-0">
          {selectedRunId ? (
            <section className="rounded-3xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
              <RunDetailPane key={selectedRunId} runId={selectedRunId} />
            </section>
          ) : (
            <section className="rounded-3xl border border-[#d7d4e8] bg-white p-8 text-center shadow-sm">
              <span className="material-symbols-outlined text-[48px] text-[#d7d4e8]">
                robot_2
              </span>
              <p className="mt-2 text-sm font-semibold text-[#9993b0]">
                {t("selectRun")}
              </p>
            </section>
          )}
        </main>

        <aside className="min-h-0">
          <section className="flex h-full flex-col rounded-3xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
                {t("recentRuns")}
              </h2>
              {runsQuery.data && (
                <span className="text-[10px] font-semibold text-[#777587]">
                  {t("total", { count: runsQuery.data.total })}
                </span>
              )}
            </div>

            {runsQuery.isLoading && (
              <LoadingState title={t("loadingRuns")} compact />
            )}
            {runsQuery.isError && (
              <ErrorState
                error={runsQuery.error}
                onRetry={() => void runsQuery.refetch()}
                compact
              />
            )}
            {!runsQuery.isLoading &&
              !runsQuery.isError &&
              runs.length === 0 && (
                <EmptyState
                  title={t("noRuns.title")}
                  description={t("noRuns.description")}
                  compact
                />
              )}
            {runs.length > 0 && (
              <div className="space-y-2 overflow-y-auto pr-1">
                {runs.map((run) => (
                  <RunListItem
                    key={run.run_id}
                    run={run}
                    isSelected={selectedRunId === run.run_id}
                    onSelect={() => setExplicitSelectedRunId(run.run_id)}
                  />
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
