import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

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

export type FeedbackDiagnostics = Schemas["FeedbackDiagnostics"];

export type SubmitFeedbackPayload = Overlay<
  Schemas["SubmitFeedbackRequest"],
  {
    rating: FeedbackRating;
    reason?: FeedbackReason | null;
    category?: FeedbackCategory | null;
  }
>;

export type MessageFeedbackResponse = Served<
  Schemas["MessageFeedbackResponse"]
>;

export type FeedbackCategoryMetric = Served<Schemas["FeedbackCategoryMetric"]>;

export type FeedbackMetricsResponse = Served<
  Schemas["FeedbackMetricsResponse"]
>;

export type SessionFeedbackListResponse = Served<
  Schemas["SessionFeedbackListResponse"]
>;

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
