import { useState } from "react";

import { useMutation } from "@tanstack/react-query";

import {
  deleteMessageFeedback,
  submitMessageFeedback,
  type FeedbackReason,
  type MessageFeedbackResponse,
} from "@/lib/api/feedback";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

export function useChatFeedback() {
  const chatFeedbackEnabled = getFrontendRuntimeConfig().features.feedback;
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<
    Record<string, MessageFeedbackResponse>
  >({});
  const [feedbackModalMessageId, setFeedbackModalMessageId] = useState<
    string | null
  >(null);
  const [trustPanelFeedbackMessageId, setTrustPanelFeedbackMessageId] =
    useState<string | null>(null);
  const [trustPanelFeedbackContext, setTrustPanelFeedbackContext] = useState<{
    warnings: string[];
    traceId: string | null;
    trustScore: number;
    trustLevel: string | null;
  } | null>(null);

  const feedbackSubmitMutation = useMutation({
    mutationFn: ({
      messageId,
      rating,
      reason,
      comment,
      category,
    }: {
      messageId: string;
      rating: "up" | "down";
      reason?: FeedbackReason | null;
      comment?: string | null;
      category?: import("@/lib/api/feedback").FeedbackCategory | null;
    }) =>
      submitMessageFeedback(messageId, { rating, reason, comment, category }),
    onSuccess: (data) => {
      setFeedbackByMessageId((previous) => ({
        ...previous,
        [data.message_id]: data,
      }));
    },
  });

  const feedbackDeleteMutation = useMutation({
    mutationFn: (messageId: string) => deleteMessageFeedback(messageId),
    onSuccess: (_, messageId) => {
      setFeedbackByMessageId((previous) => {
        const next = { ...previous };
        delete next[messageId];
        return next;
      });
    },
  });

  const trustPanelFeedbackMutation = useMutation({
    mutationFn: ({
      messageId,
      category,
      comment,
      selectedCitationIds,
      traceId,
      trustScore,
      trustLevel,
      citations,
      debug,
      trustMetadata,
    }: {
      messageId: string;
      category: import("@/lib/api/feedback").FeedbackCategory | null;
      comment: string | null;
      selectedCitationIds: string[];
      traceId: string | null;
      trustScore: number | null;
      trustLevel: string | null;
      citations: import("@/lib/api/chat").ChatCitationResponse[];
      debug: import("@/lib/api/chat").ChatDebugResponse | null;
      trustMetadata:
        | import("@/lib/api/trust_metadata").AnswerTrustMetadataResponse
        | null
        | undefined;
    }) =>
      submitMessageFeedback(messageId, {
        rating: "down",
        category,
        comment,
        diagnostics: {
          trust_metadata: trustMetadata
            ? {
                confidence: trustMetadata.confidence,
                retrieval: trustMetadata.retrieval,
              }
            : undefined,
          trust_score: trustScore ?? undefined,
          trust_level: trustLevel ?? undefined,
          trace_id: traceId ?? undefined,
          selected_citation_ids:
            selectedCitationIds.length > 0 ? selectedCitationIds : undefined,
          model_name: debug?.llm_model ?? undefined,
          citations: citations.slice(0, 20).map((c) => ({
            document_id: c.document_id,
            chunk_id: c.chunk_id,
            filename: c.filename,
            score: c.score,
          })),
        },
      }),
    onSuccess: (data) => {
      setFeedbackByMessageId((previous) => ({
        ...previous,
        [data.message_id]: data,
      }));
      setTrustPanelFeedbackMessageId(null);
      setTrustPanelFeedbackContext(null);
    },
  });

  return {
    chatFeedbackEnabled,
    feedbackByMessageId,
    setFeedbackByMessageId,
    feedbackModalMessageId,
    setFeedbackModalMessageId,
    trustPanelFeedbackMessageId,
    setTrustPanelFeedbackMessageId,
    trustPanelFeedbackContext,
    setTrustPanelFeedbackContext,
    feedbackSubmitMutation,
    feedbackDeleteMutation,
    trustPanelFeedbackMutation,
  };
}

export type ChatFeedbackController = ReturnType<typeof useChatFeedback>;
