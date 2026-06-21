import { apiRequest } from "@/lib/api/request";

export type VerifiedAnswerStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "published"
  | "archived";

export type CitationIn = {
  document_id: string;
  chunk_id?: string | null;
  text_snippet?: string | null;
  page_number?: number | null;
  citation_order?: number;
};

export type CitationResponse = {
  citation_id: string;
  document_id: string;
  chunk_id: string | null;
  text_snippet: string | null;
  page_number: number | null;
  citation_order: number;
};

export type VersionResponse = {
  version_id: string;
  version_number: number;
  title: string;
  question: string;
  answer_text: string;
  tags: string | null;
  change_reason: string;
  changed_by_id: string | null;
  created_at: string;
};

export type VerifiedAnswerResponse = {
  answer_id: string;
  organization_id: string;
  title: string;
  question: string;
  answer_text: string;
  status: VerifiedAnswerStatus;
  tags: string | null;
  collection_id: string | null;
  owner_id: string | null;
  requires_citations: boolean;
  review_date: string | null;
  expiry_date: string | null;
  approved_by_id: string | null;
  approved_at: string | null;
  published_at: string | null;
  rejection_note: string | null;
  source_message_id: string | null;
  created_by_id: string | null;
  is_stale: boolean;
  citations: CitationResponse[];
  created_at: string;
  updated_at: string;
};

export type VerifiedAnswerListResponse = {
  items: VerifiedAnswerResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type VerifiedAnswerVersionListResponse = {
  items: VersionResponse[];
  total: number;
};

export type CreateVerifiedAnswerRequest = {
  title: string;
  question: string;
  answer_text: string;
  tags?: string | null;
  collection_id?: string | null;
  requires_citations?: boolean;
  review_date?: string | null;
  expiry_date?: string | null;
  citations?: CitationIn[];
};

export type CreateFromChatRequest = {
  title: string;
  question?: string | null;
  tags?: string | null;
  collection_id?: string | null;
  review_date?: string | null;
  expiry_date?: string | null;
};

export type UpdateVerifiedAnswerRequest = {
  title?: string;
  question?: string;
  answer_text?: string;
  tags?: string | null;
  collection_id?: string | null;
  requires_citations?: boolean;
  review_date?: string | null;
  expiry_date?: string | null;
  citations?: CitationIn[];
  change_reason?: string;
};

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
  return apiRequest<VerifiedAnswerListResponse>("/verified-answers/search/match", {
    query: {
      query,
      collection_id: options.collection_id,
      limit: options.limit,
    },
  });
}
