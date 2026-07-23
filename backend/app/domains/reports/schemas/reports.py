from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReportCategory = Literal[
    "question",
    "answer",
    "citation",
    "confidence",
    "feedback",
    "indexing",
    "connector_sync",
    "permission",
    "export",
    "audit",
]
ReportSort = Literal["occurred_at", "category", "event_type", "status", "count", "value"]
SortDirection = Literal["asc", "desc"]
AnswerQualityLevel = Literal["high", "medium", "low", "warning", "not_found"]


class ReportEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ReportCategory
    event_type: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_.-]+$")
    occurred_at: datetime
    workspace_id: UUID | None = None
    collection_id: UUID | None = None
    connector_id: UUID | None = None
    team_id: UUID | None = None
    source_id: UUID | None = None
    status: str | None = Field(default=None, max_length=32)
    count: int = Field(default=1, ge=0, le=1_000_000)
    value: Decimal | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    request_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ReportEventAccepted(BaseModel):
    id: UUID
    accepted: bool = True
    deduplicated: bool = False


class ReportMetric(BaseModel):
    key: str
    value: Decimal
    unit: Literal["count", "ratio", "milliseconds", "score"] = "count"


class ReportChartPoint(BaseModel):
    bucket: str
    series: str
    value: Decimal


class ReportTableRow(BaseModel):
    id: UUID
    occurred_at: datetime
    category: ReportCategory
    event_type: str
    status: str | None
    count: int
    value: Decimal | None
    duration_ms: int | None
    workspace_id: UUID | None
    collection_id: UUID | None
    connector_id: UUID | None
    user_id: UUID | None
    team_id: UUID | None
    source_id: UUID | None


class ReportActionItem(BaseModel):
    key: str
    severity: Literal["info", "warning", "critical"]
    count: int
    title: str


class ReportPage(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class ReportResponse(BaseModel):
    organization_id: UUID
    generated_at: datetime
    from_at: datetime
    to_at: datetime
    metrics: list[ReportMetric]
    chart: list[ReportChartPoint]
    table: list[ReportTableRow]
    action_items: list[ReportActionItem]
    pagination: ReportPage


class AnswerQualityMetrics(BaseModel):
    total_questions: int = 0
    average_confidence: float | None = None
    average_citation_support: float | None = None
    not_found_count: int = 0
    missing_citations_count: int = 0
    stale_source_warning_count: int = 0
    source_conflict_count: int = 0
    unsupported_claims_removed: int = 0


class AnswerQualityTrendPoint(BaseModel):
    date: str
    answer_count: int = 0
    average_confidence: float | None = None
    average_citation_support: float | None = None
    not_found_count: int = 0


class AnswerQualityDistributionPoint(BaseModel):
    level: AnswerQualityLevel
    count: int = 0


class AnswerQualityCollectionPoint(BaseModel):
    collection_id: UUID | None = None
    collection_name: str
    low_confidence_count: int = 0


class AnswerQualityFeedbackPoint(BaseModel):
    category: str
    count: int = 0


class AnswerQualityRow(BaseModel):
    message_id: UUID
    question: str
    user_id: UUID
    user_name: str
    collection_id: UUID | None = None
    collection_name: str | None = None
    source_id: UUID | None = None
    source_name: str | None = None
    confidence: float | None = None
    confidence_level: AnswerQualityLevel
    citation_support_score: float | None = None
    warnings: list[str] = Field(default_factory=list)
    feedback_status: str | None = None
    created_at: datetime


class AnswerQualityReportResponse(BaseModel):
    metrics: AnswerQualityMetrics
    confidence_distribution: list[AnswerQualityDistributionPoint]
    trends: list[AnswerQualityTrendPoint]
    low_confidence_by_collection: list[AnswerQualityCollectionPoint]
    bad_feedback_categories: list[AnswerQualityFeedbackPoint]
    items: list[AnswerQualityRow]
    pagination: ReportPage


class AnswerQualitySource(BaseModel):
    document_id: UUID
    document_name: str
    collection_id: UUID | None = None
    collection_name: str | None = None
    page_number: int | None = None


class AnswerQualityDetailResponse(BaseModel):
    message_id: UUID
    question: str
    final_answer: str
    user_id: UUID
    user_name: str
    confidence: float | None = None
    confidence_level: AnswerQualityLevel
    citation_support_score: float | None = None
    confidence_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sources: list[AnswerQualitySource] = Field(default_factory=list)
    feedback_id: UUID | None = None
    feedback_category: str | None = None
    feedback_comment: str | None = None
    feedback_status: str | None = None
    related_evaluation_case_id: UUID | None = None
    review_item_id: UUID | None = None
    created_at: datetime
