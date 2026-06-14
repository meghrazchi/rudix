from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
    rerank_score: float | None = None
    rerank_rank: int | None = None
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


class ChatDebugResponse(BaseModel):
    latencies_ms: dict[str, int]
    retrieval_count: int
    selected_count: int
    rerank_applied: bool
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
    graph_relation_types_used: list[str] = Field(default_factory=list)


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
    debug: ChatDebugResponse
    created_at: datetime
