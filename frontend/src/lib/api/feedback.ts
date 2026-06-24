import { apiRequest } from "@/lib/api/request";

export type FeedbackRating = "up" | "down";

export type FeedbackReason =
  | "wrong_citation"
  | "hallucination"
  | "outdated_source"
  | "missing_document"
  | "unsafe_content"
  | "other";

export type FeedbackCategory =
  | "wrong_answer"
  | "bad_citation"
  | "missing_source"
  | "outdated_source"
  | "hallucination_risk"
  | "conflict_not_detected"
  | "unclear_answer"
  | "missing_information"
  | "low_confidence"
  | "unsafe_response"
  // F316 — trust-panel accuracy categories
  | "missing_citation"
  | "stale_source"
  | "conflicting_source"
  | "not_enough_detail"
  | "should_have_said_not_found";

export type FeedbackDiagnostics = {
  question_text?: string | null;
  answer_text?: string | null;
  citations?: Record<string, unknown>[] | null;
  retrieval_diagnostics?: Record<string, unknown> | null;
  model_name?: string | null;
  rag_profile_id?: string | null;
  llm_provider?: string | null;
  // F316 — trust-panel accuracy fields
  trust_metadata?: Record<string, unknown> | null;
  trust_score?: number | null;
  trust_level?: string | null;
  trace_id?: string | null;
  selected_citation_ids?: string[] | null;
};

export type SubmitFeedbackPayload = {
  rating: FeedbackRating;
  reason?: FeedbackReason | null;
  comment?: string | null;
  category?: FeedbackCategory | null;
  diagnostics?: FeedbackDiagnostics | null;
};

export type MessageFeedbackResponse = {
  feedback_id: string;
  message_id: string;
  user_id: string;
  rating: FeedbackRating;
  reason: FeedbackReason | null;
  comment: string | null;
  category: FeedbackCategory | null;
  question_text: string | null;
  answer_text: string | null;
  model_name: string | null;
  rag_profile_id: string | null;
  llm_provider: string | null;
  trust_metadata: Record<string, unknown> | null;
  retain_until: string | null;
  redacted_at: string | null;
  converted_to_eval_question_id: string | null;
  // F316 fields
  trace_id: string | null;
  selected_citation_ids: string[] | null;
  created_at: string;
  updated_at: string;
};

export type FeedbackCategoryMetric = {
  category: string;
  count: number;
  avg_confidence_score: number | null;
};

export type FeedbackMetricsResponse = {
  period_days: number;
  total_feedback: number;
  categories: FeedbackCategoryMetric[];
};

export type SessionFeedbackListResponse = {
  items: MessageFeedbackResponse[];
  total: number;
};

export async function submitMessageFeedback(
  messageId: string,
  payload: SubmitFeedbackPayload,
): Promise<MessageFeedbackResponse> {
  return apiRequest<MessageFeedbackResponse>(
    `/chat/messages/${encodeURIComponent(messageId)}/feedback`,
    { method: "PUT", json: payload },
  );
}

export async function deleteMessageFeedback(messageId: string): Promise<void> {
  return apiRequest<void>(
    `/chat/messages/${encodeURIComponent(messageId)}/feedback`,
    { method: "DELETE" },
  );
}

export async function listSessionFeedback(
  sessionId: string,
): Promise<SessionFeedbackListResponse> {
  return apiRequest<SessionFeedbackListResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/feedback`,
  );
}

export async function getFeedbackMetrics(
  days?: number,
): Promise<FeedbackMetricsResponse> {
  return apiRequest<FeedbackMetricsResponse>("/feedback-review/metrics", {
    query: { days: days ?? 30 },
  });
}
