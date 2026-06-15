from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackRatingLiteral = Literal["up", "down"]
FeedbackReasonLiteral = Literal[
    "wrong_citation",
    "hallucination",
    "outdated_source",
    "missing_document",
    "unsafe_content",
    "other",
]
FeedbackCategoryLiteral = Literal[
    "wrong_answer",
    "bad_citation",
    "outdated_source",
    "missing_information",
    "low_confidence",
    "unsafe_response",
]


class FeedbackDiagnostics(BaseModel):
    question_text: str | None = Field(default=None, max_length=4000)
    answer_text: str | None = Field(default=None, max_length=8000)
    citations: list[dict] | None = None
    retrieval_diagnostics: dict | None = None
    model_name: str | None = Field(default=None, max_length=128)
    rag_profile_id: str | None = None


class SubmitFeedbackRequest(BaseModel):
    rating: FeedbackRatingLiteral
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = Field(default=None, max_length=1000)
    # F303 — structured category and optional diagnostics snapshot
    category: FeedbackCategoryLiteral | None = None
    diagnostics: FeedbackDiagnostics | None = None


class MessageFeedbackResponse(BaseModel):
    feedback_id: str
    message_id: str
    user_id: str
    rating: FeedbackRatingLiteral
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = None
    # F303 fields
    category: FeedbackCategoryLiteral | None = None
    question_text: str | None = None
    answer_text: str | None = None
    model_name: str | None = None
    rag_profile_id: str | None = None
    retain_until: datetime | None = None
    redacted_at: datetime | None = None
    converted_to_eval_question_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionFeedbackListResponse(BaseModel):
    items: list[MessageFeedbackResponse]
    total: int
