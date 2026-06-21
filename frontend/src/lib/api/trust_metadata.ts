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
};

export type ConfidenceTrustRecord = {
  score: number;
  category: "low" | "medium" | "high";
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
  not_found_signal: boolean;
  no_context: boolean;
};

export type RetrievalDiagnosticsRecord = {
  retrieval_count: number;
  selected_count: number;
  rerank_applied: boolean;
  rerank_provider?: string | null;
  rerank_model?: string | null;
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

export type GroundedVerificationRecord = {
  applied: boolean;
  verdict?: string | null;
  score?: number | null;
  claim_count: number;
  supported_count: number;
  unsupported_count: number;
  removed_count: number;
  reason_codes: string[];
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
  stale_count: number;
  excluded_count: number;
  boosted_count: number;
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
