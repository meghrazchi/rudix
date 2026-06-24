import { apiRequest } from "@/lib/api/request";
import type { FeedbackCategory } from "@/lib/api/feedback";

export type FeedbackReviewStatus =
  | "new"
  | "triaged"
  | "accepted"
  | "rejected"
  | "needs_document_update"
  | "needs_prompt_retrieval_fix"
  | "converted_to_evaluation"
  | "resolved"
  | "needs_document"
  | "eval_created"
  | "fixed"
  | "duplicate";

export type FeedbackSeverity = "low" | "medium" | "high";

export type FeedbackSummary = {
  feedback_id: string;
  answer_id: string | null;
  message_id: string;
  submitter_user_id: string;
  rating: "up" | "down";
  reason: string | null;
  comment: string | null;
  // F303 fields
  category: FeedbackCategory | null;
  question_text: string | null;
  answer_text: string | null;
  model_name: string | null;
  llm_provider: string | null;
  citations: Record<string, unknown>[] | null;
  retrieval_diagnostics: Record<string, unknown> | null;
  trust_metadata: Record<string, unknown> | null;
  confidence_score: number | null;
  redacted_at: string | null;
  converted_to_eval_question_id: string | null;
  // F316 fields
  trace_id: string | null;
  selected_citation_ids: string[] | null;
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
  category?: FeedbackCategory | null;
  workspace_id?: string | null;
  document_id?: string | null;
  model_name?: string | null;
  confidence_min?: number | null;
  confidence_max?: number | null;
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
  reviewer_id?: string | null;
  linked_eval_question_id?: string | null;
  linked_document_id?: string | null;
};

export type ConvertToEvalCasePayload = {
  evaluation_set_id: string;
  default_difficulty?: "easy" | "medium" | "hard";
  reviewer_notes?: string | null;
};

export type ConvertToEvalCaseResponse = {
  review_id: string;
  evaluation_set_id: string;
  evaluation_question_id: string;
  question: string;
  already_existed: boolean;
};

export async function listFeedbackReviewItems(
  params: FeedbackReviewListParams = {},
): Promise<FeedbackReviewListResponse> {
  return apiRequest<FeedbackReviewListResponse>("/feedback-review", {
    query: {
      status: params.status ?? undefined,
      category: params.category ?? undefined,
      workspace: params.workspace_id ?? undefined,
      document: params.document_id ?? undefined,
      model: params.model_name ?? undefined,
      confidence_min: params.confidence_min ?? undefined,
      confidence_max: params.confidence_max ?? undefined,
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

export async function convertFeedbackToEvalCase(
  reviewId: string,
  payload: ConvertToEvalCasePayload,
): Promise<ConvertToEvalCaseResponse> {
  return apiRequest<ConvertToEvalCaseResponse>(
    `/feedback-review/${encodeURIComponent(reviewId)}/convert-to-eval`,
    { method: "POST", json: payload },
  );
}

export async function redactFeedbackDiagnostics(
  feedbackId: string,
): Promise<FeedbackReviewItemResponse> {
  return apiRequest<FeedbackReviewItemResponse>(
    `/feedback-review/feedback/${encodeURIComponent(feedbackId)}/redact`,
    { method: "POST", json: {} },
  );
}

export function buildFeedbackReviewExportUrl(
  params: Omit<FeedbackReviewListParams, "limit" | "offset"> = {},
): string {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.category) query.set("category", params.category);
  if (params.workspace_id) query.set("workspace", params.workspace_id);
  if (params.document_id) query.set("document", params.document_id);
  if (params.model_name) query.set("model", params.model_name);
  if (params.confidence_min != null) {
    query.set("confidence_min", String(params.confidence_min));
  }
  if (params.confidence_max != null) {
    query.set("confidence_max", String(params.confidence_max));
  }
  if (params.severity) query.set("severity", params.severity);
  if (params.rating) query.set("rating", params.rating);
  if (params.reason) query.set("reason", params.reason);
  const qs = query.toString();
  return `/feedback-review/export${qs ? `?${qs}` : ""}`;
}
