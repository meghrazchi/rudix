import type { Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type AnswerShareAccessMode = "org_only" | "specific_users";

export type CreateAnswerSharePayload = WithOptional<
  Schemas["CreateAnswerShareRequest"],
  "access_mode"
>;

export type AnswerShareResponse = Served<Schemas["AnswerShareResponse"]>;

export type AnswerShareListResponse = Served<
  Schemas["AnswerShareListResponse"]
>;

export type SharedAnswerCitationResponse = Served<
  Schemas["SharedAnswerCitationResponse"]
>;

export type SharedAnswerResponse = Served<Schemas["SharedAnswerResponse"]>;

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
