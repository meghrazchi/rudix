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


class SubmitFeedbackRequest(BaseModel):
    rating: FeedbackRatingLiteral
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = Field(default=None, max_length=1000)


class MessageFeedbackResponse(BaseModel):
    feedback_id: str
    message_id: str
    user_id: str
    rating: FeedbackRatingLiteral
    reason: FeedbackReasonLiteral | None = None
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionFeedbackListResponse(BaseModel):
    items: list[MessageFeedbackResponse]
    total: int
