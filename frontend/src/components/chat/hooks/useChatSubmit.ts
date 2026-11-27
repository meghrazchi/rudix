import type { Dispatch, SetStateAction } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  activeThreadKey,
  toTurnResponseFromAgentRun,
  toTurnResponseFromQuery,
} from "@/components/chat/chat-turns";
import { replaceSessionParamInUrl } from "@/components/chat/chat-session-utils";
import {
  AGENTIC_CHAT_ENABLED,
  CHAT_WEBSOCKET_ENABLED,
  DRAFT_SESSION_KEY,
  SESSION_TITLE_MAX_LENGTH,
  type ChatTurn,
} from "@/components/chat/chat-types";
import type { ChatScopeController } from "@/components/chat/hooks/useChatScope";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { ChatSettingsController } from "@/components/chat/hooks/useChatSettings";
import {
  useChatStream,
  type ChatStreamContext,
} from "@/components/chat/hooks/useChatStream";
import { createAgentRun, type AgentRunCreateRequest } from "@/lib/api/agent";
import { getChatWsErrorMessageKey } from "@/lib/chat-ws-errors";
import type { ChatQueryRequest, ChatQueryResponse } from "@/lib/api/chat";
import { isApiClientError } from "@/lib/api/errors";
import { invalidateAfterMutation } from "@/lib/api/query";
import { trackActivationEvent, trackFeatureEvent } from "@/lib/analytics";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";

