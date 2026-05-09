from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class ChatCitationResponse(BaseModel):
    document_id: str
    chunk_id: str
    page_number: int | None = None
    score: float | None = None
    text_snippet: str | None = None


class ChatDebugResponse(BaseModel):
    latencies_ms: dict[str, int]
    retrieval_count: int
    selected_count: int
    rerank_applied: bool
    llm_model: str | None = None


class ChatQueryResponse(BaseModel):
    chat_session_id: str
    message_id: str
    answer: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    not_found: bool
    citations: list[ChatCitationResponse] = Field(default_factory=list)
    debug: ChatDebugResponse
    created_at: datetime
