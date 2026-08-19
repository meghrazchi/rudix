"""Pydantic schemas for the admin source health dashboard API (F352).

Returned by GET /admin/source-health/*. Aggregates existing indexing,
OCR, trust/review, connector sync, and metadata-completeness signals
already tracked on Document/Collection/connector models into a single
health rollup. No new persisted fields are introduced by this feature.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# Source types this dashboard understands. "file" and "connector" are both
# Document rows, split by Document.ingestion_source. "collection" is a
# Collection row summarizing its member documents. Graph-backed sources are
# NOT a fourth row type (that would double-count documents already listed as
# file/connector) — graph indexing status is instead surfaced as the
# `graph_indexed` facet on file/connector rows.
SourceType = str  # "file" | "connector" | "collection"
Freshness = str  # "fresh" | "stale" | "expired"


class SourceHealthSummaryResponse(BaseModel):
    """Org-scoped counters for the top-of-dashboard metric cards."""

    total_sources: int = 0
    indexed: int = 0
    failed_indexing: int = 0
    pending: int = 0
    ocr_required: int = 0
    ocr_low_confidence: int = 0
    table_extraction_warnings: int = 0
    missing_metadata: int = 0
    stale: int = 0
    deprecated: int = 0
    expired: int = 0
    unreviewed: int = 0
    needs_review: int = 0
    generated_at: datetime


class SourceStatusCount(BaseModel):
    status: str
    count: int


class IndexingFailurePoint(BaseModel):
    date: str
    failed_count: int


class StaleByCollection(BaseModel):
    collection_id: str | None
    collection_name: str
    stale_count: int


class OcrQualityCount(BaseModel):
    ocr_quality_status: str
    count: int


class ReviewNeedsByOwner(BaseModel):
    owner_id: str | None
    owner_name: str
    needs_review_count: int


class ConnectorFreshness(BaseModel):
    connection_id: str
    connector_name: str
    provider_key: str | None
    last_successful_sync_at: datetime | None
    days_since_last_sync: int | None
    status: str


class SourceHealthChartsResponse(BaseModel):
    status_distribution: list[SourceStatusCount] = Field(default_factory=list)
    indexing_failures: list[IndexingFailurePoint] = Field(default_factory=list)
    stale_by_collection: list[StaleByCollection] = Field(default_factory=list)
    ocr_quality_distribution: list[OcrQualityCount] = Field(default_factory=list)
    review_needs_by_owner: list[ReviewNeedsByOwner] = Field(default_factory=list)
    connector_freshness: list[ConnectorFreshness] = Field(default_factory=list)
    generated_at: datetime


class SourceHealthRow(BaseModel):
    source_type: SourceType
    source_id: str
    source_name: str
    connector_name: str | None = None
    collection_id: str | None = None
    collection_name: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    status: str
    last_indexed_at: datetime | None = None
    last_updated_at: datetime | None = None
    freshness: Freshness
    # Raw trust_status (Document only; null for collections). Exposed so the
    # frontend can PATCH .../trust-status with the current value unchanged
    # when it only wants to touch review_owner_id/review_due_date.
    trust_status: str | None = None
    ocr_quality: str | None = None
    review_status: str | None = None
    graph_indexed: str | None = None
    missing_metadata: bool = False
    error_message: str | None = None
    available_actions: list[str] = Field(default_factory=list)


class SourceHealthListResponse(BaseModel):
    rows: list[SourceHealthRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class TableWarningItem(BaseModel):
    chunk_id: str
    page_number: int | None
    confidence: float | None
    reason: str


class SourceHealthErrorDetailResponse(BaseModel):
    source_type: SourceType
    source_id: str
    source_name: str
    status: str
    error_message: str | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    ocr_quality_status: str | None = None
    ocr_avg_confidence: float | None = None
    table_warnings: list[TableWarningItem] = Field(default_factory=list)
