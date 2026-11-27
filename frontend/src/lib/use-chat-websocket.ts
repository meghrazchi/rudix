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
 *
 * Streaming (R05-11): `generation.delta` text goes into a ref-backed store
 * (`textStore`), not React state, so a token never re-renders the page; only
 * `StreamingMessage` subscribes. `generation.replace` replaces all streamed
 * text, `generation.final` sets the authoritative text, and `chat.completed`
 * stays the source of truth for the finished turn.
 *
 * Reconnect (R05-13): the client reconnects and sends `chat.resume`; this hook
 * discards any `(message_id, stream_sequence)` it already applied, and any
 * second terminal event for a message it already completed.
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
import { resolveChatWsAuthParam } from "@/lib/chat-ws-auth";
import {
  createStreamingTextStore,
  type StreamingTextStore,
} from "@/lib/chat/streaming-text-store";
import { StreamSequenceTracker } from "@/lib/chat/ws-reconnect";

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
  /**
   * Streamed answer text; grows as generation.delta events arrive. A live
   * getter over `textStore`: reading it does not subscribe to updates.
   */
  partialAnswer: string;
  /** Ref-backed streamed text; subscribe with useSyncExternalStore. */
  textStore?: StreamingTextStore;
  /** True while the socket is being re-established for the run in flight. */
  reconnecting?: boolean;
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
  const [textStore] = useState(() => createStreamingTextStore());
  const [reconnecting, setReconnecting] = useState(false);
  const [finalResponse, setFinalResponse] = useState<ChatQueryResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [timelineSteps, setTimelineSteps] = useState<ActivityTimelineStep[]>(
    [],
  );

  const clientRef = useRef<ChatWSClient | null>(null);
  // Keep a stable ref to the current phase to avoid stale closures.
  const phaseRef = useRef<ChatWSPhase>("idle");
  const sequencesRef = useRef(new StreamSequenceTracker());
  const completedRef = useRef(new Set<string>());

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
      // Replayed after a resume, or a duplicate terminal frame: already applied.
      if (!sequencesRef.current.accept(evt.message_id, evt.stream_sequence)) {
        return;
      }
      if (evt.message_id && completedRef.current.has(evt.message_id)) {
        return;
      }
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
          const text = evt.payload?.text;
          if (typeof text === "string") textStore.append(text);
          break;
        }
        case "generation.replace": {
          const text = evt.payload?.text;
          if (typeof text === "string") textStore.replace(text);
          break;
        }
        case "generation.final": {
          const answer = evt.payload?.answer;
          textStore.replace(typeof answer === "string" ? answer : "", {
            final: true,
          });
          break;
        }
        case "chat.resumed":
          setReconnecting(false);
          break;
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
          if (evt.message_id) completedRef.current.add(evt.message_id);
          textStore.reset();
          setReconnecting(false);
          updatePhase("completed");
          break;
        }
        case "chat.cancelled":
          updatePhase("cancelled");
          break;
        case "chat.error":
          setReconnecting(false);
          setError(evt.safe_error_code ?? "unknown_error");
          updatePhase("error");
          break;
        default:
          break;
      }
    },
    [textStore, updatePhase],
  );

  const failRun = useCallback(
    (code: string) => {
      setReconnecting(false);
      if (isTerminal(phaseRef.current)) return;
      setError(code);
      updatePhase("error");
    },
    [updatePhase],
  );

  /** Ensure the WS client is connected (or already connected). */
  const ensureConnected = useCallback((): ChatWSClient => {
    const existing = clientRef.current;
    if (existing) {
      // Reconnect after the socket dropped or the ticket fetch failed;
      // connect() fetches a fresh single-use ticket.
      if (existing.state === "disconnected" || existing.state === "error") {
        void existing.connect();
      }
      return existing;
    }

    const { apiUrl } = getFrontendRuntimeConfig();
    const wsUrl = buildChatWsUrl(apiUrl);

    const client = new ChatWSClient({
      url: wsUrl,
      getAuthParam: resolveChatWsAuthParam,
      onAuthError: () => {
        setError("ws_ticket_unavailable");
        updatePhase("error");
      },
      onEvent: handleEvent,
      onReconnecting: () => setReconnecting(true),
      onReconnected: ({ resumed, flushed }) => {
        setReconnecting(false);
        // The drop came before the server named the message: nothing to resume.
        if (!resumed && !flushed) failRun("resume_unavailable");
      },
      onReconnectFailed: () => failRun("connection_lost"),
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
      onClose: (_code, _reason, willReconnect) => {
        if (!willReconnect && !isTerminal(phaseRef.current)) {
          setError("connection_closed");
          updatePhase("error");
        }
      },
    });

    clientRef.current = client;
    void client.connect();
    return client;
  }, [failRun, handleEvent, updatePhase]);

  const sendQuery = useCallback(
    (payload: ChatQueryRequest & { _scopeLabel?: string }) => {
      if (!isTerminal(phase) && phase !== "idle") return;

      // Reset state for new query.
      textStore.reset();
      sequencesRef.current.reset();
      completedRef.current.clear();
      setReconnecting(false);
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
    [phase, ensureConnected, textStore, updatePhase],
  );

  const cancel = useCallback(() => {
    clientRef.current?.send({ command: "chat.cancel" });
  }, []);

  const reset = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    textStore.reset();
    sequencesRef.current.reset();
    completedRef.current.clear();
    setReconnecting(false);
    setFinalResponse(null);
    setError(null);
    setTimelineSteps([]);
    updatePhase("idle");
  }, [textStore, updatePhase]);

  const isPending =
    phase !== "idle" &&
    phase !== "completed" &&
    phase !== "cancelled" &&
    phase !== "error";

  return {
    phase,
    get partialAnswer() {
      return textStore.getText();
    },
    textStore,
    reconnecting,
    finalResponse,
    error,
    isPending,
    timelineSteps,
    sendQuery,
    cancel,
    reset,
  };
}
