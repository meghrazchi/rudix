"use client";

import { useEffect, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  commentAgentRunApproval,
  decideAgentRunApproval,
  listAgentApprovals,
  type AgentApprovalQueueItem,
} from "@/lib/api/agent";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";

// ── Constants ──────────────────────────────────────────────────────────────────

const QUEUE_POLL_INTERVAL_MS = 5_000;
const QUEUE_LIMIT = 20;

// ── Risk level badge ───────────────────────────────────────────────────────────

const RISK_COLORS: Record<string, string> = {
  critical: "bg-rose-100 text-rose-800 border-rose-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const cls =
    RISK_COLORS[level.toLowerCase()] ??
    "bg-[#e4e1ee] text-[#464555] border-[#d7d4e8]";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase ${cls}`}
    >
      {level}
    </span>
  );
}

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 1_000);
    return () => window.clearInterval(id);
  }, []);

  return now;
}

function ExpiryCountdown({ expiresAt }: { expiresAt: string | null }) {
  const now = useNow();
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - now;
  if (diff <= 0) {
    return (
      <span className="text-[11px] font-semibold text-rose-600">Expired</span>
    );
  }
  const minutes = Math.floor(diff / 60_000);
  const seconds = Math.floor((diff % 60_000) / 1000);
  const label =
    minutes > 0
      ? `Expires in ${minutes}m ${seconds}s`
      : `Expires in ${seconds}s`;
  const urgent = diff < 120_000;
  return (
    <span
      className={`text-[11px] ${urgent ? "font-semibold text-rose-600" : "text-[#777587]"}`}
    >
      {label}
    </span>
  );
}

// ── Single approval card ───────────────────────────────────────────────────────

function ApprovalCard({ item }: { item: AgentApprovalQueueItem }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<
    "approved" | "rejected" | "changes_requested" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [commentError, setCommentError] = useState<string | null>(null);
  const [commentSent, setCommentSent] = useState(false);

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.agent.approvals(),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.agent.run(item.agent_run_id),
    });
  };

  const decideMutation = useMutation({
    mutationFn: ({
      decision,
    }: {
      decision: "approved" | "rejected" | "changes_requested";
    }) =>
      decideAgentRunApproval(item.agent_run_id, item.approval_id, {
        status: decision,
        reason: reason.trim() || null,
      }),
    onSuccess: () => {
      setError(null);
      setReason("");
      setShowReason(false);
      setPendingDecision(null);
      invalidate();
    },
    onError: (err) => {
      setError(getApiErrorMessage(err));
      setPendingDecision(null);
    },
  });

  const commentMutation = useMutation({
    mutationFn: () =>
      commentAgentRunApproval(
        item.agent_run_id,
        item.approval_id,
        comment.trim(),
      ),
    onSuccess: () => {
      setCommentError(null);
      setComment("");
      setShowComment(false);
      setCommentSent(true);
      invalidate();
    },
    onError: (err) => {
      setCommentError(getApiErrorMessage(err));
    },
  });

  const handleDecide = (
    decision: "approved" | "rejected" | "changes_requested",
  ) => {
    setPendingDecision(decision);
    decideMutation.mutate({ decision });
  };

  const isPending = decideMutation.isPending;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
      {/* Header row */}
      <div className="flex flex-wrap items-start gap-2">
        <span className="material-symbols-outlined mt-0.5 shrink-0 text-[20px] text-amber-600">
          pending_actions
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[#2a2640]">
              Approval required
            </span>
            <RiskBadge level={item.risk_level} />
            {item.tool_name && (
              <span className="rounded bg-[#ece8ff] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[#3525cd]">
                {item.tool_name}
              </span>
            )}
          </div>

          {item.run_objective && (
            <p className="mt-0.5 text-[11px] text-[#777587]">
              Run:{" "}
              <span className="font-medium text-[#464555]">
                {item.run_objective}
              </span>
            </p>
          )}

          {item.request_summary && (
            <p className="mt-1 text-[13px] text-[#2a2640]">
              {item.request_summary}
            </p>
          )}

          <div className="mt-1 flex flex-wrap gap-3">
            <ExpiryCountdown expiresAt={item.expires_at} />
            <span className="text-[11px] text-[#9993b0]">
              ID: {item.approval_id.slice(0, 8)}…
            </span>
          </div>
        </div>
      </div>

      {/* Decision actions */}
      <div className="mt-3 space-y-2">
        {showReason && (
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)…"
            maxLength={600}
            rows={2}
            className="w-full resize-none rounded border border-[#d7d4e8] px-2 py-1.5 text-sm outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
          />
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handleDecide("approved")}
            disabled={isPending}
            aria-label="Approve"
            className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {isPending && pendingDecision === "approved"
              ? "Approving…"
              : "Approve"}
          </button>

          <button
            type="button"
            onClick={() => {
              setShowReason(true);
              handleDecide("changes_requested");
            }}
            disabled={isPending}
            aria-label="Request changes"
            className="rounded border border-amber-400 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-60"
          >
            {isPending && pendingDecision === "changes_requested"
              ? "Requesting…"
              : "Request changes"}
          </button>

          <button
            type="button"
            onClick={() => {
              setShowReason(true);
              handleDecide("rejected");
            }}
            disabled={isPending}
            aria-label="Reject"
            className="rounded border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
          >
            {isPending && pendingDecision === "rejected"
              ? "Rejecting…"
              : "Reject"}
          </button>

          {!showReason && (
            <button
              type="button"
              onClick={() => setShowReason((v) => !v)}
              className="rounded border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs text-[#777587] hover:bg-[#f5f2ff]"
            >
              Add reason
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              setShowComment((v) => !v);
              setCommentSent(false);
            }}
            disabled={isPending}
            aria-label="Add comment"
            className="rounded border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs text-[#777587] hover:bg-[#f5f2ff] disabled:opacity-60"
          >
            Comment
          </button>
        </div>

        {error && (
          <p role="alert" className="text-[11px] text-rose-700">
            {error}
          </p>
        )}
      </div>

      {/* Comment section */}
      {showComment && (
        <div className="mt-3 space-y-1.5 border-t border-amber-200 pt-3">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Leave a comment without deciding…"
            maxLength={1000}
            rows={2}
            className="w-full resize-none rounded border border-[#d7d4e8] px-2 py-1.5 text-sm outline-none focus:border-[#3525cd] focus:ring-1 focus:ring-[#3525cd]"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => commentMutation.mutate()}
              disabled={commentMutation.isPending || !comment.trim()}
              className="rounded bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#2a1eb0] disabled:opacity-60"
            >
              {commentMutation.isPending ? "Posting…" : "Post comment"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowComment(false);
                setComment("");
                setCommentError(null);
              }}
              className="rounded border border-[#d7d4e8] bg-white px-3 py-1.5 text-xs text-[#777587] hover:bg-[#f5f2ff]"
            >
              Cancel
            </button>
          </div>
          {commentSent && (
            <p className="text-[11px] text-emerald-700">Comment posted.</p>
          )}
          {commentError && (
            <p role="alert" className="text-[11px] text-rose-700">
              {commentError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────────────────────────

export function AgentApprovalQueuePanel() {
  const queueQuery = useQuery({
    queryKey: queryKeys.agent.approvals({
      status: "pending",
      limit: QUEUE_LIMIT,
    }),
    queryFn: () =>
      listAgentApprovals({ status: "pending", limit: QUEUE_LIMIT }),
    refetchInterval: QUEUE_POLL_INTERVAL_MS,
  });

  const items = queueQuery.data?.approvals ?? [];
  const total = queueQuery.data?.total ?? 0;

  return (
    <section
      aria-label="Approval queue"
      className="rounded-xl border border-[#d7d4e8] bg-white p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[11px] font-bold tracking-wide text-[#9993b0] uppercase">
          Approval queue
          {total > 0 && (
            <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
              {total}
            </span>
          )}
        </h2>
        {queueQuery.isFetching && (
          <span className="material-symbols-outlined animate-spin text-[14px] text-[#9993b0]">
            progress_activity
          </span>
        )}
      </div>

      {queueQuery.isLoading && (
        <LoadingState title="Loading approvals…" compact />
      )}

      {queueQuery.isError && (
        <ErrorState
          error={queueQuery.error}
          onRetry={() => void queueQuery.refetch()}
          compact
        />
      )}

      {!queueQuery.isLoading && !queueQuery.isError && items.length === 0 && (
        <EmptyState
          title="No pending approvals"
          description="Agent actions requiring approval will appear here."
          compact
        />
      )}

      {items.length > 0 && (
        <div className="space-y-3">
          {items.map((item) => (
            <ApprovalCard key={item.approval_id} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}
