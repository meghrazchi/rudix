/**
 * Versioned answer trust metadata contract (F307).
 *
 * Types mirror the backend AnswerTrustMetadataResponse schema exactly.
 * The schema_version field allows detecting contract changes without breaking
 * existing consumers — branch on "1" vs later versions as needed.
 *
 * No raw prompts, chain-of-thought, ACL snapshots, or internal UUIDs are
 * returned by the API; these types therefore do not include those fields.
 */

import { apiRequest } from "@/lib/api/request";

/** Normalized freshness state for UI display (F311). */
export type FreshnessState =
  | "current"
  | "stale"
  | "expired"
  | "deprecated"
  | "draft"
  | "unreviewed"
  | "unknown";

export type CitationTrustRecord = {
  document_id: string;
  chunk_id: string;
  filename?: string | null;
  page_number?: number | null;
  score?: number | null;
  similarity_score?: number | null;
  rerank_score?: number | null;
  original_rank?: number | null;
  final_rank?: number | null;
  text_snippet?: string | null;
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
  conflict_status?: "preferred" | "conflicting" | "neutral" | null;
  doc_trust_status?: string | null;
  doc_review_status?: string | null;
  doc_version_label?: string | null;
  doc_review_due_date?: string | null;
  doc_expiry_date?: string | null;
  doc_stale_warning: boolean;
  doc_expired_warning: boolean;
  doc_is_excluded_status: boolean;
  is_table_chunk: boolean;
  table_caption?: string | null;
  table_row_count?: number | null;
  table_col_count?: number | null;
  table_headers: string[];
  doc_ocr_quality_status?:
    | "high"
    | "medium"
    | "low"
    | "failed"
    | "not_required"
    | null;
  doc_ocr_low_confidence_warning: boolean;
  /** F311 — normalized freshness state for the trust panel badge. */
  freshness_state?: FreshnessState | null;
  /** F311 — ISO timestamp of when the source document was last modified. */
  doc_last_updated_at?: string | null;
  /** F311 — user ID of the review owner for this document. */
  doc_review_owner_id?: string | null;
  /** F311 — true when the source is pending review (needs_review status). */
  doc_unreviewed_warning: boolean;
  /** F311 — true when the source is deprecated, archived, or superseded. */
  doc_deprecated_warning: boolean;
};

/** Single explainable signal that contributed to the confidence score (F310). */
export type ConfidenceReasonRecord = {
  code: string;
  label: string;
  impact: "positive" | "negative" | "neutral";
  magnitude: number;
};

export type ConfidenceTrustRecord = {
  score: number;
  category: "low" | "medium" | "high";
  /** Calibrated trust level including quality-signal degradation (F310). */
  trust_level: "high" | "medium" | "low" | "warning" | "not_found";
  citation_support_score: number;
  citation_validation_score: number;
  citation_coverage_score: number;
  retrieval_agreement_score: number;
  top_similarity: number;
  average_similarity: number;
  top_rerank_score: number;
  raw_score: number;
  citation_validation_multiplier: number;
  not_found_penalty_multiplier: number;
  freshness_multiplier: number;
  ocr_quality_multiplier: number;
  conflict_multiplier: number;
  graph_evidence_boost: number;
  verification_support_score?: number | null;
  not_found_signal: boolean;
  no_context: boolean;
  reasons: ConfidenceReasonRecord[];
};

export type ClaimSupportRecord = {
  claim_index: number;
  claim_text: string;
  support_status:
    | "supported"
    | "partially_supported"
    | "unsupported"
    | "unverifiable";
  support_score: number;
  evidence_match_score: number;
  source_quality_score: number;
  rerank_score: number;
  chunk_coverage_score: number;
  citation_indices: number[];
};

