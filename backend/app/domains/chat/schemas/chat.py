from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AnswerLanguageMode = Literal["auto", "same_as_question", "workspace_default", "en", "de", "es", "fr"]


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
    scope_mode: Literal["all", "collection", "documents", "none"] | None = None
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


class ChatDebugResponse(BaseModel):
    latencies_ms: dict[str, int]
    retrieval_count: int
    selected_count: int
    rerank_applied: bool
    embedding_model: str | None = None
    llm_model: str | None = None
    detected_language: str | None = None
    answer_language_used: str | None = None


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
