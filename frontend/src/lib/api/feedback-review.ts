import type { Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";
import type { FeedbackCategory } from "@/lib/api/feedback";

type Schemas = components["schemas"];

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

export type FeedbackSummary = Served<Schemas["FeedbackSummaryResponse"]>;

export type MessageSummary = Served<Schemas["MessageSummaryResponse"]>;

export type FeedbackReviewItemResponse = Served<
  Schemas["FeedbackReviewItemResponse"]
>;

export type FeedbackReviewListResponse = Served<
  Schemas["FeedbackReviewListResponse"]
>;

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

export type TriageFeedbackPayload = Schemas["TriageFeedbackRequest"];

export type UpdateReviewItemPayload = Schemas["UpdateReviewItemRequest"];

export type ConvertToEvalCasePayload = WithOptional<
  Schemas["ConvertToEvalCaseRequest"],
  "default_difficulty"
>;

export type ConvertToEvalCaseResponse = Served<
  Schemas["ConvertToEvalCaseResponse"]
>;

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
