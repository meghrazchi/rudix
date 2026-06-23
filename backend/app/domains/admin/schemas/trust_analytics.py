"""Pydantic schemas for the admin trust analytics API (F317).

Returned by GET /admin/trust-analytics. Aggregates trust metric events
emitted by TrustMetricsService without exposing raw question/answer content.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TrustAnalyticsDateRange(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")

    model_config = {"populate_by_name": True}


class TrustDistribution(BaseModel):
    """Per-level counts and percentage share of answered turns."""

    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    warning_count: int = 0
    not_found_count: int = 0
    high_pct: float | None = None
    medium_pct: float | None = None
    low_pct: float | None = None
    warning_pct: float | None = None
    not_found_pct: float | None = None


class WarningBreakdown(BaseModel):
    """Counts of answers that triggered each warning type."""

    stale_source_count: int = 0
    conflict_count: int = 0
    ocr_count: int = 0
    extraction_count: int = 0
    processing_count: int = 0
    evidence_quality_count: int = 0
    citation_validation_failed_count: int = 0


class TrustTrendPoint(BaseModel):
    """Single day data point for trend charts."""

    date: date
    answer_count: int
    not_found_count: int
    not_found_rate: float | None = None
    avg_confidence_score: float | None = None
    avg_citation_support_score: float | None = None
    high_trust_count: int = 0
    low_trust_count: int = 0


class LangfuseIntegrationStatus(BaseModel):
    """Whether Langfuse trace linking is available for trust events."""

    enabled: bool
    traces_linked_count: int = 0


class TrustAnalyticsResponse(BaseModel):
    """Aggregated trust analytics for an org over a date range."""

    organization_id: str
    range: TrustAnalyticsDateRange
    generated_at: datetime

    total_answers: int
    not_found_rate: float | None = None
    avg_confidence_score: float | None = None
    avg_citation_support_score: float | None = None
    avg_verification_support_score: float | None = None
    unsupported_claims_removed_total: int = 0
    conflict_detection_rate: float | None = None

    trust_distribution: TrustDistribution
    warnings: WarningBreakdown
    daily_trends: list[TrustTrendPoint] = Field(default_factory=list)
    langfuse: LangfuseIntegrationStatus

    telemetry_missing: bool = False
