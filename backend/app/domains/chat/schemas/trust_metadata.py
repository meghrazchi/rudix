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
    doc_review_status: str | None = None
    doc_version_label: str | None = None
    doc_review_due_date: date | None = None
    doc_expiry_date: date | None = None
    doc_stale_warning: bool = False
    doc_expired_warning: bool = False
    doc_is_excluded_status: bool = False
    is_table_chunk: bool = False
    table_caption: str | None = None
    table_row_count: int | None = None
    table_col_count: int | None = None
    table_headers: list[str] = Field(default_factory=list)
    doc_ocr_quality_status: str | None = None
    doc_ocr_low_confidence_warning: bool = False


class ConfidenceTrustRecord(BaseModel):
    """Confidence score breakdown for the answer."""

    score: float = Field(ge=0.0, le=1.0)
    category: Literal["low", "medium", "high"]
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
    not_found_signal: bool
    no_context: bool


class RetrievalDiagnosticsRecord(BaseModel):
    """Safe subset of pipeline retrieval diagnostics."""

    retrieval_count: int = 0
    selected_count: int = 0
    rerank_applied: bool = False
    rerank_provider: str | None = None
    rerank_model: str | None = None
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


class GroundedVerificationRecord(BaseModel):
    """Results of the post-generation grounded answer verifier (F296)."""

    applied: bool = False
    verdict: str | None = None
    score: float | None = None
    claim_count: int = 0
    supported_count: int = 0
    partially_supported_count: int = 0
    unsupported_count: int = 0
    unverifiable_count: int = 0
    removed_count: int = 0
    reason_codes: list[str] = Field(default_factory=list)
    mode: str | None = None
    threshold: float | None = None


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
    """Source freshness warning summary (F297)."""

    warning: bool = False
    warning_reason: str | None = None
    stale_count: int = 0
    excluded_count: int = 0
    boosted_count: int = 0


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
    grounded_verification: GroundedVerificationRecord
    model: ModelMetadataRecord
    conflict: ConflictStatusRecord
    policy: PolicyEnforcementRecord
    freshness: SourceFreshnessRecord
    generated_at: datetime
