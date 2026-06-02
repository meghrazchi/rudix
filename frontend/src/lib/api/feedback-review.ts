import { apiRequest } from "@/lib/api/request";

export type FeedbackReviewStatus =
  | "new"
  | "triaged"
  | "needs_document"
  | "eval_created"
  | "fixed"
  | "rejected"
  | "duplicate";

export type FeedbackSeverity = "low" | "medium" | "high";

export type FeedbackSummary = {
  feedback_id: string;
  message_id: string;
  submitter_user_id: string;
  rating: "up" | "down";
  reason: string | null;
  comment: string | null;
  submitted_at: string;
};

export type MessageSummary = {
  message_id: string;
  session_id: string;
  content_preview: string;
  confidence_score: number | null;
  model_name: string | null;
  latency_ms: number | null;
  created_at: string;
};

export type FeedbackReviewItemResponse = {
  review_id: string;
  feedback_id: string;
  organization_id: string;
  status: FeedbackReviewStatus;
  severity: FeedbackSeverity;
  reviewer_id: string | null;
  reviewer_notes: string | null;
  linked_eval_question_id: string | null;
  linked_document_id: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  feedback: FeedbackSummary | null;
  message: MessageSummary | null;
};

export type FeedbackReviewListResponse = {
  items: FeedbackReviewItemResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type FeedbackReviewListParams = {
  status?: FeedbackReviewStatus | null;
  severity?: FeedbackSeverity | null;
  rating?: "up" | "down" | null;
  reason?: string | null;
  reviewer_id?: string | null;
  limit?: number;
  offset?: number;
};

export type TriageFeedbackPayload = {
  severity: FeedbackSeverity;
  reviewer_notes?: string | null;
};

export type UpdateReviewItemPayload = {
  status?: FeedbackReviewStatus | null;
  severity?: FeedbackSeverity | null;
  reviewer_notes?: string | null;
  linked_eval_question_id?: string | null;
  linked_document_id?: string | null;
};

export async function listFeedbackReviewItems(
  params: FeedbackReviewListParams = {},
): Promise<FeedbackReviewListResponse> {
  return apiRequest<FeedbackReviewListResponse>("/feedback-review", {
    query: {
      status: params.status ?? undefined,
      severity: params.severity ?? undefined,
      rating: params.rating ?? undefined,
      reason: params.reason ?? undefined,
      reviewer_id: params.reviewer_id ?? undefined,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function getFeedbackReviewItem(
  reviewId: string,
): Promise<FeedbackReviewItemResponse> {
  return apiRequest<FeedbackReviewItemResponse>(
    `/feedback-review/${encodeURIComponent(reviewId)}`,
  );
}

export async function triageFeedback(
  feedbackId: string,
  payload: TriageFeedbackPayload,
): Promise<FeedbackReviewItemResponse> {
  return apiRequest<FeedbackReviewItemResponse>(
    `/feedback-review/feedback/${encodeURIComponent(feedbackId)}/triage`,
    { method: "POST", json: payload },
  );
}

export async function updateFeedbackReviewItem(
  reviewId: string,
  payload: UpdateReviewItemPayload,
): Promise<FeedbackReviewItemResponse> {
  return apiRequest<FeedbackReviewItemResponse>(
    `/feedback-review/${encodeURIComponent(reviewId)}`,
    { method: "PATCH", json: payload },
  );
}

export function buildFeedbackReviewExportUrl(
  params: Omit<FeedbackReviewListParams, "limit" | "offset"> = {},
): string {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.severity) query.set("severity", params.severity);
  if (params.rating) query.set("rating", params.rating);
  if (params.reason) query.set("reason", params.reason);
  const qs = query.toString();
  return `/feedback-review/export${qs ? `?${qs}` : ""}`;
}
