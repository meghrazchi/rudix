import { useEffect, useRef } from "react";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CHAT_WEBSOCKET_ENABLED } from "@/components/chat/chat-types";
import {
  queryChat,
  type ChatQueryRequest,
  type ChatQueryResponse,
} from "@/lib/api/chat";
import { useChatWebSocket } from "@/lib/use-chat-websocket";

export type ChatStreamPayload = ChatQueryRequest & { _scopeLabel?: string };

export type ChatStreamContext = {
  question: string;
  sessionId: string | null;
  scopeLabel: string | null;
};

type ChatStreamOptions = {
  /** Called once with the final response, for both transports. */
  onCompleted: (
    response: ChatQueryResponse,
    context: ChatStreamContext,
  ) => void | Promise<void>;
  /** Called when the HTTP request fails. */
  onFailed: (error: unknown) => void;
  /** Called when the WebSocket run errors or is cancelled. */
  onAborted: () => void;
};

/**
 * One interface over the WebSocket transport (useChatWebSocket) and the HTTP
 * transport (queryChat mutation). The transport is chosen by
 * NEXT_PUBLIC_CHAT_WEBSOCKET_ENABLED.
 */
export function useChatStream(options: ChatStreamOptions) {
  const tc = useTranslations("chat.page");
  const wsChat = useChatWebSocket();
  // Track the WS-submitted question + scopeLabel so the completion effect can
  // build the ChatTurn with the same data the HTTP path would have.
  const wsPendingRef = useRef<ChatStreamContext | null>(null);

  useEffect(() => {
    if (!CHAT_WEBSOCKET_ENABLED) return;
    if (wsChat.phase !== "completed" || !wsChat.finalResponse) return;
    const response = wsChat.finalResponse;
    const pending = wsPendingRef.current;
    if (!pending) return;

    wsPendingRef.current = null;
    queueMicrotask(() => {
      void options.onCompleted(response, pending);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsChat.phase, wsChat.finalResponse]);

  useEffect(() => {
    if (!CHAT_WEBSOCKET_ENABLED) return;
    if (wsChat.phase !== "error" && wsChat.phase !== "cancelled") return;
    wsPendingRef.current = null;
    queueMicrotask(() => {
      options.onAborted();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsChat.phase]);

  const queryMutation = useMutation({
    mutationFn: (payload: ChatStreamPayload) => queryChat(payload),
    onSuccess: async (response, payload) => {
      await options.onCompleted(response, {
        question: payload.question,
        sessionId: payload.chat_session_id ?? null,
        scopeLabel: payload._scopeLabel ?? null,
      });
    },
    onError: (error) => {
      options.onFailed(error);
    },
  });

  function send(
    payload: ChatStreamPayload,
    mutateOptions?: { onError?: (error: unknown) => void },
  ): void {
    if (CHAT_WEBSOCKET_ENABLED) {
      wsPendingRef.current = {
        question: payload.question,
        sessionId: payload.chat_session_id ?? null,
        scopeLabel: payload._scopeLabel ?? null,
      };
      wsChat.sendQuery(payload);
      return;
    }
    queryMutation.mutate(payload, { onError: mutateOptions?.onError });
  }

  const phaseLabel = CHAT_WEBSOCKET_ENABLED
    ? wsChat.phase === "retrieving"
      ? tc("wsRetrieving")
      : wsChat.phase === "reranking"
        ? tc("wsReranking")
        : wsChat.phase === "generating"
          ? tc("wsGenerating")
          : wsChat.phase === "validating_citations"
            ? tc("wsValidating")
            : wsChat.isPending
              ? tc("wsConnecting")
              : null
    : null;

  return {
    send,
    cancel: () => wsChat.cancel(),
    phase: wsChat.phase,
    phaseLabel,
    partialAnswer: wsChat.partialAnswer,
    finalResponse: wsChat.finalResponse,
    timelineSteps: wsChat.timelineSteps,
    /** WebSocket error code, when the WebSocket transport is active. */
    wsError: wsChat.error,
    /** Transport-aware error, as an Error instance. */
    error: ((CHAT_WEBSOCKET_ENABLED && wsChat.error
      ? new Error(wsChat.error)
      : null) ??
      (!CHAT_WEBSOCKET_ENABLED ? queryMutation.error : null)) as Error | null,
    isPending: CHAT_WEBSOCKET_ENABLED
      ? wsChat.isPending
      : queryMutation.isPending,
    /** True only while the HTTP mutation is in flight. */
    httpPending: queryMutation.isPending,
  };
}

export type ChatStreamController = ReturnType<typeof useChatStream>;
