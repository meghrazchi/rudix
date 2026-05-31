import { apiRequest } from "@/lib/api/request";
import type { ChatSessionMessageResponse } from "@/lib/api/chat";

export type CreateChatSharePayload = {
  expires_in_hours?: number | null;
};

export type ChatShareResponse = {
  share_id: string;
  session_id: string;
  token: string;
  created_at: string;
  expires_at: string | null;
  is_revoked: boolean;
  shared_by_user_id: string;
};

export type ChatShareListResponse = {
  items: ChatShareResponse[];
  total: number;
};

export type SharedSessionResponse = {
  session_id: string;
  title: string | null;
  shared_at: string;
  messages: ChatSessionMessageResponse[];
  total_messages: number;
};

export async function createChatShare(
  sessionId: string,
  payload: CreateChatSharePayload = {},
): Promise<ChatShareResponse> {
  return apiRequest<ChatShareResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/shares`,
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function listChatShares(
  sessionId: string,
): Promise<ChatShareListResponse> {
  return apiRequest<ChatShareListResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/shares`,
  );
}

export async function revokeChatShare(
  sessionId: string,
  shareId: string,
): Promise<void> {
  return apiRequest<void>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/shares/${encodeURIComponent(shareId)}`,
    { method: "DELETE" },
  );
}

export async function getSharedSession(
  token: string,
): Promise<SharedSessionResponse> {
  return apiRequest<SharedSessionResponse>(
    `/chat/shared/${encodeURIComponent(token)}`,
  );
}
