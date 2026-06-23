from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackReviewStatusLiteral = Literal[
    "new", "triaged", "needs_document", "accepted", "eval_created", "fixed", "rejected", "duplicate"
]
FeedbackSeverityLiteral = Literal["low", "medium", "high"]
FeedbackCategoryLiteral = Literal[
    "wrong_answer",
    "bad_citation",
    "outdated_source",
    "missing_information",
    "low_confidence",
    "unsafe_response",
    "missing_citation",
    "stale_source",
    "conflicting_source",
    "not_enough_detail",
    "should_have_said_not_found",
]
DifficultyLiteral = Literal["easy", "medium", "hard"]


class TriageFeedbackRequest(BaseModel):
    severity: FeedbackSeverityLiteral = "medium"
    reviewer_notes: str | None = Field(default=None, max_length=4000)


class UpdateReviewItemRequest(BaseModel):
    status: FeedbackReviewStatusLiteral | None = None
    severity: FeedbackSeverityLiteral | None = None
    reviewer_notes: str | None = Field(default=None, max_length=4000)
    linked_eval_question_id: str | None = None
    linked_document_id: str | None = None


class ConvertToEvalCaseRequest(BaseModel):
    evaluation_set_id: str
    default_difficulty: DifficultyLiteral = "medium"
    reviewer_notes: str | None = Field(default=None, max_length=4000)


class ConvertToEvalCaseResponse(BaseModel):
    review_id: str
    evaluation_set_id: str
    evaluation_question_id: str
    question: str
    already_existed: bool


class FeedbackSummaryResponse(BaseModel):
    feedback_id: str
    message_id: str
    submitter_user_id: str
    rating: str
    reason: str | None = None
    comment: str | None = None
    # F303 fields
    category: FeedbackCategoryLiteral | None = None
    question_text: str | None = None
    answer_text: str | None = None
    model_name: str | None = None
    redacted_at: datetime | None = None
    converted_to_eval_question_id: str | None = None
    # F316 fields
    trace_id: str | None = None
    selected_citation_ids: list[str] | None = None
    submitted_at: datetime


class MessageSummaryResponse(BaseModel):
    message_id: str
    session_id: str
    content_preview: str
    confidence_score: float | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    created_at: datetime


class FeedbackReviewItemResponse(BaseModel):
    review_id: str
    feedback_id: str
    organization_id: str
    status: FeedbackReviewStatusLiteral
    severity: FeedbackSeverityLiteral
    reviewer_id: str | None = None
    reviewer_notes: str | None = None
    linked_eval_question_id: str | None = None
    linked_document_id: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    feedback: FeedbackSummaryResponse | None = None
    message: MessageSummaryResponse | None = None

    @classmethod
    def from_model(
        cls,
        item: object,
        *,
        feedback: object | None = None,
        message: object | None = None,
    ) -> "FeedbackReviewItemResponse":
        from app.models.chat import ChatMessage
        from app.models.feedback_review_item import FeedbackReviewItem
        from app.models.message_feedback import MessageFeedback

        assert isinstance(item, FeedbackReviewItem)

        fb_summary: FeedbackSummaryResponse | None = None
        if feedback is not None:
            assert isinstance(feedback, MessageFeedback)
            fb_summary = FeedbackSummaryResponse(
                feedback_id=str(feedback.id),
                message_id=str(feedback.message_id),
                submitter_user_id=str(feedback.user_id),
                rating=feedback.rating,
                reason=feedback.reason,
                comment=feedback.comment,
                category=feedback.category,  # type: ignore[arg-type]
                question_text=feedback.question_text,
                answer_text=feedback.answer_text,
                model_name=feedback.model_name,
                redacted_at=feedback.redacted_at,
                converted_to_eval_question_id=str(feedback.converted_to_eval_question_id)
                if feedback.converted_to_eval_question_id
                else None,
                trace_id=getattr(feedback, "trace_id", None),
                selected_citation_ids=getattr(feedback, "selected_citation_ids", None),
                submitted_at=feedback.created_at,
            )

        msg_summary: MessageSummaryResponse | None = None
        if message is not None:
            assert isinstance(message, ChatMessage)
            preview = message.content[:300] if message.content else ""
            msg_summary = MessageSummaryResponse(
                message_id=str(message.id),
                session_id=str(message.chat_session_id),
                content_preview=preview,
                confidence_score=message.confidence_score,
                model_name=message.model_name,
                latency_ms=message.latency_ms,
                created_at=message.created_at,
            )

        return cls(
            review_id=str(item.id),
            feedback_id=str(item.feedback_id),
            organization_id=str(item.organization_id),
            status=item.status,  # type: ignore[arg-type]
            severity=item.severity,  # type: ignore[arg-type]
            reviewer_id=str(item.reviewer_id) if item.reviewer_id else None,
            reviewer_notes=item.reviewer_notes,
            linked_eval_question_id=str(item.linked_eval_question_id)
            if item.linked_eval_question_id
            else None,
            linked_document_id=str(item.linked_document_id) if item.linked_document_id else None,
            resolved_at=item.resolved_at,
            created_at=item.created_at,
            updated_at=item.updated_at,
            feedback=fb_summary,
            message=msg_summary,
        )

    @classmethod
    def from_model_feedback_only(cls, feedback: object) -> "FeedbackReviewItemResponse":
        """Build a minimal response when there is no associated FeedbackReviewItem."""
        from app.models.message_feedback import MessageFeedback

        assert isinstance(feedback, MessageFeedback)
        fb_summary = FeedbackSummaryResponse(
            feedback_id=str(feedback.id),
            message_id=str(feedback.message_id),
            submitter_user_id=str(feedback.user_id),
            rating=feedback.rating,
            reason=feedback.reason,
            comment=feedback.comment,
            category=feedback.category,  # type: ignore[arg-type]
            question_text=feedback.question_text,
            answer_text=feedback.answer_text,
            model_name=feedback.model_name,
            redacted_at=feedback.redacted_at,
            converted_to_eval_question_id=str(feedback.converted_to_eval_question_id)
            if feedback.converted_to_eval_question_id
            else None,
            trace_id=getattr(feedback, "trace_id", None),
            selected_citation_ids=getattr(feedback, "selected_citation_ids", None),
            submitted_at=feedback.created_at,
        )
        return cls(
            review_id="",
            feedback_id=str(feedback.id),
            organization_id=str(feedback.organization_id),
            status="new",  # type: ignore[arg-type]
            severity="medium",  # type: ignore[arg-type]
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
            feedback=fb_summary,
            message=None,
        )


class FeedbackReviewListResponse(BaseModel):
    items: list[FeedbackReviewItemResponse]
    total: int
    limit: int
    offset: int


class FeedbackCategoryMetric(BaseModel):
    category: str
    count: int
    avg_confidence_score: float | None = None


class FeedbackMetricsResponse(BaseModel):
    period_days: int
    total_feedback: int
    categories: list[FeedbackCategoryMetric]
