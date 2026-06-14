import { apiRequest } from "@/lib/api/request";

export type AnswerShareAccessMode = "org_only" | "specific_users";

export type CreateAnswerSharePayload = {
  access_mode?: AnswerShareAccessMode;
  allowed_user_ids?: string[];
  password?: string | null;
  expires_in_hours?: number | null;
};

export type AnswerShareResponse = {
  share_id: string;
  message_id: string;
  token: string;
  access_mode: AnswerShareAccessMode;
  allowed_user_ids: string[];
  has_password: boolean;
  created_at: string;
  expires_at: string | null;
  is_revoked: boolean;
  shared_by_user_id: string;
};

export type AnswerShareListResponse = {
  items: AnswerShareResponse[];
  total: number;
};

export type SharedAnswerCitationResponse = {
  filename: string | null;
  page_number: number | null;
  text_snippet: string | null;
  source_provider_label: string | null;
  source_title: string | null;
  source_section: string | null;
  source_key: string | null;
  source_trust_status: string | null;
};

export type SharedAnswerResponse = {
  question: string;
  answer: string;
  citations: SharedAnswerCitationResponse[];
  confidence_score: number | null;
  confidence_category: string | null;
  shared_at: string;
  expires_at: string | null;
  access_mode: AnswerShareAccessMode;
};

export async function createAnswerShare(
  messageId: string,
  payload: CreateAnswerSharePayload = {},
): Promise<AnswerShareResponse> {
  return apiRequest<AnswerShareResponse>(
    `/chat/messages/${encodeURIComponent(messageId)}/shares`,
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function listAnswerShares(
  messageId: string,
): Promise<AnswerShareListResponse> {
  return apiRequest<AnswerShareListResponse>(
    `/chat/messages/${encodeURIComponent(messageId)}/shares`,
  );
}

export async function revokeAnswerShare(
  messageId: string,
  shareId: string,
): Promise<void> {
  return apiRequest<void>(
    `/chat/messages/${encodeURIComponent(messageId)}/shares/${encodeURIComponent(shareId)}`,
    { method: "DELETE" },
  );
}

export async function getSharedAnswer(
  token: string,
  password?: string,
): Promise<SharedAnswerResponse> {
  const params = password ? `?password=${encodeURIComponent(password)}` : "";
  return apiRequest<SharedAnswerResponse>(
    `/chat/answer-shared/${encodeURIComponent(token)}${params}`,
  );
}
