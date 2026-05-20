import { apiRequest } from "@/lib/api/request";

export type CreateChatSessionRequest = {
  title?: string | null;
};

export type ChatSessionResponse = {
  session_id: string;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ChatSessionListResponse = {
  items: ChatSessionResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type ChatCitationResponse = {
  document_id: string;
  chunk_id: string;
  filename: string | null;
  page_number: number | null;
  score: number | null;
  similarity_score: number | null;
  rerank_score: number | null;
  rerank_rank: number | null;
  text_snippet: string | null;
};

export type ChatDebugResponse = {
  latencies_ms: Record<string, number>;
  retrieval_count: number;
  selected_count: number;
  rerank_applied: boolean;
  embedding_model: string | null;
  llm_model: string | null;
};

export type ChatConfidenceExplanationResponse = {
  top_similarity: number;
  average_similarity: number;
  top_rerank_score: number;
  citation_support_score: number;
  citation_validation_score: number;
  citation_coverage_score: number;
  retrieval_agreement_score: number;
  raw_score: number;
  citation_validation_multiplier: number;
  not_found_penalty_multiplier: number;
  no_context: boolean;
  not_found_signal: boolean;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
};

export type ChatQueryResponse = {
  chat_session_id: string;
  message_id: string;
  answer: string;
  confidence_score: number;
  confidence_category: "low" | "medium" | "high";
  confidence_explanation: ChatConfidenceExplanationResponse;
  not_found: boolean;
  citations: ChatCitationResponse[];
  debug: ChatDebugResponse;
  created_at: string;
};

export type ChatMessageResponse = {
  session_id: string;
  message_id: string;
  role: "assistant";
  answer: string;
  citations: Array<{
    document_id: string;
    chunk_id: string;
    page_number: number | null;
    score: number | null;
  }>;
  created_at: string;
};

export type ChatSessionMessageResponse = {
  message_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  confidence_score: number | null;
  confidence_category: "low" | "medium" | "high" | null;
  citations: ChatCitationResponse[];
  created_at: string;
};

export type ChatSessionMessageListResponse = {
  items: ChatSessionMessageResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type ChatQueryRequest = {
  question: string;
  chat_session_id?: string | null;
  document_ids?: string[];
  top_k?: number;
  rerank?: boolean;
};

export type ChatMessageRequest = {
  message: string;
  document_ids?: string[];
  stream?: boolean;
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
  params: { limit?: number; offset?: number } = {},
): Promise<ChatSessionListResponse> {
  return apiRequest<ChatSessionListResponse>("/chat/sessions", {
    query: {
      limit: params.limit,
      offset: params.offset,
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
