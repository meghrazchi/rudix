import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

export type ChatSourceScopeRequest = {
  mode?:
    | "all"
    | "uploaded"
    | "collections"
    | "connector_sources"
    | "connector_items";
  provider_keys?: string[];
  connection_ids?: string[];
  provider_source_ids?: string[];
  external_source_ids?: string[];
  external_item_ids?: string[];
  collection_ids?: string[];
  document_types?: string[];
  sync_statuses?: Array<
    "uploaded" | "active" | "stale" | "revoked" | "deleted" | "unknown"
  >;
};

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
  // Table-aware retrieval (F298): populated for table chunks.
  is_table_chunk?: boolean;
  table_caption?: string | null;
  table_row_count?: number | null;
  table_col_count?: number | null;
  table_headers?: string[];
  table_section_context?: string | null;
  // OCR quality (F299)
  doc_ocr_quality_status?: "high" | "medium" | "low" | "failed" | "not_required" | null;
  doc_ocr_low_confidence_warning?: boolean;
};
export type ChatDebugResponse = Schemas["ChatDebugResponse"] & {
  source_scope?: string | null;
  llm_provider?: string | null;
  fallback_used?: boolean;
  fallback_from?: string | null;
  fallback_to?: string | null;
  fallback_reason?: string | null;
  graph_context_enabled?: boolean;
  graph_context_used?: boolean;
  graph_context_unavailable?: boolean;
  graph_context_reason?: string | null;
  graph_seed_entity_count?: number;
  graph_related_entity_count?: number;
  graph_chunk_count?: number;
  graph_max_hops_used?: number;
  graph_relation_types_used?: string[];
};
export type ChatConfidenceExplanationResponse =
  Schemas["ChatConfidenceExplanationResponse"];
export type ChatQueryResponse = Omit<Schemas["ChatQueryResponse"], "debug"> & {
  debug: Schemas["ChatQueryResponse"]["debug"] | null;
};
export type ChatMessageResponse = Schemas["ChatMessageResponse"];
export type ChatSessionMessageResponse = Schemas["ChatSessionMessageResponse"];
export type ChatSessionMessageListResponse =
  Schemas["ChatSessionMessageListResponse"];
export type ChatQueryRequest = Omit<
  Schemas["ChatQueryRequest"],
  "scope_mode"
> & {
  scope_mode?:
    | Exclude<Schemas["ChatQueryRequest"]["scope_mode"], null>
    | "connectors"
    | null;
  source_scope?: ChatSourceScopeRequest | null;
};
export type ChatMessageRequest = Schemas["ChatMessageRequest"];

export type UpdateChatSessionRequest = {
  title: string | null;
};

export type ChatStatsResponse = {
  questions_asked: number;
  total_sessions: number;
};

export async function getChatStats(): Promise<ChatStatsResponse> {
  return apiRequest<ChatStatsResponse>("/chat/stats");
}

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
