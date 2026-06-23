from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domains.chat.schemas.trust_metadata import AnswerTrustMetadataResponse

AnswerLanguageMode = Literal[
    "auto", "same_as_question", "workspace_default", "en", "de", "es", "fr"
]
SourceScopeMode = Literal[
    "all",
    "uploaded",
    "collections",
    "connector_sources",
    "connector_items",
]
SourceSyncStatus = Literal["uploaded", "active", "stale", "revoked", "deleted", "unknown"]


class SourceScopeRequest(BaseModel):
    mode: SourceScopeMode = "all"
    provider_keys: list[str] = Field(default_factory=list, max_length=50)
    connection_ids: list[str] = Field(default_factory=list, max_length=50)
    provider_source_ids: list[str] = Field(default_factory=list, max_length=50)
    external_source_ids: list[str] = Field(default_factory=list, max_length=50)
    external_item_ids: list[str] = Field(default_factory=list, max_length=50)
    collection_ids: list[str] = Field(default_factory=list, max_length=50)
    document_types: list[str] = Field(default_factory=list, max_length=10)
    sync_statuses: list[SourceSyncStatus] = Field(default_factory=list, max_length=10)

    @field_validator(
        "provider_keys",
        "connection_ids",
        "provider_source_ids",
        "external_source_ids",
        "external_item_ids",
        "collection_ids",
        "document_types",
        mode="before",
    )
    @classmethod
    def validate_string_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("source scope values must be arrays")
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_value in value:
            normalized_value = str(raw_value).strip()
            if not normalized_value or normalized_value in seen:
                continue
            seen.add(normalized_value)
            normalized.append(normalized_value)
        return normalized


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    stream: bool = False


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    chat_session_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    top_k: int | None = Field(default=None, ge=1, le=200)
    rerank: bool = True
    scope_mode: (
        Literal[
            "all",
            "collection",
            "documents",
            "connectors",
            "none",
        ]
        | None
    ) = None
    source_scope: SourceScopeRequest | None = None
    answer_language: AnswerLanguageMode | None = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("question must not be blank")
        return trimmed


class CreateChatSessionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed


class UpdateChatSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("title must not be blank")
        return trimmed


class ChatSessionResponse(BaseModel):
    session_id: str
    title: str | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]
    total: int
    limit: int
    offset: int


class ChatStatsResponse(BaseModel):
    questions_asked: int
    total_sessions: int


class ChatConflictPairResponse(BaseModel):
    document_id_a: str
    document_id_b: str
    topic: str
    severity: Literal["low", "medium", "high"] = "medium"


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    page_number: int | None = None
    score: float | None = None


