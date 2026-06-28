"""Pydantic schemas for verified answers and knowledge cards (F255)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CitationIn(BaseModel):
    document_id: str
    chunk_id: str | None = None
    text_snippet: str | None = Field(default=None, max_length=4000)
    page_number: int | None = Field(default=None, ge=1)
    citation_order: int = Field(default=0, ge=0)

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("document_id must not be blank")
        return v.strip()


class CreateVerifiedAnswerRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    question: str = Field(min_length=1, max_length=2000)
    answer_text: str = Field(min_length=1, max_length=50000)
    tags: str | None = Field(default=None, max_length=1024)
    collection_id: str | None = None
    requires_citations: bool = True
    review_date: date | None = None
    expiry_date: date | None = None
    citations: list[CitationIn] = Field(default_factory=list)

    @field_validator("title", "question", "answer_text")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


class CreateFromChatRequest(BaseModel):
    """Promote a chat assistant message to a verified answer draft."""

    title: str = Field(min_length=1, max_length=512)
    question: str | None = Field(default=None, max_length=2000)
    tags: str | None = Field(default=None, max_length=1024)
    collection_id: str | None = None
    review_date: date | None = None
    expiry_date: date | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class UpdateVerifiedAnswerRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer_text: str | None = Field(default=None, min_length=1, max_length=50000)
    tags: str | None = None
    collection_id: str | None = None
    requires_citations: bool | None = None
    review_date: date | None = None
    expiry_date: date | None = None
    citations: list[CitationIn] | None = None
    change_reason: str = Field(default="manual_edit", max_length=255)

    @field_validator("title", "question", "answer_text")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


class ApproveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RejectRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def strip_note(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("note must not be blank")
        return stripped


class CitationResponse(BaseModel):
    citation_id: str
    document_id: str
    chunk_id: str | None
    text_snippet: str | None
    page_number: int | None
    citation_order: int


class VersionResponse(BaseModel):
    version_id: str
    version_number: int
    title: str
    question: str
    answer_text: str
    tags: str | None
    change_reason: str
    changed_by_id: str | None
    created_at: datetime


class VerifiedAnswerResponse(BaseModel):
    answer_id: str
    organization_id: str
    title: str
    question: str
    answer_text: str
    status: Literal["draft", "pending_review", "approved", "published", "archived", "deprecated"]
    tags: str | None
    collection_id: str | None
    owner_id: str | None
    requires_citations: bool
    review_date: date | None
    expiry_date: date | None
    approved_by_id: str | None
    approved_at: datetime | None
    published_at: datetime | None
    deprecated_at: datetime | None
    restored_at: datetime | None
    rejection_note: str | None
    source_message_id: str | None
    created_by_id: str | None
    is_stale: bool
    citations: list[CitationResponse]
    created_at: datetime
    updated_at: datetime


class VerifiedAnswerListResponse(BaseModel):
    items: list[VerifiedAnswerResponse]
    total: int
    limit: int
    offset: int


class VerifiedAnswerVersionListResponse(BaseModel):
    items: list[VersionResponse]
    total: int