export function useChatSubmit({
  question,
  setQuestion,
  scope,
  settings,
  session,
}: {
  question: string;
  setQuestion: Dispatch<SetStateAction<string>>;
  scope: ChatScopeController;
  settings: ChatSettingsController;
  session: ChatSessionController;
}) {
  const tc = useTranslations("chat.page");
  const queryClient = useQueryClient();
  const {
    activeSessionId,
    setActiveSessionId,
    setThreadsBySession,
    setSelectedResponseMessageId,
    setPendingQuestion,
    setSubmitRequestId,
    createSessionMutation,
  } = session;
  const {
    scopeMode,
    effectiveDocumentIds,
    hasAvailableDocuments,
    requiresUploadedDocuments,
    isScopeInvalid,
    indexedDocumentsQuery,
    buildScopeLabel,
    buildSourceScopePayload,
  } = scope;
  const { topK, rerank, agenticMode, setAgenticMode, answerLanguage } =
    settings;

  async function handleStreamCompleted(
    response: ChatQueryResponse,
    context: ChatStreamContext,
  ): Promise<void> {
    const resolvedSessionId =
      response.chat_session_id ?? context.sessionId ?? activeSessionId;
    const nextSessionId = resolvedSessionId ?? DRAFT_SESSION_KEY;
    const previousThreadKey = activeThreadKey(context.sessionId);
    const nextTurn: ChatTurn = {
      question: context.question,
      response: toTurnResponseFromQuery(response, context.scopeLabel),
    };

    setThreadsBySession((previous) => {
      const sourceThread = previous[previousThreadKey] ?? [];
      const merged = [...sourceThread, nextTurn];
      const next = { ...previous, [nextSessionId]: merged };
      if (previousThreadKey !== nextSessionId) {
        delete next[previousThreadKey];
      }
      return next;
    });

    setActiveSessionId(resolvedSessionId ?? null);
    setSelectedResponseMessageId(nextTurn.response.message_id);
    replaceSessionParamInUrl(resolvedSessionId ?? null);
    setSubmitRequestId(null);
    setPendingQuestion(null);
    void trackFeatureEvent("feature.chat.question_submitted", {
      surface: "app",
      route: "/chat",
      pageKey: "chat",
      featureArea: "chat",
      count: 1,
    });
    void trackFeatureEvent("feature.chat.answer_rendered", {
      surface: "app",
      route: "/chat",
      pageKey: "chat",
      featureArea: "chat",
      citationCount: nextTurn.response.citations.length,
      hasCitations: nextTurn.response.citations.length > 0,
    });
    void trackActivationEvent("activation.first_question", {
      surface: "app",
      route: "/chat",
      pageKey: "chat",
      featureArea: "chat",
      count: 1,
    });
    if (nextTurn.response.citations.length > 0) {
      void trackActivationEvent("activation.first_cited_answer", {
        surface: "app",
        route: "/chat",
        pageKey: "chat",
        featureArea: "chat",
        citationCount: nextTurn.response.citations.length,
        hasCitations: true,
      });
    }
    await invalidateAfterMutation(queryClient, "chat.query");
  }

  const stream = useChatStream({
    onCompleted: handleStreamCompleted,
    onFailed: (error) => {
      setSubmitRequestId(extractRequestIdFromError(error));
      setPendingQuestion(null);
    },
    onAborted: () => {
      setPendingQuestion(null);
    },
  });

  const agentRunMutation = useMutation({
    mutationFn: (payload: AgentRunCreateRequest) => createAgentRun(payload),
  });

  const isComposerDisabled =
    stream.isPending ||
    agentRunMutation.isPending ||
    createSessionMutation.isPending ||
    question.trim().length === 0 ||
    indexedDocumentsQuery.isError ||
    (!hasAvailableDocuments && requiresUploadedDocuments) ||
    isScopeInvalid;

  const composerError =
    stream.error ?? agentRunMutation.error ?? createSessionMutation.error;
  const composerForbidden = isForbiddenError(composerError);
  const composerWsErrorKey = CHAT_WEBSOCKET_ENABLED
    ? getChatWsErrorMessageKey(stream.wsError)
    : null;
  const composerSubmitButtonLabel = createSessionMutation.isPending
    ? tc("composerStarting")
    : agentRunMutation.isPending
      ? tc("composerAgentRunning")
      : stream.isPending
        ? (stream.phaseLabel ?? tc("composerGenerating"))
        : tc("composerSend");
  const regenerateDisabled =
    stream.httpPending ||
    agentRunMutation.isPending ||
    createSessionMutation.isPending ||
    (!hasAvailableDocuments && scopeMode !== "none");

  async function submitQuestion(): Promise<void> {
    const trimmedQuestion = question.trim();
    await submitQuestionText(trimmedQuestion, true);
  }

  async function submitQuestionText(
    questionText: string,
    clearComposerOnSubmit: boolean,
  ): Promise<void> {
    const trimmedQuestion = questionText.trim();
    if (
      !trimmedQuestion ||
      stream.httpPending ||
      agentRunMutation.isPending ||
      createSessionMutation.isPending ||
      isScopeInvalid ||
      (!hasAvailableDocuments &&
        requiresUploadedDocuments &&
        !indexedDocumentsQuery.isLoading)
    ) {
      return;
    }

    setSubmitRequestId(null);
    setPendingQuestion(trimmedQuestion);
    if (clearComposerOnSubmit) {
      setQuestion("");
    }

    const currentScopeLabel = buildScopeLabel();
    const shouldUseAgenticChat = AGENTIC_CHAT_ENABLED && agenticMode;

    if (shouldUseAgenticChat) {
      const previousThreadKey = activeThreadKey(activeSessionId);
      let fallbackToStandardQuery = false;
      const payload: AgentRunCreateRequest = {
        agentic_mode: true,
        request: {
          objective: trimmedQuestion,
          mode: "answer",
          question: trimmedQuestion,
          document_ids:
            scopeMode !== "collection" && effectiveDocumentIds.length > 0
              ? effectiveDocumentIds
              : undefined,
          source_scope: buildSourceScopePayload() ?? undefined,
          top_k: topK,
          rerank,
        },
      };

      try {
        const response = await agentRunMutation.mutateAsync(payload);
        const nextTurn: ChatTurn = {
          question: trimmedQuestion,
          response: {
            ...toTurnResponseFromAgentRun(response.run),
            scope_label: currentScopeLabel,
          },
        };
        setThreadsBySession((previous) => {
          const sourceThread = previous[previousThreadKey] ?? [];
          return {
            ...previous,
            [previousThreadKey]: [...sourceThread, nextTurn],
          };
        });
        setSelectedResponseMessageId(nextTurn.response.message_id);
        setSubmitRequestId(null);
        setPendingQuestion(null);
        await invalidateAfterMutation(queryClient, "agent.run");
        return;
      } catch (error) {
        if (isApiClientError(error) && error.code === "feature_not_available") {
          // Backend agentic feature is off; fall back to standard query flow.
          setAgenticMode(false);
          agentRunMutation.reset();
          setSubmitRequestId(null);
          fallbackToStandardQuery = true;
        } else {
          setSubmitRequestId(extractRequestIdFromError(error));
          if (clearComposerOnSubmit) {
            setQuestion(trimmedQuestion);
          }
          setPendingQuestion(null);
          return;
        }
      }
      if (!fallbackToStandardQuery) {
        return;
      }
    }

    let targetSessionId = activeSessionId;
    if (!targetSessionId) {
      try {
        const createdSession = await createSessionMutation.mutateAsync(
          trimmedQuestion.slice(0, SESSION_TITLE_MAX_LENGTH),
        );
        targetSessionId = createdSession.session_id;
        setActiveSessionId(createdSession.session_id);
        replaceSessionParamInUrl(createdSession.session_id);
      } catch (error) {
        setSubmitRequestId(extractRequestIdFromError(error));
        setPendingQuestion(null);
        if (clearComposerOnSubmit) {
          setQuestion(trimmedQuestion);
        }
        return;
      }
    }

    const backendScopeMode: ChatQueryRequest["scope_mode"] =
      scopeMode === "connectors" ? "all" : scopeMode;

    stream.send(
      {
        question: trimmedQuestion,
        chat_session_id: targetSessionId,
        document_ids:
          scopeMode !== "collection" &&
          requiresUploadedDocuments &&
          effectiveDocumentIds.length > 0
            ? effectiveDocumentIds
            : undefined,
        top_k: topK,
        rerank,
        scope_mode: backendScopeMode,
        source_scope: buildSourceScopePayload() ?? undefined,
        answer_language: answerLanguage !== "auto" ? answerLanguage : undefined,
        _scopeLabel: currentScopeLabel,
      },
      {
        onError: (error) => {
          setSubmitRequestId(extractRequestIdFromError(error));
          if (clearComposerOnSubmit) {
            setQuestion(trimmedQuestion);
          }
          setPendingQuestion(null);
        },
      },
    );
  }

  return {
    stream,
    agentRunMutation,
    isComposerDisabled,
    composerError,
    composerForbidden,
    composerWsErrorKey,
    composerSubmitButtonLabel,
    regenerateDisabled,
    submitQuestion,
    submitQuestionText,
  };
}

export type ChatSubmitController = ReturnType<typeof useChatSubmit>;
