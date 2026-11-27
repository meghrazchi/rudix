"""Retrieval, rerank, confidence, chunking, and answer-quality settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from pydantic_settings import NoDecode

from app.core.settings.enums import (
    RerankFallbackBehavior,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class RagSettings(BaseModel):
    retrieval_initial_top_k: int = Field(default=20, ge=1, le=200)
    retrieval_final_top_k: int = Field(default=5, ge=1, le=50)
    rerank_default_provider: str = Field(default="openai", min_length=1, max_length=64)
    rerank_default_model_name: str | None = Field(default=None, max_length=255)
    rerank_default_timeout_seconds: float = Field(default=6.0, ge=0.1, le=120.0)
    rerank_default_batch_size: int = Field(default=8, ge=1, le=200)
    rerank_default_input_candidates: int = Field(default=20, ge=1, le=200)
    rerank_default_candidate_chars: int = Field(default=2000, ge=128, le=20_000)
    rerank_default_fallback_behavior: RerankFallbackBehavior = RerankFallbackBehavior.original
    rerank_input_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    rerank_output_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    rerank_mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    rerank_mmr_candidate_count: int = Field(default=20, ge=1, le=200)
    rerank_mmr_duplicate_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    confidence_weight_top_similarity: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_weight_average_similarity: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_rerank_score: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_citation_support: float = Field(default=0.15, ge=0.0, le=1.0)
    confidence_weight_agreement: float = Field(default=0.10, ge=0.0, le=1.0)
    confidence_medium_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    confidence_high_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    confidence_not_found_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_not_found_penalty_multiplier: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_citation_coverage_target: int = Field(default=2, ge=1, le=20)
    confidence_graph_evidence_boost: float = Field(default=0.05, ge=0.0, le=0.30)
    confidence_freshness_stale_penalty: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_conflict_penalty_partial: float = Field(default=0.10, ge=0.0, le=1.0)
    confidence_conflict_penalty_conflicting: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_ocr_medium_multiplier: float = Field(default=0.90, ge=0.0, le=1.0)
    confidence_ocr_low_multiplier: float = Field(default=0.75, ge=0.0, le=1.0)
    confidence_ocr_failed_multiplier: float = Field(default=0.55, ge=0.0, le=1.0)
    confidence_warning_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    chunking_strategy: str = Field(default="token_recursive", min_length=1, max_length=64)
    document_index_version: str = Field(default="v1", min_length=1, max_length=64)
    # Extra index versions production retrieval still serves (CSV). The current
    # document_index_version is always active; evaluation "eval-" versions never are.
    document_active_index_versions: Annotated[list[str], NoDecode] = Field(
        default_factory=list, max_length=20
    )
    embedding_batch_max_items: int = Field(default=96, ge=1, le=2048)
    embedding_batch_max_tokens: int = Field(default=100000, ge=100, le=300000)
    embedding_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_retry_base_seconds: float = Field(default=0.5, ge=0.1, le=30.0)
    embedding_retry_max_seconds: float = Field(default=8.0, ge=0.1, le=120.0)
    feature_enable_embeddings: bool = True
    feature_enable_llm: bool = True
    feature_enable_evaluations: bool = True
    feature_enable_chunking_profiles: bool = False
    feature_enable_adaptive_chunking: bool = False
    feature_enable_hybrid_retrieval: bool = False
    # Weight given to vector (semantic) scores when merging. keyword weight = 1 - vector_weight.
    hybrid_retrieval_vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    # Constant k used in Reciprocal Rank Fusion: score = 1 / (k + rank).
    hybrid_retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    # Multiplier applied to a chunk's RRF score when an exact-match token is found.
    hybrid_retrieval_exact_match_boost: float = Field(default=1.5, ge=1.0, le=10.0)
    # Query rewriting and decomposition (F295).
    # When enabled the LLM rewrites vague questions and decomposes multi-part questions
    # into focused sub-queries for parallel retrieval.
    # WARNING: each LLM rewriting call adds latency and token cost before retrieval.
    # Keep query_rewriting_timeout_seconds well below the overall request timeout.
    retrieval_parallel_max_calls: int = Field(default=4, ge=1, le=50)
    retrieval_parallel_timeout_ms: int = Field(default=8_000, ge=100, le=300_000)
    retrieval_parallel_max_retry_attempts: int = Field(default=1, ge=0, le=10)
    retrieval_parallel_max_total_tokens: int | None = Field(default=4_000, ge=1, le=100_000)
    retrieval_parallel_max_total_cost_usd: float | None = Field(default=0.05, ge=0.0, le=1000.0)
    feature_enable_query_rewriting: bool = False
    feature_enable_query_rewrite_preview: bool = True
    query_rewriting_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    query_rewriting_max_sub_queries: int = Field(default=4, ge=1, le=8)
    # Conflict detection and agreement scoring (F301).
    # feature_enable_conflict_detection gates the extra analysis pass that detects
    # contradictory claims across retrieved documents.
    # conflict_detection_min_source_docs keeps the detector from running on
    # single-source answers where there is no meaningful disagreement signal.
    feature_enable_conflict_detection: bool = False
    conflict_detection_timeout_seconds: float = Field(default=6.0, ge=0.5, le=60.0)
    conflict_detection_min_source_docs: int = Field(default=2, ge=2, le=10)
    # Grounded-answer verifier (F296): checks that generated answers are supported
    # by retrieved source chunks. Unsupported claims are removed (standard mode)
    # or the answer is refused (strict mode). Adds one LLM call after generation.
    # Keep grounded_verification_timeout_seconds well below the overall request timeout.
    feature_enable_grounded_answer_verification: bool = False
    # Context injection scan (R05-09): retrieved chunks matching the prompt-injection
    # patterns are flagged in trust metadata, down-ranked (score times the multiplier),
    # or dropped before context packing.
    chat_context_injection_action: Literal["flag", "downrank", "drop"] = "downrank"
    chat_context_injection_downrank_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)
    grounded_verification_timeout_seconds: float = Field(default=12.0, ge=0.5, le=60.0)
    # Planner-critic-refiner pipeline (F339): classifies questions into answer strategies,
    # evaluates quality signals after generation, and rewrites high-risk answers using only
    # supported claims. Adds one LLM call (refiner) for high-risk answers when critic finds
    # medium/high severity issues. Keep refiner_timeout_seconds well below request timeout.
    feature_enable_planner_critic_refiner: bool = False
    refiner_timeout_seconds: float = Field(default=10.0, ge=0.5, le=60.0)
    # "high_risk_only": critic+refiner only runs when planner flags the question as high-risk.
    # "always": critic+refiner runs on every answer (higher latency and LLM cost).
    planner_critic_refiner_mode: str = Field(default="high_risk_only", max_length=32)
    feature_enable_language_aware_rag: bool = True

    @field_validator("document_index_version")
    @classmethod
    def validate_document_index_version(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("document_index_version must not be empty")
        if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "document_index_version may contain only letters, numbers, '.', '-', and '_'"
            )
        return cleaned

    @field_validator("document_active_index_versions", mode="before")
    @classmethod
    def validate_document_active_index_versions(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        raw_items = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw_items, list | tuple):
            raise ValueError("document_active_index_versions must be a CSV string or list")
        versions: list[str] = []
        for item in raw_items:
            cleaned = str(item).strip()
            if not cleaned or cleaned in versions:
                continue
            if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
                raise ValueError(
                    "document_active_index_versions entries may contain only letters, "
                    "numbers, '.', '-', and '_'"
                )
            if cleaned.lower().startswith("eval-"):
                raise ValueError("document_active_index_versions must not include eval- versions")
            versions.append(cleaned)
        return versions


def validate_rag_thresholds(settings: Settings) -> None:
    if settings.retrieval_final_top_k > settings.retrieval_initial_top_k:
        raise ValueError(
            "retrieval_final_top_k must be less than or equal to retrieval_initial_top_k"
        )

    if settings.rerank_mmr_candidate_count < settings.retrieval_final_top_k:
        raise ValueError("rerank_mmr_candidate_count must be >= retrieval_final_top_k")

    if settings.rerank_default_input_candidates < settings.retrieval_final_top_k:
        raise ValueError("rerank_default_input_candidates must be >= retrieval_final_top_k")
    if settings.rerank_default_batch_size > settings.rerank_default_input_candidates:
        raise ValueError("rerank_default_batch_size must be <= rerank_default_input_candidates")

    if settings.confidence_high_threshold < settings.confidence_medium_threshold:
        raise ValueError("confidence_high_threshold must be >= confidence_medium_threshold")

    if settings.confidence_not_found_threshold > settings.confidence_medium_threshold:
        raise ValueError("confidence_not_found_threshold must be <= confidence_medium_threshold")

    confidence_weight_sum = (
        settings.confidence_weight_top_similarity
        + settings.confidence_weight_average_similarity
        + settings.confidence_weight_rerank_score
        + settings.confidence_weight_citation_support
        + settings.confidence_weight_agreement
    )
    if confidence_weight_sum <= 0:
        raise ValueError("confidence weights sum must be > 0")

    if settings.chunk_overlap_tokens >= settings.chunk_size_tokens:
        raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")

    if settings.embedding_retry_max_seconds < settings.embedding_retry_base_seconds:
        raise ValueError("embedding_retry_max_seconds must be >= embedding_retry_base_seconds")

    if settings.llm_retry_max_seconds < settings.llm_retry_base_seconds:
        raise ValueError("llm_retry_max_seconds must be >= llm_retry_base_seconds")

    if settings.embedding_batch_max_tokens < settings.chunk_size_tokens:
        raise ValueError("embedding_batch_max_tokens must be >= chunk_size_tokens")
