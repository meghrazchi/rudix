"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { agentRunStreamPath, openEventStream } from "@/lib/api/events";
import { queryKeys } from "@/lib/api/query";
import { isRealtimeEnabled } from "@/lib/realtime/RealtimeProvider";
import { readSseFrames } from "@/lib/realtime/sse-reader";

export type AgentRunStreamState = "idle" | "streaming" | "fallback";

const TERMINAL_EVENTS = new Set([
  "agent.run.completed",
  "agent.run.failed",
  "agent.run.cancelled",
]);
export const AGENT_RUN_STREAM_REFETCH_MS = 200;

/**
 * Follow `GET /agent/runs/{run_id}/stream` while the run is not terminal (R07-07; deferred
 * from 0.6.0). Each event refetches the run query (merged within 200 ms); a terminal
 * event closes the stream. Any error, a non-200 answer (404, 503), or the server ending
 * the stream early switches to `fallback`, and the caller polls again. Only active with
 * `NEXT_PUBLIC_REALTIME_ENABLED=true`.
 */
export function useAgentRunStream(
  runId: string | null,
  active: boolean,
): AgentRunStreamState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<{
    runId: string | null;
    value: AgentRunStreamState;
  }>({ runId: null, value: "idle" });

  useEffect(() => {
    if (!runId || !active || !isRealtimeEnabled()) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const update = (value: AgentRunStreamState) => {
      if (!controller.signal.aborted) {
        setState({ runId, value });
      }
    };
    const refetch = () => {
      if (timer !== null) {
        return;
      }
      timer = setTimeout(() => {
        timer = null;
        void queryClient.invalidateQueries({
          queryKey: queryKeys.agent.run(runId),
        });
      }, AGENT_RUN_STREAM_REFETCH_MS);
    };

    async function follow(): Promise<void> {
      try {
        const response = await openEventStream(agentRunStreamPath(runId!), {
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          update("fallback");
          return;
        }
        update("streaming");
        for await (const frame of readSseFrames(response.body)) {
          if (frame.kind !== "event") {
            continue;
          }
          refetch();
          if (TERMINAL_EVENTS.has(frame.event)) {
            update("idle");
            return;
          }
        }
        update("fallback");
      } catch {
        update("fallback");
      }
    }

    void follow();
    return () => {
      controller.abort();
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [runId, active, queryClient]);

  return state.runId === runId && active ? state.value : "idle";
}
