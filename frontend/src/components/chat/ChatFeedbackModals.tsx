import { useTranslations } from "next-intl";

import {
  TrustPanelFeedbackModal,
  type TrustPanelCitationRef,
} from "@/components/chat/TrustPanelFeedbackModal";
import { FeedbackModal } from "@/components/chat/FeedbackModal";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatFeedbackController } from "@/components/chat/hooks/useChatFeedback";

export function ChatFeedbackModals({
  feedback,
  thread,
}: {
  feedback: ChatFeedbackController;
  thread: ChatTurn[];
}) {
  const t = useTranslations("chat.feedback");
  const {
    chatFeedbackEnabled,
    feedbackModalMessageId,
    setFeedbackModalMessageId,
    feedbackByMessageId,
    feedbackSubmitMutation,
    feedbackDeleteMutation,
    trustPanelFeedbackMessageId,
    setTrustPanelFeedbackMessageId,
    trustPanelFeedbackContext,
    setTrustPanelFeedbackContext,
    trustPanelFeedbackMutation,
  } = feedback;

  return (
    <>
      {chatFeedbackEnabled && feedbackModalMessageId ? (
        <FeedbackModal
          existingReason={feedbackByMessageId[feedbackModalMessageId]?.reason}
          existingCategory={
            feedbackByMessageId[feedbackModalMessageId]?.category
          }
          existingComment={feedbackByMessageId[feedbackModalMessageId]?.comment}
          isSubmitting={feedbackSubmitMutation.isPending}
          isDeleting={feedbackDeleteMutation.isPending}
          onSubmit={(reason, comment, category) => {
            feedbackSubmitMutation.mutate(
              {
                messageId: feedbackModalMessageId,
                rating: "down",
                reason,
                comment,
                category,
              },
              { onSuccess: () => setFeedbackModalMessageId(null) },
            );
          }}
          onDelete={() => {
            feedbackDeleteMutation.mutate(feedbackModalMessageId, {
              onSuccess: () => setFeedbackModalMessageId(null),
            });
          }}
          onClose={() => setFeedbackModalMessageId(null)}
        />
      ) : null}
      {chatFeedbackEnabled &&
      trustPanelFeedbackMessageId &&
      trustPanelFeedbackContext
        ? (() => {
            const activeTurn = thread.find(
              (turn) =>
                turn.response?.message_id === trustPanelFeedbackMessageId,
            );
            const panelCitations: TrustPanelCitationRef[] = (
              activeTurn?.response?.citations ?? []
            ).map((c) => ({
              document_id: c.document_id,
              chunk_id: c.chunk_id,
              title: c.source_title ?? c.filename ?? t("unknownSource"),
            }));
            return (
              <TrustPanelFeedbackModal
                activeWarnings={trustPanelFeedbackContext.warnings}
                citations={panelCitations}
                traceId={trustPanelFeedbackContext.traceId}
                trustScore={trustPanelFeedbackContext.trustScore}
                trustLevel={trustPanelFeedbackContext.trustLevel}
                isSubmitting={trustPanelFeedbackMutation.isPending}
                onSubmit={({
                  category,
                  comment,
                  selectedCitationIds,
                  traceId,
                  trustScore,
                  trustLevel,
                }) => {
                  trustPanelFeedbackMutation.mutate({
                    messageId: trustPanelFeedbackMessageId,
                    category,
                    comment,
                    selectedCitationIds,
                    traceId,
                    trustScore,
                    trustLevel,
                    citations: activeTurn?.response?.citations ?? [],
                    debug: activeTurn?.response?.debug ?? null,
                    trustMetadata: activeTurn?.response?.trust_metadata ?? null,
                  });
                }}
                onClose={() => {
                  setTrustPanelFeedbackMessageId(null);
                  setTrustPanelFeedbackContext(null);
                }}
              />
            );
          })()
        : null}
    </>
  );
}
