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
import { useRealtimeAwareInterval } from "@/lib/realtime/polling";
import { useAgentRunStream } from "@/components/chat/hooks/useAgentRunStream";

export function useAgentRunTimeline({
  selectedCitationTurn,
}: {
  selectedCitationTurn: ChatTurn | null;
}) {
  const queryClient = useQueryClient();
  const selectedAgentRunId =
    selectedCitationTurn?.response.agent_run_id ?? null;
  const runKey = queryKeys.agent.run(selectedAgentRunId ?? "");
  const cachedRun = queryClient.getQueryData<AgentRunDetailResponse>(runKey);
  // R07-07: follow the run's SSE stream while it is not terminal; poll only when the
  // stream is not available (or realtime is off), and never in a hidden tab.
  const streamState = useAgentRunStream(
    selectedAgentRunId,
    Boolean(cachedRun) && !isTerminalAgentRunStatus(cachedRun?.status ?? ""),
  );
  const refetchInterval = useRealtimeAwareInterval(
    (query: { state: { data: unknown } }) => {
      const data = query.state.data as AgentRunDetailResponse | undefined;
      if (
        streamState === "streaming" ||
        !data ||
        isTerminalAgentRunStatus(data.status)
      ) {
        return false;
      }
      return AGENT_RUN_POLL_INTERVAL_MS;
    },
    { covered: false },
  );
  const selectedAgentRunQuery = useQuery({
    queryKey: runKey,
    queryFn: () => getAgentRun(selectedAgentRunId ?? ""),
    enabled: Boolean(selectedAgentRunId),
    refetchInterval,
    refetchIntervalInBackground: false,
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
