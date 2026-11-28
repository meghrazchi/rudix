import type {
  Overlay,
  WithOptional,
  WithRequired,
} from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

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

type Schemas = components["schemas"];

/** Normalized freshness state for UI display (F311). */
export type FreshnessState =
  | "current"
  | "stale"
  | "expired"
  | "deprecated"
  | "draft"
  | "unreviewed"
  | "unknown";

// Snapshots saved before a field was introduced do not carry it, so these fields stay optional.
export type CitationTrustRecord = WithOptional<
  Schemas["CitationTrustRecord"],
  "doc_draft_warning"
>;

/** Single explainable signal that contributed to the confidence score (F310). */
export type ConfidenceReasonRecord = Schemas["ConfidenceReasonRecord"];

export type ConfidenceTrustRecord = Schemas["ConfidenceTrustRecord"];

export type ClaimSupportRecord = WithRequired<
  Schemas["ClaimSupportRecord"],
  "citation_indices"
>;

export type RetrievalDiagnosticsRecord = WithOptional<
  Schemas["RetrievalDiagnosticsRecord"],
  | "retrieval_candidate_count"
  | "top_k"
  | "rerank_fallback_used"
  | "parallel_branch_count"
  | "parallel_branch_failure_count"
  | "parallel_branch_timeout_count"
>;

export type QueryInterpretationRecord = WithRequired<
  Schemas["QueryInterpretationRecord"],
  "sub_queries"
>;

export type GroundedVerificationRecord = Overlay<
  WithOptional<
    Schemas["GroundedVerificationRecord"],
    "conflicting_count" | "not_enough_evidence_count"
  >,
  { claims: ClaimSupportRecord[] }
>;

export type ModelMetadataRecord = Schemas["ModelMetadataRecord"];

export type ConflictStatusRecord = WithRequired<
  Schemas["ConflictStatusRecord"],
  "conflicting_document_ids" | "preferred_document_ids"
>;

export type PolicyEnforcementRecord = Schemas["PolicyEnforcementRecord"];

export type SourceFreshnessRecord = WithOptional<
  Schemas["SourceFreshnessRecord"],
  "draft_count"
>;

/** Aggregated evidence quality signals across all cited sources (F315). */
export type EvidenceQualityRecord = WithRequired<
  Schemas["EvidenceQualityRecord"],
  "warning_reasons"
>;

/** A single quality warning produced by the answer critic (F339). */
export type CriticWarningRecord = Schemas["CriticWarningRecord"];

/**
 * Planner strategy classification, critic warnings, and refiner outcome (F339).
 * Present on all responses; fields are empty/default when the pipeline is disabled
 * or the question was not flagged as high-risk.
 */
export type PlannerCriticRecord = WithRequired<
  Schemas["PlannerCriticRecord"],
  "critic_warnings"
>;

/**
 * Dynamically selected retrieval method for this query (F341).
 * Populated when dynamic retrieval routing is enabled.
 * Only safe public fields — internal routing reason is excluded.
 */
export type RetrievalMethodRecord = Schemas["RetrievalMethodRecord"];

/** Authorization and execution outcome for one tool capability (F342). */
export type ChatToolCallRecord = Schemas["ChatToolCallRecord"];

/**
 * Aggregated result of the permission-aware adaptive tool orchestration step (F342).
 * Populated when feature_enable_chat_tool_orchestration is active.
 * Shows which tools were selected, authorized, executed, and whether fallbacks fired.
 */
export type ToolOrchestrationRecord = WithRequired<
  Schemas["ToolOrchestrationRecord"],
  "tool_calls"
>;

/** Versioned, organization-scoped answer trust metadata. schema_version "1" is current. */
export type AnswerTrustMetadataResponse = Overlay<
  Schemas["AnswerTrustMetadataResponse"],
  {
    citations: CitationTrustRecord[];
    retrieval: RetrievalDiagnosticsRecord;
    query_interpretation?: QueryInterpretationRecord | null;
    grounded_verification: GroundedVerificationRecord;
    conflict: ConflictStatusRecord;
    freshness: SourceFreshnessRecord;
    evidence_quality: EvidenceQualityRecord;
    planner_critic?: PlannerCriticRecord;
    tool_orchestration?: ToolOrchestrationRecord;
  }
>;

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
