from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Profile config
# ---------------------------------------------------------------------------


class RagProfileConfig(BaseModel):
    """All retrieval and generation tuning knobs for a RAG profile."""

    top_k: int = Field(default=10, ge=1, le=100)
    rerank_enabled: bool = Field(default=False)
    rerank_model: str | None = Field(default=None, max_length=255)
    rerank_provider: str | None = Field(default=None, max_length=64)
    rerank_timeout_seconds: float | None = Field(default=None, ge=0.1, le=120.0)
    rerank_batch_size: int | None = Field(default=None, ge=1, le=200)
    rerank_input_max_candidates: int | None = Field(default=None, ge=1, le=200)
    rerank_max_candidate_chars: int | None = Field(default=None, ge=128, le=20_000)
    rerank_fallback_behavior: Literal["original", "disabled"] = Field(default="original")
    confidence_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_strictness: Literal["strict", "moderate", "lenient"] = Field(default="moderate")
    model_provider: str | None = Field(default=None, max_length=64)
    model_name: str | None = Field(default=None, max_length=255)
    prompt_template: str | None = Field(default=None, max_length=32_000)
    safety_mode: Literal["strict", "standard", "permissive"] = Field(default="standard")
    # Optional chunk post-filter applied after vector retrieval
    chunk_filter: dict | None = Field(default=None)
    max_context_tokens: int | None = Field(default=None, ge=256, le=128_000)
    # Hybrid retrieval (F293): combines vector search with PostgreSQL full-text search.
    hybrid_retrieval_enabled: bool = Field(default=False)
    hybrid_vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    hybrid_exact_match_boost: float = Field(default=1.5, ge=1.0, le=10.0)
    # Query rewriting and decomposition (F295).
    # query_rewriting_enabled: allow LLM to expand/rewrite the retrieval query.
    # query_decomposition_enabled: allow LLM to split multi-part questions into sub-queries.
    # query_rewriting_max_sub_queries: hard cap on generated sub-queries per question.
    query_rewriting_enabled: bool = Field(default=True)
    query_decomposition_enabled: bool = Field(default=True)
    query_rewriting_max_sub_queries: int = Field(default=4, ge=1, le=8)
    # Conflict detection and agreement scoring (F301).
    # conflict_detection_enabled: run the detector over selected chunks and
    # surface agreement metadata when multiple sources disagree.
    conflict_detection_enabled: bool = Field(default=False)
    # Grounded-answer verification (F296).
    # grounded_answer_verification_enabled: run LLM verifier after generation to check claim support.
    # grounded_answer_verification_mode: "strict" refuses the whole answer when unsupported;
    #   "standard" only removes individual unsupported claims.
    # grounded_answer_verification_threshold: minimum verification_score to consider answer supported.
    grounded_answer_verification_enabled: bool = Field(default=False)
    grounded_answer_verification_mode: Literal["strict", "standard"] = Field(default="standard")
    grounded_answer_verification_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # Source freshness and trust-status scoring (F297).
    # freshness_boost_enabled: apply per-status score multipliers during retrieval.
    # exclude_deprecated_docs: drop deprecated/superseded/expired docs from results by default.
    # exclude_expired_docs: explicitly control whether expired docs are omitted.
    # stale_threshold_days: org-level override for how many days without review before a doc is stale.
    freshness_boost_enabled: bool = Field(default=True)
    exclude_deprecated_docs: bool = Field(default=True)
    exclude_expired_docs: bool = Field(default=True)
    stale_threshold_days: int | None = Field(default=None, ge=1, le=3650)
    # Table-aware retrieval (F298).
    # table_retrieval_boost_enabled: apply score multiplier to table chunks on table-like queries.
    # table_retrieval_boost_multiplier: per-profile multiplier override (default uses system setting).
    table_retrieval_boost_enabled: bool = Field(default=True)
    table_retrieval_boost_multiplier: float = Field(default=1.25, ge=1.0, le=5.0)
    # Parent-context expansion (F300).
    # parent_context_expansion_enabled: substitute parent section text for child chunks in the LLM
    #   prompt so the model receives richer surrounding context without losing precise citations.
    # parent_context_max_tokens_per_chunk: hard per-chunk token budget for expanded parent text.
    #   Parent texts exceeding this limit are truncated at a word boundary.
    parent_context_expansion_enabled: bool = Field(default=True)
    parent_context_max_tokens_per_chunk: int = Field(default=512, ge=64, le=8192)
    # Planner-critic-refiner pipeline (F339).
    # planner_critic_refiner_enabled: run the planner/critic/refiner on applicable answers.
    # planner_critic_refiner_mode: "high_risk_only" limits to strategies flagged as high-risk;
    #   "always" runs critic+refiner on every answer regardless of strategy.
    # planner_high_risk_strategies: list of strategy names that trigger critic+refiner.
    planner_critic_refiner_enabled: bool = Field(default=False)
    planner_critic_refiner_mode: Literal["high_risk_only", "always"] = Field(
        default="high_risk_only"
    )
    planner_high_risk_strategies: list[str] = Field(
        default_factory=lambda: ["legal_compliance", "policy_lookup", "comparison"]
    )
    # Strict context packing (F340).
    # context_packing_enabled: run the context packer after reranking to apply priority scoring,
    #   rejection rules, and a global token budget before prompt construction.
    # context_packing_strategy: "strict" enforces a hard token budget and rejects weak OCR /
    #   stale-superseded chunks; "balanced" applies soft budget and OCR rejection only;
    #   "permissive" disables all rejection rules.
    # context_budget_max_tokens: maximum estimated tokens for the full evidence context window.
    #   None means unlimited (only top_k limits selection).
    # context_min_relevance_score: floor below which a chunk is rejected as unrelated.
    #   The strategy preset raises this floor if the config value is lower than the preset.
    # context_reject_weak_ocr: drop chunks from documents with failed/low-confidence OCR.
    # context_reject_stale_superseded: drop deprecated/expired sources even after the
    #   exclusion-fallback has re-included them (strict compliance mode).
    # context_require_citations: metadata flag passed to the prompt builder; when True,
    #   the prompt instructs the model to cite every claim.
    # context_not_found_min_chunks: minimum chunks that must survive packing before the
    #   pipeline attempts a grounded answer (fewer → not_found).
    context_packing_enabled: bool = Field(default=False)
    context_packing_strategy: Literal["strict", "balanced", "permissive"] = Field(
        default="balanced"
    )
    context_budget_max_tokens: int | None = Field(default=None, ge=256, le=128_000)
    context_min_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    context_reject_weak_ocr: bool = Field(default=True)
    context_reject_stale_superseded: bool = Field(default=False)
    context_require_citations: bool = Field(default=True)
    context_not_found_min_chunks: int = Field(default=1, ge=1, le=50)
    # Dynamic retrieval strategy routing (F341).
    # retrieval_strategy_override: admin-set override that forces a specific
    # retrieval method for all queries using this profile. "auto" (default) lets
    # the router decide based on question intent. Per-query user overrides are
    # governed separately by feature_enable_retrieval_strategy_user_override.
    retrieval_strategy_override: (
        Literal[
            "auto",
            "vector",
            "keyword",
            "hybrid",
            "table_aware",
            "parent_child",
            "graph_rag",
            "connector_aware",
        ]
        | None
    ) = Field(default=None)

    @field_validator("rerank_model")
    @classmethod
    def validate_rerank_model(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("rerank_model must not be blank")
            return trimmed
        return value

    @field_validator("rerank_provider", "rerank_fallback_behavior")
    @classmethod
    def validate_rerank_provider(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip().lower()
        if not trimmed:
            raise ValueError("rerank_provider must not be blank")
        return trimmed

    @field_validator("model_provider")
    @classmethod
    def validate_model_provider(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("model_provider must not be blank")
            return trimmed
        return value

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("model_name must not be blank")
            return trimmed
        return value


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class CreateRagProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    config: RagProfileConfig = Field(default_factory=RagProfileConfig)
    set_as_default: bool = Field(default=False)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("description must not be blank")
        return trimmed


class UpdateRagProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    config: RagProfileConfig | None = None
    set_as_default: bool | None = None
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class RollbackRagProfileRequest(BaseModel):
    version_number: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RagProfileResponse(BaseModel):
    profile_id: str
    organization_id: str
    name: str
    description: str | None = None
    config: dict
    is_default: bool
    is_archived: bool
    version: int
    created_by_id: str | None = None
    updated_by_id: str | None = None
    created_at: datetime
    updated_at: datetime


class RagProfileListResponse(BaseModel):
    items: list[RagProfileResponse]
    total: int
    limit: int
    offset: int


class RagProfileVersionResponse(BaseModel):
    version_id: str
    rag_profile_id: str
    version_number: int
    config_snapshot: dict
    change_note: str | None = None
    changed_by_id: str | None = None
    created_at: datetime


class RagProfileVersionListResponse(BaseModel):
    items: list[RagProfileVersionResponse]
    total: int


# ---------------------------------------------------------------------------
# Collection overrides
# ---------------------------------------------------------------------------


class SetCollectionOverrideRequest(BaseModel):
    rag_profile_id: str

    @field_validator("rag_profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("rag_profile_id must not be blank")
        return trimmed


class CollectionOverrideResponse(BaseModel):
    override_id: str
    organization_id: str
    collection_id: str
    rag_profile_id: str
    created_by_id: str | None = None
    created_at: datetime


class CollectionOverrideListResponse(BaseModel):
    items: list[CollectionOverrideResponse]
    total: int


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


class ResolvedRagProfileResponse(BaseModel):
    """The effective RAG profile for a given org / collection context."""

    profile_id: str
    name: str
    version: int
    config: dict
    source: Literal["collection_override", "org_default", "system_default"]
