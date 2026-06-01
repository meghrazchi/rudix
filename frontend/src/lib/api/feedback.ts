import { apiRequest } from "@/lib/api/request";

export type FeedbackRating = "up" | "down";

export type FeedbackReason =
  | "wrong_citation"
  | "hallucination"
  | "outdated_source"
  | "missing_document"
  | "unsafe_content"
  | "other";

export type SubmitFeedbackPayload = {
  rating: FeedbackRating;
  reason?: FeedbackReason | null;
  comment?: string | null;
};

export type MessageFeedbackResponse = {
  feedback_id: string;
  message_id: string;
  user_id: string;
  rating: FeedbackRating;
  reason: FeedbackReason | null;
  comment: string | null;
  created_at: string;
  updated_at: string;
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
