import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";
import type { ChatSessionMessageResponse } from "@/lib/api/chat";

type Schemas = components["schemas"];

export type CreateChatSharePayload = Schemas["CreateChatShareRequest"];

export type ChatShareResponse = Served<Schemas["ChatShareResponse"]>;

export type ChatShareListResponse = Served<Schemas["ChatShareListResponse"]>;

export type SharedSessionResponse = Overlay<
  Served<Schemas["SharedSessionResponse"]>,
  { messages: ChatSessionMessageResponse[] }
>;

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