export type RetrievalDiagnosticsRecord = {
  retrieval_candidate_count?: number;
  retrieval_count: number;
  selected_count: number;
  top_k?: number;
  search_mode?: string | null;
  source_scope_mode?: string | null;
  source_scope_label?: string | null;
  retrieval_profile_name?: string | null;
  retrieval_profile_scope?: string | null;
  retrieval_profile_source?: string | null;
  retrieval_filters?: string[];
  rerank_applied: boolean;
  rerank_provider?: string | null;
  rerank_model?: string | null;
  rerank_score_min?: number | null;
  rerank_score_max?: number | null;
  rerank_fallback_used?: boolean;
  rerank_fallback_reason?: string | null;
  request_id?: string | null;
  trace_request_id?: string | null;
  hybrid_retrieval_enabled: boolean;
  hybrid_vector_hit_count: number;
  hybrid_keyword_hit_count: number;
  query_rewriting_applied: boolean;
  query_decomposed: boolean;
  sub_query_count: number;
  parent_context_expanded_count: number;
  graph_context_used: boolean;
  graph_context_unavailable: boolean;
  graph_chunk_count: number;
  freshness_excluded_count: number;
  freshness_boosted_count: number;
};

export type QueryInterpretationRecord = {
  intent:
    | "lookup"
    | "summary"
    | "comparison"
    | "policy"
    | "troubleshooting"
    | "compliance"
    | "connector_search"
    | "graph_entity_search";
  intent_label: string;
  complexity: "simple" | "complex" | "multi_part";
  retrieval_strategy: "original" | "rewrite" | "decompose";
  rewrite_preview_enabled: boolean;
  rewritten_query_preview?: string | null;
  sub_queries: string[];
};

export type GroundedVerificationRecord = {
  applied: boolean;
  verdict?: string | null;
  score?: number | null;
  aggregate_support_score: number;
  claim_count: number;
  supported_count: number;
  partially_supported_count: number;
  unsupported_count: number;
  unverifiable_count: number;
  removed_count: number;
  reason_codes: string[];
  claims: ClaimSupportRecord[];
};

export type ModelMetadataRecord = {
  llm_model?: string | null;
  llm_provider?: string | null;
  embedding_model?: string | null;
  fallback_used: boolean;
  fallback_from?: string | null;
  fallback_to?: string | null;
  fallback_reason?: string | null;
  prompt_template_key?: string | null;
  prompt_template_version?: number | null;
};

export type ConflictStatusRecord = {
  detected: boolean;
  agreement_level: "full" | "partial" | "conflicting";
  conflict_count: number;
  conflicting_document_ids: string[];
  preferred_document_ids: string[];
  conflict_summary?: string | null;
};

export type PolicyEnforcementRecord = {
  applied: boolean;
  outcome?: string | null;
  violated_rules: string[];
  warning_flags: string[];
  has_disclaimer: boolean;
};

export type SourceFreshnessRecord = {
  warning: boolean;
  warning_reason?: string | null;
  /** F311 — structured list of specific freshness warning messages. */
  warning_reasons: string[];
  stale_count: number;
  excluded_count: number;
  boosted_count: number;
  /** F311 — number of cited sources pending review. */
  unreviewed_count: number;
  /** F311 — number of cited sources that are deprecated, archived, or superseded. */
  deprecated_count: number;
  /** F311 — true when all sources were excluded and the fallback re-included them. */
  all_excluded_fallback: boolean;
};

/** Versioned, organization-scoped answer trust metadata. schema_version "1" is current. */
export type AnswerTrustMetadataResponse = {
  schema_version: "1";
  organization_id: string;
  message_id: string;
  not_found: boolean;
  citation_validation_failed: boolean;
  verification_failed: boolean;
  confidence: ConfidenceTrustRecord;
  citations: CitationTrustRecord[];
  retrieval: RetrievalDiagnosticsRecord;
  query_interpretation?: QueryInterpretationRecord | null;
  grounded_verification: GroundedVerificationRecord;
  model: ModelMetadataRecord;
  conflict: ConflictStatusRecord;
  policy: PolicyEnforcementRecord;
  freshness: SourceFreshnessRecord;
  generated_at: string;
};

/**
 * Fetch the versioned trust metadata snapshot for a saved assistant message.
 * Returns null (404) when the message predates F307 or does not exist.
 */
export async function getAnswerTrustMetadata(
  messageId: string,
): Promise<AnswerTrustMetadataResponse> {
  return apiRequest<AnswerTrustMetadataResponse>(
    `/chat/messages/${encodeURIComponent(messageId)}/trust-metadata`,
  );
}
