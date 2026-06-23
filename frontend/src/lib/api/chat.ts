import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";
import type { AnswerTrustMetadataResponse } from "@/lib/api/trust_metadata";

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
  conflict_status?: "preferred" | "conflicting" | "neutral" | null;
  doc_review_status?:
    | "current"
    | "trusted"
    | "needs_review"
    | "stale"
    | "expired"
    | "archived"
    | null;
  doc_review_owner_id?: string | null;
  doc_review_due_date?: string | null;
  doc_expiry_date?: string | null;
  doc_expired_warning?: boolean;
  doc_stale_warning?: boolean;
  doc_is_excluded_status?: boolean;
  // OCR quality (F299)
  doc_ocr_quality_status?:
    | "high"
    | "medium"
    | "low"
    | "failed"
    | "not_required"
    | null;
  doc_ocr_low_confidence_warning?: boolean;
};
export type ChatDebugResponse = Schemas["ChatDebugResponse"] & {
  request_id?: string | null;
  trace_request_id?: string | null;
  retrieval_candidate_count?: number;
  source_scope?: string | null;
  top_k?: number;
  search_mode?: string | null;
  source_scope_mode?: string | null;
  source_scope_label?: string | null;
  retrieval_profile_name?: string | null;
  retrieval_profile_scope?: string | null;
  retrieval_profile_source?: string | null;
  retrieval_filters?: string[];
  llm_provider?: string | null;
  fallback_used?: boolean;
  fallback_from?: string | null;
  fallback_to?: string | null;
  fallback_reason?: string | null;
  // Reranking details
  rerank_enabled?: boolean;
  rerank_provider?: string | null;
  rerank_model?: string | null;
  rerank_fallback_used?: boolean;
  rerank_fallback_reason?: string | null;
  rerank_input_count?: number;
  rerank_score_min?: number | null;
  rerank_score_max?: number | null;
  // Hybrid retrieval (F293)
  hybrid_retrieval_enabled?: boolean;
  hybrid_vector_hit_count?: number;
  hybrid_keyword_hit_count?: number;
  // Query rewriting (F295)
  query_rewriting_enabled?: boolean;
  query_rewriting_applied?: boolean;
  query_decomposed?: boolean;
  original_query?: string | null;
  rewritten_query?: string | null;
  sub_queries?: string[];
  // Grounded verification (F296)
  grounded_verification_enabled?: boolean;
  grounded_verification_applied?: boolean;
  grounded_verification_verdict?: string | null;
  grounded_verification_score?: number | null;
  grounded_verification_claim_count?: number;
  grounded_verification_supported_count?: number;
  grounded_verification_unsupported_count?: number;
  grounded_verification_removed_count?: number;
  grounded_verification_reason_codes?: string[];
  grounded_verification_model?: string | null;
  // Source freshness (F297)
  freshness_filter_enabled?: boolean;
  freshness_excluded_count?: number;
  freshness_boosted_count?: number;
  freshness_stale_count?: number;
  // OCR quality (F299)
  ocr_quality_downranking_enabled?: boolean;
  ocr_low_confidence_chunk_count?: number;
  // Parent context expansion (F300)
  parent_context_expansion_enabled?: boolean;
  parent_context_child_hit_count?: number;
  parent_context_expanded_count?: number;
  parent_context_tokens_used?: number;
  // Prompt template
  prompt_template_key?: string | null;
  prompt_template_version?: number | null;
  // Graph context (F283)
  graph_context_enabled?: boolean;
  graph_context_used?: boolean;
  graph_context_unavailable?: boolean;
  graph_context_reason?: string | null;
  graph_seed_entity_count?: number;
  graph_related_entity_count?: number;
  graph_chunk_count?: number;
  graph_max_hops_used?: number;
  graph_relation_types_used?: string[];
  conflict_detection_enabled?: boolean;
  conflict_detection_applied?: boolean;
  conflict_detection_latency_ms?: number;
  conflict_detection_agreement_level?: "full" | "partial" | "conflicting";
  conflict_detection_conflict_count?: number;
  conflict_detection_conflicting_document_ids?: string[];
  conflict_detection_preferred_document_ids?: string[];
  conflict_detection_model?: string | null;
  conflict_detection_provider?: string | null;
};
export type ChatConflictPairResponse = Schemas["ChatConflictPairResponse"];
export type ChatConfidenceExplanationResponse =
  Schemas["ChatConfidenceExplanationResponse"];
export type ChatQueryResponse = Omit<Schemas["ChatQueryResponse"], "debug"> & {
  debug: Schemas["ChatQueryResponse"]["debug"] | null;
  agreement_level?: "full" | "partial" | "conflicting";
  conflict_detected?: boolean;
  conflict_summary?: string | null;
  conflicting_document_ids?: string[];
  preferred_document_ids?: string[];
  conflict_pairs?: ChatConflictPairResponse[];
  source_freshness_warning?: boolean;
  source_freshness_warning_reason?: string | null;
  verification_failed?: boolean;
  policy_applied?: boolean;
  policy_outcome?: string | null;
  policy_violated_rules?: string[];
  policy_warning_flags?: string[];
  policy_disclaimer?: string | null;
  /** Versioned trust metadata snapshot — present for answers generated after F307. */
  trust_metadata?: AnswerTrustMetadataResponse | null;
};
export type ChatMessageResponse = Schemas["ChatMessageResponse"] & {
  trust_metadata?: AnswerTrustMetadataResponse | null;
};
export type ChatSessionMessageResponse =
  Schemas["ChatSessionMessageResponse"] & {
    trust_metadata?: AnswerTrustMetadataResponse | null;
  };
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
