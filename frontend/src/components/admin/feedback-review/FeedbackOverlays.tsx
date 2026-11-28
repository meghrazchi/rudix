"use client";

import { CreateVerifiedAnswerModal } from "@/components/verified-answers/CreateVerifiedAnswerModal";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { ConvertToEvalModal } from "@/components/admin/feedback-review/ConvertToEvalModal";
import { useFeedbackReviewController } from "@/components/admin/feedback-review/useFeedbackReviewController";

export function FeedbackOverlays({
  ctl,
}: {
  ctl: ReturnType<typeof useFeedbackReviewController>;
}) {
  const {
    queryClient,
    setSelectedItem,
    convertReviewId,
    setConvertReviewId,
    saveKnowledgeCardReviewId,
    setSaveKnowledgeCardReviewId,
    updateMutation,
  } = ctl;

  return (
    <>
      {updateMutation.isError ? (
        <p className="text-sm text-rose-700">
          {getApiErrorMessage(updateMutation.error)}
        </p>
      ) : null}

      {convertReviewId ? (
        <ConvertToEvalModal
          reviewId={convertReviewId}
          onClose={() => setConvertReviewId(null)}
          onConverted={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.feedbackReview.all,
            });
            setConvertReviewId(null);
            setSelectedItem(null);
          }}
        />
      ) : null}
      {saveKnowledgeCardReviewId ? (
        <CreateVerifiedAnswerModal
          mode={{ kind: "from-feedback", reviewId: saveKnowledgeCardReviewId }}
          onClose={() => setSaveKnowledgeCardReviewId(null)}
          invalidateKey={["verified-answers"]}
        />
      ) : null}
    </>
  );
}
