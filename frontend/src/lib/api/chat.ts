import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

export type CreateChatSessionRequest = Schemas["CreateChatSessionRequest"];
export type ChatSessionResponse = Schemas["ChatSessionResponse"];
export type ChatSessionListResponse = Schemas["ChatSessionListResponse"];
export type ChatCitationResponse = Schemas["ChatCitationResponse"] & {
  source_provider?: string | null;
  source_provider_label?: string | null;
  source_title?: string | null;
  source_key?: string | null;
  source_section?: string | null;
  source_deep_link?: string | null;
  source_last_synced_at?: string | null;
  source_trust_status?:
    | "trusted"
    | "stale"
    | "revoked"
    | "deleted"
    | "unknown"
    | "uploaded"
    | null;
  source_acl_snapshot?: Record<string, unknown>;
};
export type ChatDebugResponse = Schemas["ChatDebugResponse"];
export type ChatConfidenceExplanationResponse =
  Schemas["ChatConfidenceExplanationResponse"];
export type ChatQueryResponse = Schemas["ChatQueryResponse"];
export type ChatMessageResponse = Schemas["ChatMessageResponse"];
export type ChatSessionMessageResponse = Schemas["ChatSessionMessageResponse"];
export type ChatSessionMessageListResponse =
  Schemas["ChatSessionMessageListResponse"];
export type ChatQueryRequest = Schemas["ChatQueryRequest"];
export type ChatMessageRequest = Schemas["ChatMessageRequest"];

export type UpdateChatSessionRequest = {
  title: string | null;
};

export async function createChatSession(
  payload: CreateChatSessionRequest = {},
): Promise<ChatSessionResponse> {
  return apiRequest<ChatSessionResponse>("/chat/sessions", {
    method: "POST",
    json: payload,
  });
}

export async function listChatSessions(
  params: { limit?: number; offset?: number; search?: string } = {},
): Promise<ChatSessionListResponse> {
  return apiRequest<ChatSessionListResponse>("/chat/sessions", {
    query: {
      limit: params.limit,
      offset: params.offset,
      search: params.search || undefined,
    },
  });
}

export async function getChatSession(
  sessionId: string,
): Promise<ChatSessionResponse> {
  return apiRequest<ChatSessionResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export async function updateChatSession(
  sessionId: string,
  payload: UpdateChatSessionRequest,
): Promise<ChatSessionResponse> {
  return apiRequest<ChatSessionResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  return apiRequest<void>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function listChatSessionMessages(
  sessionId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ChatSessionMessageListResponse> {
  return apiRequest<ChatSessionMessageListResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      query: {
        limit: params.limit,
        offset: params.offset,
      },
    },
  );
}

export async function queryChat(
  payload: ChatQueryRequest,
): Promise<ChatQueryResponse> {
  return apiRequest<ChatQueryResponse>("/chat", {
    method: "POST",
    json: payload,
  });
}

export async function createChatMessage(
  sessionId: string,
  payload: ChatMessageRequest,
): Promise<ChatMessageResponse> {
  return apiRequest<ChatMessageResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      json: payload,
    },
  );
}
