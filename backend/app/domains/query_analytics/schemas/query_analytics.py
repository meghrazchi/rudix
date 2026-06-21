from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Date range helpers ─────────────────────────────────────────────────────────

class QueryAnalyticsDateRange(BaseModel):
    from_date: date
    to_date: date


# ── Trend data ─────────────────────────────────────────────────────────────────

class QueryTrendPoint(BaseModel):
    date: date
    total_queries: int
    unanswered: int
    low_confidence: int
    negative_feedback: int
    avg_confidence: float | None


class QueryTrendsResponse(BaseModel):
    organization_id: str
    range: QueryAnalyticsDateRange
    generated_at: datetime
    points: list[QueryTrendPoint]


# ── Dashboard summary ──────────────────────────────────────────────────────────

class FeedbackCategoryCount(BaseModel):
    category: str
    count: int


class QueryAnalyticsSummaryResponse(BaseModel):
    organization_id: str
    range: QueryAnalyticsDateRange
    generated_at: datetime
    enabled: bool
    disabled_reason: str | None = None

    total_queries: int
    answered_queries: int
    unanswered_queries: int
    low_confidence_queries: int
    negative_feedback_count: int

    unanswered_rate: float | None
    avg_confidence: float | None
    negative_feedback_rate: float | None

    top_feedback_categories: list[FeedbackCategoryCount]
    top_feedback_reasons: list[FeedbackCategoryCount]


# ── Knowledge gaps ─────────────────────────────────────────────────────────────

class KnowledgeGapResponse(BaseModel):
    gap_id: str
    organization_id: str
    gap_type: str
    topic_label: str
    description: str | None
    gap_source: str
    occurrence_count: int
    avg_confidence: float | None
    example_query: str | None
    status: str
    remediation_json: dict | None
    collection_id: str | None
    linked_document_id: str | None
    linked_eval_question_id: str | None
    converted_to: str | None
    converted_at: datetime | None
    reviewer_notes: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeGapListResponse(BaseModel):
    items: list[KnowledgeGapResponse]
    total: int


class CreateKnowledgeGapRequest(BaseModel):
    gap_type: str = Field(..., pattern="^(no_answer|low_confidence|bad_feedback|stale_citation|missing_source)$")
    topic_label: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    occurrence_count: int = Field(default=1, ge=1)
    avg_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    example_query: str | None = Field(default=None, max_length=4096)
    collection_id: str | None = None
    gap_source: str = Field(default="admin", pattern="^(admin|low_confidence_analysis|feedback_analysis|no_answer_analysis)$")


class UpdateKnowledgeGapRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|in_review|resolved|dismissed)$")
    reviewer_notes: str | None = Field(default=None, max_length=4096)
    linked_document_id: str | None = None
    description: str | None = Field(default=None, max_length=4096)


class ConvertKnowledgeGapRequest(BaseModel):
    target: str = Field(..., pattern="^(eval_case|doc_request|review_task)$")
    evaluation_set_id: str | None = None
    notes: str | None = Field(default=None, max_length=4096)


class ConvertKnowledgeGapResponse(BaseModel):
    gap_id: str
    converted_to: str
    converted_at: datetime
    linked_eval_question_id: str | None = None


# ── Auto-detect gaps ───────────────────────────────────────────────────────────

class DetectGapsRequest(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    low_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    min_occurrences: int = Field(default=3, ge=1)


class DetectGapsResponse(BaseModel):
    detected: int
    created: int
    skipped_duplicates: int
