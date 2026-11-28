import type { Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type VerifiedAnswerStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "published"
  | "archived"
  | "deprecated";

export type CitationIn = Served<Schemas["CitationIn"]>;

export type CitationResponse = Served<Schemas["CitationResponse"]>;

export type VersionResponse = Served<Schemas["VersionResponse"]>;

export type VerifiedAnswerResponse = Served<Schemas["VerifiedAnswerResponse"]>;

export type VerifiedAnswerListResponse = Served<
  Schemas["VerifiedAnswerListResponse"]
>;

export type VerifiedAnswerVersionListResponse = Served<
  Schemas["VerifiedAnswerVersionListResponse"]
>;

export type CreateVerifiedAnswerRequest = WithOptional<
  Schemas["CreateVerifiedAnswerRequest"],
  "requires_citations"
>;

export type CreateFromChatRequest = Schemas["CreateFromChatRequest"];

export type UpdateVerifiedAnswerRequest =
  Schemas["UpdateVerifiedAnswerRequest"];

export type ListVerifiedAnswersOptions = {
  status?: VerifiedAnswerStatus;
  collection_id?: string;
  owner_id?: string;
  query?: string;
  limit?: number;
  offset?: number;
};

// ── CRUD ──────────────────────────────────────────────────────────────────────

export async function listVerifiedAnswers(
  options: ListVerifiedAnswersOptions = {},
): Promise<VerifiedAnswerListResponse> {
  return apiRequest<VerifiedAnswerListResponse>("/verified-answers", {
    query: {
      status: options.status,
      collection_id: options.collection_id,
      owner_id: options.owner_id,
      query: options.query,
      limit: options.limit,
      offset: options.offset,
    },
  });
}

export async function getVerifiedAnswer(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}`,
  );
}

export async function createVerifiedAnswer(
  payload: CreateVerifiedAnswerRequest,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>("/verified-answers", {
    method: "POST",
    json: payload,
  });
}

export async function updateVerifiedAnswer(
  answerId: string,
  payload: UpdateVerifiedAnswerRequest,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}`,
    { method: "PATCH", json: payload },
  );
}

export async function archiveVerifiedAnswer(answerId: string): Promise<void> {
  await apiRequest<unknown>(
    `/verified-answers/${encodeURIComponent(answerId)}`,
    { method: "DELETE" },
  );
}

// ── Workflow ──────────────────────────────────────────────────────────────────

export async function submitForReview(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/submit-for-review`,
    { method: "POST" },
  );
}

export async function approveVerifiedAnswer(
  answerId: string,
  note?: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/approve`,
    { method: "POST", json: { note: note ?? null } },
  );
}

export async function rejectVerifiedAnswer(
  answerId: string,
  note: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/reject`,
    { method: "POST", json: { note } },
  );
}

export async function publishVerifiedAnswer(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/publish`,
    { method: "POST" },
  );
}

// ── Version history ───────────────────────────────────────────────────────────

export async function listVerifiedAnswerVersions(
  answerId: string,
): Promise<VerifiedAnswerVersionListResponse> {
  return apiRequest<VerifiedAnswerVersionListResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/versions`,
  );
}

// ── Create from chat ──────────────────────────────────────────────────────────

export async function createVerifiedAnswerFromMessage(
  messageId: string,
  payload: CreateFromChatRequest,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/from-message/${encodeURIComponent(messageId)}`,
    { method: "POST", json: payload },
  );
}

// ── Retrieval ─────────────────────────────────────────────────────────────────

export async function searchVerifiedAnswers(
  query: string,
  options: { collection_id?: string; limit?: number } = {},
): Promise<VerifiedAnswerListResponse> {
  return apiRequest<VerifiedAnswerListResponse>(
    "/verified-answers/search/match",
    {
      query: {
        query,
        collection_id: options.collection_id,
        limit: options.limit,
      },
    },
  );
}

// ── F328 — deprecate / restore / duplicate ────────────────────────────────────

export async function deprecateVerifiedAnswer(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/deprecate`,
    { method: "POST" },
  );
}

export async function restoreVerifiedAnswer(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/restore`,
    { method: "POST" },
  );
}

export async function duplicateVerifiedAnswer(
  answerId: string,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/${encodeURIComponent(answerId)}/duplicate`,
    { method: "POST" },
  );
}

// ── F328 — Create from feedback review item ───────────────────────────────────

export async function createVerifiedAnswerFromFeedback(
  itemId: string,
  payload: CreateFromChatRequest,
): Promise<VerifiedAnswerResponse> {
  return apiRequest<VerifiedAnswerResponse>(
    `/verified-answers/from-feedback/${encodeURIComponent(itemId)}`,
    { method: "POST", json: payload },
  );
}
