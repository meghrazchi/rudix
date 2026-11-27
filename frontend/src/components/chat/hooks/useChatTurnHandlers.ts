import { useLayoutEffect, useMemo, useRef } from "react";

import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";
import type { ChatOverlaysController } from "@/components/chat/hooks/useChatOverlays";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { CitationPanelController } from "@/components/chat/hooks/useCitationPanel";
import type { ChatCitationResponse } from "@/lib/api/chat";
import { copyToClipboard, formatAnswerAsMarkdown } from "@/lib/export-utils";

export type CitationPreviewSet = {
  citations: ChatCitationResponse[];
  initialIndex: number;
};

/**
 * Actions of a completed chat turn. The object and every function in it keep
 * their identity for the lifetime of the thread, so memoised turns
 * (`ChatTurnItem` is `React.memo`) never re-render because a parent did
 * (R05-11). Each call reads the latest controllers.
 */
export type ChatTurnHandlers = {
  toggleTrustPanel: (messageId: string) => void;
  copyAnswer: (turn: ChatTurn) => void;
  shareAnswer: (messageId: string) => void;
  rateHelpful: (messageId: string) => void;
  reportIssue: (messageId: string) => void;
  regenerate: (question: string) => void;
  openKnowledgeHub: (messageId: string) => void;
  previewCitations: (messageId: string, set: CitationPreviewSet) => void;
};

export type ChatTurnHandlerDeps = {
  session: Pick<ChatSessionController, "setSelectedResponseMessageId">;
  panel: Pick<
    CitationPanelController,
    "setIsKnowledgeHubOpen" | "setPreviewCitationSet"
  >;
  feedback: Pick<
    ChatFeedbackController,
    | "feedbackByMessageId"
    | "feedbackDeleteMutation"
    | "feedbackSubmitMutation"
    | "setFeedbackModalMessageId"
  >;
  overlays: Pick<
    ChatOverlaysController,
    | "openTrustPanelMessageId"
    | "setOpenTrustPanelMessageId"
    | "setCopiedMessageId"
    | "setAnswerShareMessageId"
  >;
  regenerate: (question: string) => void;
};

export function useChatTurnHandlers(deps: ChatTurnHandlerDeps) {
  const latest = useRef(deps);
  useLayoutEffect(() => {
    latest.current = deps;
  });

  return useMemo<ChatTurnHandlers>(
    () => ({
      toggleTrustPanel(messageId) {
        const { session, overlays } = latest.current;
        session.setSelectedResponseMessageId(messageId);
        overlays.setOpenTrustPanelMessageId(
          overlays.openTrustPanelMessageId === messageId ? null : messageId,
        );
      },
      copyAnswer(turn) {
        const md = formatAnswerAsMarkdown({
          question: turn.question,
          answer: turn.response.answer,
          citations: turn.response.citations,
          created_at: turn.response.created_at,
        });
        void copyToClipboard(md).then(() => {
          const { setCopiedMessageId } = latest.current.overlays;
          setCopiedMessageId(turn.response.message_id);
          setTimeout(() => setCopiedMessageId(null), 2000);
        });
      },
      shareAnswer(messageId) {
        latest.current.overlays.setAnswerShareMessageId(messageId);
      },
      rateHelpful(messageId) {
        const { feedback } = latest.current;
        if (feedback.feedbackByMessageId[messageId]?.rating === "up") {
          feedback.feedbackDeleteMutation.mutate(messageId);
        } else {
          feedback.feedbackSubmitMutation.mutate({ messageId, rating: "up" });
        }
      },
      reportIssue(messageId) {
        latest.current.feedback.setFeedbackModalMessageId(messageId);
      },
      regenerate(question) {
        latest.current.regenerate(question);
      },
      openKnowledgeHub(messageId) {
        const { session, panel } = latest.current;
        session.setSelectedResponseMessageId(messageId);
        panel.setIsKnowledgeHubOpen(true);
      },
      previewCitations(messageId, set) {
        const { session, panel } = latest.current;
        session.setSelectedResponseMessageId(messageId);
        panel.setIsKnowledgeHubOpen(false);
        panel.setPreviewCitationSet(set);
      },
    }),
    [],
  );
}
