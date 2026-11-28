import { useTranslations } from "next-intl";

import { agentRunStatusClass } from "@/components/chat/chat-session-utils";
import type { AgentRunTimelineController } from "@/components/chat/hooks/useAgentRunTimeline";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { getApiErrorMessage } from "@/lib/api/errors";

export function AgentRunTimeline({
  agentRun,
  canDecideApprovals,
}: {
  agentRun: AgentRunTimelineController;
  canDecideApprovals: boolean;
}) {
  const tc = useTranslations("chat.page");
  const {
    selectedAgentRunId,
    selectedAgentRunQuery,
    decideApprovalMutation,
    handleApprovalDecision,
  } = agentRun;

  return (
    <>
      {selectedAgentRunId ? (
        <div className="mt-4">
          <p className="mb-2 text-[10px] font-bold tracking-widest text-[#464555] uppercase">
            {tc("agentTimeline")}
          </p>
          {selectedAgentRunQuery.isLoading ? (
            <LoadingState compact title={tc("loadingTimeline")} />
          ) : selectedAgentRunQuery.isError ? (
            <ErrorState
              compact
              error={selectedAgentRunQuery.error}
              description={getApiErrorMessage(selectedAgentRunQuery.error)}
              onRetry={() => {
                void selectedAgentRunQuery.refetch();
              }}
            />
          ) : selectedAgentRunQuery.data ? (
            <div className="space-y-1.5 text-xs text-[#4f4b63]">
              <div className="flex flex-wrap items-center gap-2 rounded border border-[#ebe8f7] px-2 py-1.5">
                <span
                  className={agentRunStatusClass(
                    selectedAgentRunQuery.data.status,
                  )}
                >
                  {selectedAgentRunQuery.data.status}
                </span>
                <span className="truncate text-[#6a6780]">
                  {tc("agentRunShortId", {
                    id: selectedAgentRunQuery.data.run_id.slice(0, 8),
                  })}
                </span>
              </div>
              {selectedAgentRunQuery.data.approvals.length > 0 && (
                <p className="text-[10px] font-bold tracking-widest text-[#464555] uppercase">
                  {tc("approvalsTitle")}
                </p>
              )}
              {selectedAgentRunQuery.data.approvals
                .filter((a) => a.status === "pending")
                .map((approval) => (
                  <div
                    key={approval.approval_id}
                    className="rounded border border-amber-200 bg-amber-50 px-2 py-2"
                  >
                    <p className="mb-1 text-xs text-amber-800">
                      {approval.request_summary ?? tc("approvalNeeded")}
                    </p>
                    {canDecideApprovals && (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={decideApprovalMutation.isPending}
                          onClick={() => {
                            void handleApprovalDecision({
                              runId: selectedAgentRunQuery.data.run_id,
                              approvalId: approval.approval_id,
                              status: "approved",
                            });
                          }}
                          className="rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 disabled:opacity-60"
                        >
                          {tc("approve")}
                        </button>
                        <button
                          type="button"
                          disabled={decideApprovalMutation.isPending}
                          onClick={() => {
                            void handleApprovalDecision({
                              runId: selectedAgentRunQuery.data.run_id,
                              approvalId: approval.approval_id,
                              status: "rejected",
                            });
                          }}
                          className="rounded border border-rose-300 bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-800 disabled:opacity-60"
                        >
                          {tc("reject")}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              <ol className="space-y-1">
                {selectedAgentRunQuery.data.steps.map((step) => (
                  <li
                    key={step.step_id}
                    className="rounded border border-[#ebe8f7] px-2 py-1.5"
                  >
                    <p className="font-semibold text-[#3f3b58]">
                      {step.sequence}. {step.step_name}
                    </p>
                    <p className="text-[#6a6780]">
                      {step.status}
                      {step.duration_ms !== null
                        ? ` • ${step.duration_ms}ms`
                        : ""}
                    </p>
                  </li>
                ))}
              </ol>
              {decideApprovalMutation.isError && (
                <p className="rounded border border-rose-200 bg-rose-50 px-2 py-1.5 text-rose-800">
                  {getApiErrorMessage(decideApprovalMutation.error)}
                </p>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
