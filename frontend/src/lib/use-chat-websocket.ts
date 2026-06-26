/**
 * React hook for the Rudix WebSocket chat transport (F277).
 *
 * State machine:
 *   idle → connecting → retrieving → generating → validating → completed
 *                                                             ↘ cancelled
 *                                                             ↘ error
 *
 * Usage:
 *   const ws = useChatWebSocket();
 *   ws.sendQuery({ question: "…", chat_session_id: "…", … });
 *   ws.cancel();
 *   // ws.phase, ws.partialAnswer, ws.finalResponse, ws.error
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatQueryRequest, ChatQueryResponse } from "@/lib/api/chat";
import {
  buildChatWsUrl,
  ChatWSClient,
  type ActivityTimelineStep,
  type ChatWSEvent,
} from "@/lib/chat-websocket";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";
import { getSessionRequestContext } from "@/lib/api/request";

export type ChatWSPhase =
  | "idle"
  | "connecting"
  | "scope_validated"
  | "retrieving"
  | "reranking"
  | "generating"
  | "validating_citations"
  | "completed"
  | "cancelled"
  | "error";

export type UseChatWebSocketResult = {
  phase: ChatWSPhase;
  /** Streamed answer text; grows as generation.delta events arrive. */
  partialAnswer: string;
  /** Final full response payload from chat.completed. */
  finalResponse: ChatQueryResponse | null;
  /** Safe error code from the server, or "connection_failed" for WS errors. */
  error: string | null;
  /** True while any non-terminal phase is active. */
  isPending: boolean;
  /** Live activity timeline steps, keyed by step_key and sorted by sequence. */
  timelineSteps: ActivityTimelineStep[];
  sendQuery: (payload: ChatQueryRequest & { _scopeLabel?: string }) => void;
  cancel: () => void;
  reset: () => void;
};

type TerminalPhase = "completed" | "cancelled" | "error";

const TERMINAL_PHASES = new Set<ChatWSPhase>([
  "completed",
  "cancelled",
  "error",
]);

function isTerminal(phase: ChatWSPhase): phase is TerminalPhase {
  return TERMINAL_PHASES.has(phase);
}

export function useChatWebSocket(): UseChatWebSocketResult {
  const [phase, setPhase] = useState<ChatWSPhase>("idle");
  const [partialAnswer, setPartialAnswer] = useState("");
  const [finalResponse, setFinalResponse] = useState<ChatQueryResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [timelineSteps, setTimelineSteps] = useState<ActivityTimelineStep[]>([]);

  const clientRef = useRef<ChatWSClient | null>(null);
  // Keep a stable ref to the current phase to avoid stale closures.
  const phaseRef = useRef<ChatWSPhase>("idle");

  const updatePhase = useCallback((next: ChatWSPhase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  // Tear down on unmount.
  useEffect(() => {
    return () => {
      clientRef.current?.close();
      clientRef.current = null;
    };
  }, []);

  const handleEvent = useCallback(
    (evt: ChatWSEvent) => {
      switch (evt.event) {
        case "connection.ready":
          break;
        case "chat.request.received":
          updatePhase("connecting");
          break;
        case "chat.scope.validated":
          updatePhase("scope_validated");
          break;
        case "retrieval.started":
          updatePhase("retrieving");
          break;
        case "retrieval.completed":
          break;
        case "rerank.started":
          updatePhase("reranking");
          break;
        case "rerank.completed":
          break;
        case "generation.started":
          updatePhase("generating");
          break;
        case "generation.delta": {
          const text = (evt.payload?.text as string | undefined) ?? "";
          if (text) {
            setPartialAnswer((prev) => prev + text);
          }
          break;
        }
        case "citation.validation.started":
          updatePhase("validating_citations");
          break;
        case "citation.validation.completed":
          break;
        case "activity.step.update": {
          const p = evt.payload;
          if (!p) break;
          const step: ActivityTimelineStep = {
            stepKey: p.step_key as string,
            sequence: p.sequence as number,
            label: p.label as string,
            state: p.state as ActivityTimelineStep["state"],
            detail: (p.detail as string | null) ?? null,
            durationMs: (p.duration_ms as number | null) ?? null,
          };
          setTimelineSteps((prev) => {
            const idx = prev.findIndex((s) => s.stepKey === step.stepKey);
            if (idx === -1) {
              const next = [...prev, step];
              next.sort((a, b) => a.sequence - b.sequence);
              return next;
            }
            const next = [...prev];
            next[idx] = { ...next[idx], ...step };
            return next;
          });
          break;
        }
        case "chat.completed": {
          const response = evt.payload?.response as
            | ChatQueryResponse
            | undefined;
          if (response) {
            setFinalResponse(response);
          }
          setPartialAnswer("");
          updatePhase("completed");
          break;
        }
        case "chat.cancelled":
          updatePhase("cancelled");
          break;
        case "chat.error":
          setError(evt.safe_error_code ?? "unknown_error");
          updatePhase("error");
          break;
        default:
          break;
      }
    },
    [updatePhase],
  );

  /** Ensure the WS client is connected (or already connected). */
  const ensureConnected = useCallback((): ChatWSClient => {
    if (clientRef.current) return clientRef.current;

    const { token } = getSessionRequestContext();
    const { apiUrl } = getFrontendRuntimeConfig();
    const wsUrl = buildChatWsUrl(apiUrl);

    const client = new ChatWSClient({
      url: wsUrl,
      token: token ?? "",
      onEvent: handleEvent,
      onStateChange: (state) => {
        if (state === "error" && !isTerminal(phaseRef.current)) {
          setError("connection_failed");
          updatePhase("error");
        }
        if (state === "disconnected" && !isTerminal(phaseRef.current)) {
          setError("connection_lost");
          updatePhase("error");
        }
      },
      onClose: (_code, _reason) => {
        if (!isTerminal(phaseRef.current)) {
          setError("connection_closed");
          updatePhase("error");
        }
      },
    });

    clientRef.current = client;
    client.connect();
    return client;
  }, [handleEvent, updatePhase]);

  const sendQuery = useCallback(
    (payload: ChatQueryRequest & { _scopeLabel?: string }) => {
      if (!isTerminal(phase) && phase !== "idle") return;

      // Reset state for new query.
      setPartialAnswer("");
      setFinalResponse(null);
      setError(null);
      setTimelineSteps([]);
      updatePhase("connecting");

      // Strip internal _scopeLabel — not a valid backend field.
      const { _scopeLabel, ...backendPayload } = payload;

      const client = ensureConnected();

      const requestId = crypto.randomUUID?.() ?? String(Date.now());
      client.send({
        command: "chat.start",
        request_id: requestId,
        payload: backendPayload as Record<string, unknown>,
      });
    },
    [phase, ensureConnected, updatePhase],
  );

  const cancel = useCallback(() => {
    clientRef.current?.send({ command: "chat.cancel" });
  }, []);

  const reset = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    setPartialAnswer("");
    setFinalResponse(null);
    setError(null);
    setTimelineSteps([]);
    updatePhase("idle");
  }, [updatePhase]);

  const isPending =
    phase !== "idle" &&
    phase !== "completed" &&
    phase !== "cancelled" &&
    phase !== "error";

  return {
    phase,
    partialAnswer,
    finalResponse,
    error,
    isPending,
    timelineSteps,
    sendQuery,
    cancel,
    reset,
  };
}
