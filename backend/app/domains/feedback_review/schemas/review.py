from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackReviewStatusLiteral = Literal[
    "new",
    "triaged",
    "accepted",
    "rejected",
    "needs_document_update",
    "needs_prompt_retrieval_fix",
    "converted_to_evaluation",
    "resolved",
    # Legacy values kept for backward compatibility.
    "needs_document",
    "eval_created",
    "fixed",
    "duplicate",
]
FeedbackSeverityLiteral = Literal["low", "medium", "high"]
FeedbackCategoryLiteral = Literal[
    "wrong_answer",
    "bad_citation",
    "missing_source",
    "outdated_source",
    "hallucination_risk",
    "conflict_not_detected",
    "unclear_answer",
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

_STATUS_NORMALIZATION: dict[str, str] = {
    "needs_document": "needs_document_update",
    "eval_created": "converted_to_evaluation",
    "fixed": "resolved",
}

_STATUS_FILTER_ALIASES: dict[str, set[str]] = {
    "needs_document_update": {"needs_document_update", "needs_document"},
    "converted_to_evaluation": {"converted_to_evaluation", "eval_created"},
    "resolved": {"resolved", "fixed"},
}

_CATEGORY_NORMALIZATION: dict[str, str] = {
    "missing_information": "missing_source",
    "stale_source": "outdated_source",
    "low_confidence": "hallucination_risk",
    "conflicting_source": "conflict_not_detected",
    "not_enough_detail": "unclear_answer",
}

_CATEGORY_FILTER_ALIASES: dict[str, set[str]] = {
    "missing_source": {"missing_source", "missing_information"},
    "outdated_source": {"outdated_source", "stale_source"},
    "hallucination_risk": {"hallucination_risk", "low_confidence"},
    "conflict_not_detected": {"conflict_not_detected", "conflicting_source"},
    "unclear_answer": {"unclear_answer", "not_enough_detail"},
}


def normalize_feedback_status(value: str) -> str:
    return _STATUS_NORMALIZATION.get(value, value)


def normalize_feedback_category(value: str | None) -> str | None:
    if value is None:
        return None
    return _CATEGORY_NORMALIZATION.get(value, value)


def feedback_status_filter_candidates(value: str) -> set[str]:
    normalized = normalize_feedback_status(value)
    return _STATUS_FILTER_ALIASES.get(normalized, {normalized})


def feedback_category_filter_candidates(value: str) -> set[str]:
    normalized = normalize_feedback_category(value)
    if normalized is None:
        return set()
    return _CATEGORY_FILTER_ALIASES.get(normalized, {normalized})


class TriageFeedbackRequest(BaseModel):
    severity: FeedbackSeverityLiteral = "medium"
    reviewer_notes: str | None = Field(default=None, max_length=4000)


class UpdateReviewItemRequest(BaseModel):
    status: FeedbackReviewStatusLiteral | None = None
    severity: FeedbackSeverityLiteral | None = None
    reviewer_notes: str | None = Field(default=None, max_length=4000)
    reviewer_id: str | None = None
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
    answer_id: str | None = None
    message_id: str
    submitter_user_id: str
    rating: str
    reason: str | None = None
    comment: str | None = None
    # F303 fields
    category: FeedbackCategoryLiteral | None = None
    question_text: str | None = None
    answer_text: str | None = None
    citations: list[dict] | None = None
    retrieval_diagnostics: dict | None = None
    model_name: str | None = None
    llm_provider: str | None = None
    confidence_score: float | None = None
    redacted_at: datetime | None = None
    converted_to_eval_question_id: str | None = None
    # F316 fields
    trust_metadata: dict | None = None
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
            trust_metadata = getattr(feedback, "trust_metadata_json", None)
            citations = getattr(feedback, "citations_json", None)
            if isinstance(citations, dict):
                raw_citations = citations.get("items")
            else:
                raw_citations = citations
            fb_summary = FeedbackSummaryResponse(
                feedback_id=str(feedback.id),
                answer_id=str(feedback.message_id),
                message_id=str(feedback.message_id),
                submitter_user_id=str(feedback.user_id),
                rating=feedback.rating,
                reason=feedback.reason,
                comment=feedback.comment,
                category=normalize_feedback_category(feedback.category),  # type: ignore[arg-type]
                question_text=feedback.question_text,
                answer_text=feedback.answer_text,
                citations=raw_citations if isinstance(raw_citations, list) else None,
                retrieval_diagnostics=getattr(feedback, "retrieval_diagnostics_json", None),
                model_name=feedback.model_name,
                llm_provider=(
                    trust_metadata.get("llm_provider") if isinstance(trust_metadata, dict) else None
                ),
                confidence_score=(
                    trust_metadata.get("confidence_score")
                    if isinstance(trust_metadata, dict)
                    else None
                ),
                redacted_at=feedback.redacted_at,
                converted_to_eval_question_id=str(feedback.converted_to_eval_question_id)
                if feedback.converted_to_eval_question_id
                else None,
                trust_metadata=trust_metadata if isinstance(trust_metadata, dict) else None,
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
            status=normalize_feedback_status(item.status),  # type: ignore[arg-type]
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
            answer_id=str(feedback.message_id),
            message_id=str(feedback.message_id),
            submitter_user_id=str(feedback.user_id),
            rating=feedback.rating,
            reason=feedback.reason,
            comment=feedback.comment,
            category=normalize_feedback_category(feedback.category),  # type: ignore[arg-type]
            question_text=feedback.question_text,
            answer_text=feedback.answer_text,
            citations=(
                feedback.citations_json.get("items")
                if isinstance(feedback.citations_json, dict)
                else feedback.citations_json
            ),
            retrieval_diagnostics=feedback.retrieval_diagnostics_json,
            model_name=feedback.model_name,
            llm_provider=(
                feedback.trust_metadata_json.get("llm_provider")
                if isinstance(feedback.trust_metadata_json, dict)
                else None
            ),
            confidence_score=(
                feedback.trust_metadata_json.get("confidence_score")
                if isinstance(feedback.trust_metadata_json, dict)
                else None
            ),
            redacted_at=feedback.redacted_at,
            converted_to_eval_question_id=str(feedback.converted_to_eval_question_id)
            if feedback.converted_to_eval_question_id
            else None,
            trust_metadata=feedback.trust_metadata_json
            if isinstance(feedback.trust_metadata_json, dict)
            else None,
            trace_id=getattr(feedback, "trace_id", None),
            selected_citation_ids=getattr(feedback, "selected_citation_ids", None),
            submitted_at=feedback.created_at,
        )
        return cls(
            review_id="",
            feedback_id=str(feedback.id),
            answer_id=str(feedback.message_id),
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
