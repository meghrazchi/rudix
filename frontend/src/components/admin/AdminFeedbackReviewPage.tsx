"use client";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import { extractRequestIdFromError } from "@/lib/forbidden";
import { useFeedbackReviewController } from "@/components/admin/feedback-review/useFeedbackReviewController";
import { FeedbackSummary } from "@/components/admin/feedback-review/FeedbackSummary";
import { FeedbackFilters } from "@/components/admin/feedback-review/FeedbackFilters";
import { FeedbackResults } from "@/components/admin/feedback-review/FeedbackResults";
import { FeedbackOverlays } from "@/components/admin/feedback-review/FeedbackOverlays";

export function AdminFeedbackReviewPage() {
  const ctl = useFeedbackReviewController();
  const { t, isAdminUser, forbiddenError } = ctl;

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.restrictedTitle")}
          description={t("access.restrictedDescription")}
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={t("access.unavailableTitle")}
          description={t("access.unavailableDescription")}
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  return (
    <section className="space-y-5 bg-[#fcf8ff] px-4 py-5 lg:px-8 lg:py-8">
      <FeedbackSummary ctl={ctl} />
      <FeedbackFilters ctl={ctl} />
      <FeedbackResults ctl={ctl} />
      <FeedbackOverlays ctl={ctl} />
    </section>
  );
}
