"""Versioned answer trust metadata contract (F307).

This module defines stable, security-filtered DTOs for answer trust metadata.
The schema_version field allows frontend consumers to handle contract evolution
without breaking. Raw prompts, chain-of-thought, ACL snapshots, and internal
UUIDs are excluded.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CitationTrustRecord(BaseModel):
    """Trust-enriched citation record.

    Omits source_acl_snapshot (internal ACL details) and keeps only
    user-facing provenance and freshness fields.

    F311 additions:
      freshness_state      — normalized display state for the trust panel
      doc_last_updated_at  — when the document was last modified
      doc_review_owner_id  — who is responsible for reviewing this document
      doc_unreviewed_warning — True when the source is pending review
      doc_deprecated_warning — True when the source is deprecated/archived/superseded
    """

    document_id: str
    chunk_id: str
    filename: str | None = None
    page_number: int | None = None
    score: float | None = None
    similarity_score: float | None = None
    rerank_score: float | None = None
    original_rank: int | None = None
    final_rank: int | None = None
    text_snippet: str | None = None
    source_provider: str | None = None
    source_provider_label: str | None = None
    source_title: str | None = None
    source_key: str | None = None
    source_section: str | None = None
    source_deep_link: str | None = None
    source_last_synced_at: datetime | None = None
    source_trust_status: (
        Literal["trusted", "stale", "revoked", "deleted", "unknown", "uploaded"] | None
    ) = None
    conflict_status: Literal["preferred", "conflicting", "neutral"] | None = None
    doc_trust_status: str | None = None
    doc_quality_state: str | None = None
    doc_review_status: str | None = None
    doc_version_label: str | None = None
    doc_review_due_date: date | None = None
    doc_expiry_date: date | None = None
    doc_stale_warning: bool = False
    doc_expired_warning: bool = False
    doc_is_excluded_status: bool = False
    doc_draft_warning: bool = False
    is_table_chunk: bool = False
    table_caption: str | None = None
    table_row_count: int | None = None
    table_col_count: int | None = None
    table_headers: list[str] = Field(default_factory=list)
    doc_ocr_quality_status: str | None = None
    doc_ocr_low_confidence_warning: bool = False
    # F311 — normalized freshness state + provenance display fields
    freshness_state: (
        Literal["current", "stale", "expired", "deprecated", "draft", "unreviewed", "unknown"]
        | None
    ) = None
    doc_last_updated_at: datetime | None = None
    doc_review_owner_id: str | None = None
    doc_unreviewed_warning: bool = False
    doc_deprecated_warning: bool = False
    doc_draft_warning: bool = False
    # F315 — evidence quality: table extraction and document processing signals
    table_extraction_confidence: float | None = None
    table_low_confidence_warning: bool = False
    doc_extraction_quality: str | None = None
    doc_extraction_warning: bool = False
    doc_processing_warning: bool = False


class ConfidenceReasonRecord(BaseModel):
    """Single explainable signal that contributed to the confidence score (F310)."""

    code: str
    label: str
    impact: Literal["positive", "negative", "neutral"]
    magnitude: float = Field(ge=0.0, le=1.0)


class ConfidenceTrustRecord(BaseModel):
    """Confidence score breakdown for the answer."""

    score: float = Field(ge=0.0, le=1.0)
    category: Literal["low", "medium", "high"]
    trust_level: Literal["high", "medium", "low", "warning", "not_found"] = "low"
    citation_support_score: float = Field(ge=0.0, le=1.0)
    citation_validation_score: float = Field(ge=0.0, le=1.0)
    citation_coverage_score: float = Field(ge=0.0, le=1.0)
    retrieval_agreement_score: float = Field(ge=0.0, le=1.0)
    top_similarity: float = Field(ge=0.0, le=1.0)
    average_similarity: float = Field(ge=0.0, le=1.0)
    top_rerank_score: float = Field(ge=0.0, le=1.0)
    raw_score: float = Field(ge=0.0, le=1.0)
    citation_validation_multiplier: float = Field(ge=0.0, le=1.0)
    not_found_penalty_multiplier: float = Field(ge=0.0, le=1.0)
    freshness_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    ocr_quality_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    conflict_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    table_quality_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    extraction_quality_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)
    graph_evidence_boost: float = Field(ge=0.0, le=1.0, default=0.0)
    verification_support_score: float | None = None
    not_found_signal: bool
    no_context: bool
    reasons: list[ConfidenceReasonRecord] = Field(default_factory=list)


class RetrievalDiagnosticsRecord(BaseModel):
    """Safe subset of pipeline retrieval diagnostics."""

    retrieval_candidate_count: int = 0
    retrieval_count: int = 0
    selected_count: int = 0
    top_k: int = 0
    search_mode: str | None = None
    source_scope_mode: str | None = None
    source_scope_label: str | None = None
    retrieval_profile_name: str | None = None
    retrieval_profile_scope: str | None = None
    retrieval_profile_source: str | None = None
    retrieval_filters: list[str] = Field(default_factory=list)
    rerank_applied: bool = False
    rerank_provider: str | None = None
    rerank_model: str | None = None
    rerank_score_min: float | None = None
    rerank_score_max: float | None = None
    rerank_fallback_used: bool = False
    rerank_fallback_reason: str | None = None
    request_id: str | None = None
    trace_request_id: str | None = None
    hybrid_retrieval_enabled: bool = False
    hybrid_vector_hit_count: int = 0
    hybrid_keyword_hit_count: int = 0
    query_rewriting_applied: bool = False
    query_decomposed: bool = False
    sub_query_count: int = 0
    parent_context_expanded_count: int = 0
    graph_context_used: bool = False
    graph_context_unavailable: bool = False
    graph_chunk_count: int = 0
    freshness_excluded_count: int = 0
    freshness_boosted_count: int = 0


class QueryInterpretationRecord(BaseModel):
    """Safe query interpretation surfaced in the trust panel."""

    intent: Literal[
        "lookup",
        "summary",
        "comparison",
        "policy",
        "troubleshooting",
        "compliance",
        "connector_search",
        "graph_entity_search",
    ]
    intent_label: str
    complexity: Literal["simple", "complex", "multi_part"]
    retrieval_strategy: Literal["original", "rewrite", "decompose"]
    rewrite_preview_enabled: bool = True
    rewritten_query_preview: str | None = None
    sub_queries: list[str] = Field(default_factory=list)


class GroundedVerificationRecord(BaseModel):
    """Results of the post-generation grounded answer verifier (F296/F338)."""

    applied: bool = False
    verdict: str | None = None
    score: float | None = None
    aggregate_support_score: float = Field(ge=0.0, le=1.0, default=0.0)
    claim_count: int = 0
    supported_count: int = 0
    partially_supported_count: int = 0
    unsupported_count: int = 0
    unverifiable_count: int = 0
    conflicting_count: int = 0
    not_enough_evidence_count: int = 0
    removed_count: int = 0
    reason_codes: list[str] = Field(default_factory=list)
    claims: list[ClaimSupportRecord] = Field(default_factory=list)
    mode: str | None = None
    threshold: float | None = None


class ClaimSupportRecord(BaseModel):
    """Claim-level support details with citation mapping."""

    claim_index: int = Field(ge=1)
    claim_text: str
    support_status: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "unverifiable",
        "conflicting",
        "not_enough_evidence",
    ]
    support_score: float = Field(ge=0.0, le=1.0)
    evidence_match_score: float = Field(ge=0.0, le=1.0)
    source_quality_score: float = Field(ge=0.0, le=1.0)
    rerank_score: float = Field(ge=0.0, le=1.0)
    chunk_coverage_score: float = Field(ge=0.0, le=1.0)
    citation_indices: list[int] = Field(default_factory=list)


class ModelMetadataRecord(BaseModel):
    """LLM and prompt template metadata.

    Excludes the internal prompt_template_version_id UUID.
    """

    llm_model: str | None = None
    llm_provider: str | None = None
    embedding_model: str | None = None
    fallback_used: bool = False
    fallback_from: str | None = None
    fallback_to: str | None = None
    fallback_reason: str | None = None
    prompt_template_key: str | None = None
    prompt_template_version: int | None = None


class ConflictStatusRecord(BaseModel):
    """Source conflict detection results."""

    detected: bool = False
    agreement_level: Literal["full", "partial", "conflicting"] = "full"
    conflict_count: int = 0
    conflicting_document_ids: list[str] = Field(default_factory=list)
    preferred_document_ids: list[str] = Field(default_factory=list)
    conflict_summary: str | None = None


class PolicyEnforcementRecord(BaseModel):
    """AI response policy outcomes (F268)."""

    applied: bool = False
    outcome: str | None = None
    violated_rules: list[str] = Field(default_factory=list)
    warning_flags: list[str] = Field(default_factory=list)
    has_disclaimer: bool = False


class SourceFreshnessRecord(BaseModel):
    """Source freshness warning summary (F297/F311)."""

    warning: bool = False
    warning_reason: str | None = None
    warning_reasons: list[str] = Field(default_factory=list)
    stale_count: int = 0
    excluded_count: int = 0
    boosted_count: int = 0
    unreviewed_count: int = 0
    deprecated_count: int = 0
    draft_count: int = 0
    all_excluded_fallback: bool = False


class EvidenceQualityRecord(BaseModel):
    """Aggregated evidence quality signals across all cited sources (F315).

    Captures table extraction confidence, document extraction health, and
    processing completeness issues that may reduce answer reliability.
    """

    table_low_confidence_count: int = 0
    extraction_warning_count: int = 0
    processing_warning_count: int = 0
    any_incomplete_documents: bool = False
    warning_reasons: list[str] = Field(default_factory=list)


class AnswerTrustMetadataResponse(BaseModel):
    """Versioned, organization-scoped answer trust metadata contract.

    schema_version is bumped when a breaking field change is introduced,
    allowing frontend consumers to branch on contract evolution without
    deployment coupling.
    """

    schema_version: Literal["1"] = "1"
    organization_id: str
    message_id: str
    not_found: bool
    citation_validation_failed: bool
    verification_failed: bool
    confidence: ConfidenceTrustRecord
    citations: list[CitationTrustRecord]
    retrieval: RetrievalDiagnosticsRecord
    query_interpretation: QueryInterpretationRecord | None = None
    grounded_verification: GroundedVerificationRecord
    model: ModelMetadataRecord
    conflict: ConflictStatusRecord
    policy: PolicyEnforcementRecord
    freshness: SourceFreshnessRecord
    evidence_quality: EvidenceQualityRecord
    generated_at: datetime


GroundedVerificationRecord.model_rebuild()
ConfidenceTrustRecord.model_rebuild()
QueryInterpretationRecord.model_rebuild()
EvidenceQualityRecord.model_rebuild()
AnswerTrustMetadataResponse.model_rebuild()
