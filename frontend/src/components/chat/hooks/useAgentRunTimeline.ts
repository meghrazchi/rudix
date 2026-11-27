import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isTerminalAgentRunStatus } from "@/components/chat/chat-session-utils";
import {
  AGENT_RUN_POLL_INTERVAL_MS,
  type ChatTurn,
} from "@/components/chat/chat-types";
import {
  decideAgentRunApproval,
  getAgentRun,
  type AgentApprovalDecisionRequest,
  type AgentRunDetailResponse,
} from "@/lib/api/agent";
import { queryKeys } from "@/lib/api/query";

export function useAgentRunTimeline({
  selectedCitationTurn,
}: {
  selectedCitationTurn: ChatTurn | null;
}) {
  const queryClient = useQueryClient();
  const selectedAgentRunId =
    selectedCitationTurn?.response.agent_run_id ?? null;
  const selectedAgentRunQuery = useQuery({
    queryKey: queryKeys.agent.run(selectedAgentRunId ?? ""),
    queryFn: () => getAgentRun(selectedAgentRunId ?? ""),
    enabled: Boolean(selectedAgentRunId),
    refetchInterval: (query) => {
      const data = query.state.data as AgentRunDetailResponse | undefined;
      if (!data || isTerminalAgentRunStatus(data.status)) {
        return false;
      }
      return AGENT_RUN_POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: true,
  });

  const decideApprovalMutation = useMutation({
    mutationFn: (params: {
      runId: string;
      approvalId: string;
      payload: AgentApprovalDecisionRequest;
    }) =>
      decideAgentRunApproval(params.runId, params.approvalId, params.payload),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agent.run(variables.runId),
      });
    },
  });

  async function handleApprovalDecision(params: {
    runId: string;
    approvalId: string;
    status: "approved" | "rejected";
  }) {
    await decideApprovalMutation.mutateAsync({
      runId: params.runId,
      approvalId: params.approvalId,
      payload: {
        status: params.status,
      },
    });
  }

  return {
    selectedAgentRunId,
    selectedAgentRunQuery,
    decideApprovalMutation,
    handleApprovalDecision,
  };
}

export type AgentRunTimelineController = ReturnType<typeof useAgentRunTimeline>;