class ChatMessageResponse(BaseModel):
    session_id: str
    message_id: str
    role: Literal["assistant"] = "assistant"
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ChatSessionMessageResponse(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    confidence_score: float | None = None
    confidence_category: Literal["low", "medium", "high"] | None = None
    citations: list["ChatCitationResponse"] = Field(default_factory=list)
    created_at: datetime


class ChatSessionMessageListResponse(BaseModel):
    items: list[ChatSessionMessageResponse]
    total: int
    limit: int
    offset: int


class ChatCitationResponse(BaseModel):
    document_id: str
    chunk_id: str
    filename: str | None = None
    page_number: int | None = None
    score: float | None = None
    similarity_score: float | None = None
    original_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None
    text_snippet: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    source_provider: str | None = None
    source_provider_label: str | None = None
    source_title: str | None = None
    source_key: str | None = None
    source_section: str | None = None
    source_deep_link: str | None = None
    source_last_synced_at: datetime | None = None
    source_trust_status: (
        Literal[
            "trusted",
            "stale",
            "revoked",
            "deleted",
            "unknown",
            "uploaded",
        ]
        | None
    ) = None
    source_acl_snapshot: dict[str, Any] = Field(default_factory=dict)
    conflict_status: Literal["preferred", "conflicting", "neutral"] | None = None
    # Source freshness fields (F297/F311): populated from document trust metadata.
    doc_trust_status: str | None = None
    doc_review_status: str | None = None
    doc_review_owner_id: str | None = None
    doc_review_due_date: date | None = None
    doc_expiry_date: date | None = None
    doc_version_label: str | None = None
    doc_review_date: date | None = None
    doc_effective_date: date | None = None
    doc_stale_warning: bool = False
    doc_expired_warning: bool = False
    doc_is_excluded_status: bool = False
    # F311 — normalized freshness state + additional provenance display
    freshness_state: str | None = None
    doc_last_updated_at: datetime | None = None
    doc_unreviewed_warning: bool = False
    doc_deprecated_warning: bool = False
    # Table-aware retrieval (F298): populated when the cited chunk is a table.
    is_table_chunk: bool = False
    table_caption: str | None = None
    table_row_count: int | None = None
    table_col_count: int | None = None
    table_headers: list[str] = Field(default_factory=list)
    table_section_context: str | None = None
    # OCR quality (F299): populated when the source document was OCR-processed.
    doc_ocr_quality_status: str | None = None
    doc_ocr_low_confidence_warning: bool = False
    # Evidence quality (F315): table extraction confidence and document processing quality.
    # table_extraction_confidence: raw confidence from the extraction engine for this table chunk.
    # table_low_confidence_warning: True when table_extraction_confidence < 0.4.
    # doc_extraction_quality: document_profile from extraction_snapshot (e.g. corrupted, scanned).
    # doc_extraction_warning: True when extraction profile is problematic or confidence is low.
    # doc_processing_warning: True when the source document has incomplete or failed processing.
    table_extraction_confidence: float | None = None
    table_low_confidence_warning: bool = False
    doc_extraction_quality: str | None = None
    doc_extraction_warning: bool = False
    doc_processing_warning: bool = False


class ChatDebugResponse(BaseModel):
    latencies_ms: dict[str, int]
    request_id: str | None = None
    trace_request_id: str | None = None
    retrieval_candidate_count: int = 0
    retrieval_count: int
    selected_count: int
    top_k: int = 0
    search_mode: str | None = None
    source_scope_mode: str | None = None
    source_scope_label: str | None = None
    retrieval_profile_name: str | None = None
    retrieval_profile_scope: str | None = None
    retrieval_profile_source: str | None = None
    retrieval_filters: list[str] = Field(default_factory=list)
    rerank_applied: bool
    rerank_enabled: bool = False
    rerank_provider: str | None = None
    rerank_model: str | None = None
    rerank_fallback_used: bool = False
    rerank_fallback_reason: str | None = None
    rerank_input_count: int = 0
    rerank_score_min: float | None = None
    rerank_score_max: float | None = None
    rerank_batch_count: int = 0
    rerank_prompt_tokens: int = 0
    rerank_completion_tokens: int = 0
    rerank_total_tokens: int = 0
    rerank_cost_usd: float | None = None
    source_scope: str | None = None
    embedding_model: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    fallback_used: bool = False
    fallback_from: str | None = None
    fallback_to: str | None = None
    fallback_reason: str | None = None
    detected_language: str | None = None
    answer_language_used: str | None = None
    prompt_template_key: str | None = None
    prompt_template_version: int | None = None
    prompt_template_version_id: str | None = None
    graph_context_enabled: bool = False
    graph_context_used: bool = False
    graph_context_unavailable: bool = False
    graph_context_reason: str | None = None
    graph_seed_entity_count: int = 0
    graph_related_entity_count: int = 0
    graph_chunk_count: int = 0
    graph_max_hops_used: int = 0
    conflict_detection_enabled: bool = False
    conflict_detection_applied: bool = False
    conflict_detection_latency_ms: int = 0
    conflict_detection_agreement_level: Literal["full", "partial", "conflicting"] = "full"
    conflict_detection_conflict_count: int = 0
    conflict_detection_conflicting_document_ids: list[str] = Field(default_factory=list)
    conflict_detection_preferred_document_ids: list[str] = Field(default_factory=list)
    conflict_detection_model: str | None = None
    conflict_detection_provider: str | None = None
    graph_relation_types_used: list[str] = Field(default_factory=list)
    hybrid_retrieval_enabled: bool = False
    hybrid_vector_hit_count: int = 0
    hybrid_keyword_hit_count: int = 0
    hybrid_exact_match_tokens: list[str] = Field(default_factory=list)
    query_rewriting_enabled: bool = False
    query_rewriting_applied: bool = False
    query_decomposed: bool = False
    original_query: str | None = None
    rewritten_query: str | None = None
    sub_queries: list[str] = Field(default_factory=list)
    query_rewriting_strategy: str | None = None
    query_rewriting_latency_ms: int = 0
    grounded_verification_enabled: bool = False
    grounded_verification_applied: bool = False
    grounded_verification_verdict: str | None = None
    grounded_verification_score: float | None = None
    grounded_verification_claim_count: int = 0
    grounded_verification_supported_count: int = 0
    grounded_verification_partially_supported_count: int = 0
    grounded_verification_unsupported_count: int = 0
    grounded_verification_unverifiable_count: int = 0
    grounded_verification_removed_count: int = 0
    grounded_verification_reason_codes: list[str] = Field(default_factory=list)
    grounded_verification_mode: str | None = None
    grounded_verification_threshold: float | None = None
    grounded_verification_model: str | None = None
    grounded_verification_latency_ms: int = 0
    freshness_filter_enabled: bool = False
    freshness_excluded_count: int = 0
    freshness_boosted_count: int = 0
    freshness_stale_count: int = 0
    freshness_unreviewed_count: int = 0
    freshness_deprecated_count: int = 0
    freshness_all_excluded_fallback: bool = False
    # Table-aware retrieval (F298).
    table_boost_enabled: bool = False
    table_boost_applied: bool = False
    table_boost_count: int = 0
    table_chunk_count: int = 0
    table_query_detected: bool = False
    # OCR quality downranking (F299).
    ocr_quality_downranking_enabled: bool = False
    ocr_low_confidence_chunk_count: int = 0
    # Parent-context expansion (F300): child chunks expanded to parent section text for LLM prompt.
    parent_context_expansion_enabled: bool = False
    parent_context_child_hit_count: int = 0
    parent_context_expanded_count: int = 0
    parent_context_tokens_used: int = 0


class ChatConfidenceExplanationResponse(BaseModel):
    top_similarity: float = Field(ge=0.0, le=1.0)
    average_similarity: float = Field(ge=0.0, le=1.0)
    top_rerank_score: float = Field(ge=0.0, le=1.0)
    citation_support_score: float = Field(ge=0.0, le=1.0)
    citation_validation_score: float = Field(ge=0.0, le=1.0)
    citation_coverage_score: float = Field(ge=0.0, le=1.0)
    retrieval_agreement_score: float = Field(ge=0.0, le=1.0)
    raw_score: float = Field(ge=0.0, le=1.0)
    citation_validation_multiplier: float = Field(ge=0.0, le=1.0)
    not_found_penalty_multiplier: float = Field(ge=0.0, le=1.0)
    no_context: bool
    not_found_signal: bool
    weights: dict[str, float]
    thresholds: dict[str, float]


class ChatQueryResponse(BaseModel):
    chat_session_id: str
    message_id: str
    answer: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_category: Literal["low", "medium", "high"]
    confidence_explanation: ChatConfidenceExplanationResponse
    not_found: bool
    citations: list[ChatCitationResponse] = Field(default_factory=list)
    citation_validation_failed: bool = False
    verification_failed: bool = False
    agreement_level: Literal["full", "partial", "conflicting"] = "full"
    conflict_detected: bool = False
    conflict_summary: str | None = None
    conflicting_document_ids: list[str] = Field(default_factory=list)
    preferred_document_ids: list[str] = Field(default_factory=list)
    conflict_pairs: list[ChatConflictPairResponse] = Field(default_factory=list)
    source_freshness_warning: bool = False
    source_freshness_warning_reason: str | None = None
    # AI response policy (F268)
    policy_applied: bool = False
    policy_outcome: str | None = None  # "allowed" | "blocked" | "warned"
    policy_violated_rules: list[str] = Field(default_factory=list)
    policy_warning_flags: list[str] = Field(default_factory=list)
    policy_disclaimer: str | None = None
    debug: ChatDebugResponse
    trust_metadata: AnswerTrustMetadataResponse | None = None
    created_at: datetime
