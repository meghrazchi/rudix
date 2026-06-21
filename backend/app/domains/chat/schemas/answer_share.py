from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AnswerShareAccessMode = Literal["org_only", "specific_users"]


class CreateAnswerShareRequest(BaseModel):
    access_mode: AnswerShareAccessMode = "org_only"
    allowed_user_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="User IDs allowed to view when access_mode is 'specific_users'.",
    )
    password: str | None = Field(
        default=None,
        min_length=4,
        max_length=128,
        description="Optional plaintext password; stored as Argon2 hash.",
    )
    expires_in_hours: int | None = Field(
        default=None,
        ge=1,
        le=8760,
        description="Hours until the share link expires. Omit for no expiry.",
    )


class AnswerShareResponse(BaseModel):
    share_id: str
    message_id: str
    token: str
    access_mode: AnswerShareAccessMode
    allowed_user_ids: list[str]
    has_password: bool
    created_at: datetime
    expires_at: datetime | None = None
    is_revoked: bool
    shared_by_user_id: str


class AnswerShareListResponse(BaseModel):
    items: list[AnswerShareResponse]
    total: int


class SharedAnswerCitationResponse(BaseModel):
    """Citation included in a shared answer; document_id/chunk_id omitted to prevent leakage."""

    filename: str | None = None
    page_number: int | None = None
    text_snippet: str | None = None
    source_provider_label: str | None = None
    source_title: str | None = None
    source_section: str | None = None
    source_key: str | None = None
    source_trust_status: str | None = None
    source_freshness_warning: bool = False
    source_freshness_warning_reason: str | None = None


class SharedAnswerResponse(BaseModel):
    question: str
    answer: str
    citations: list[SharedAnswerCitationResponse]
    confidence_score: float | None = None
    confidence_category: str | None = None
    shared_at: datetime
    expires_at: datetime | None = None
    access_mode: AnswerShareAccessMode
