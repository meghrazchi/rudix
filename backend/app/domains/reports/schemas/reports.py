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
