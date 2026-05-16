from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UsageGranularity = Literal["day", "week", "month"]


class UsageSummaryRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class UsageSummaryTotalsResponse(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    event_count: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None


class UsageSummaryPointResponse(BaseModel):
    period_start: date
    period_end: date
    input_tokens: int
    output_tokens: int
    cost_usd: float
    event_count: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None


class UsageSummaryResponse(BaseModel):
    organization_id: str
    range: UsageSummaryRange
    granularity: UsageGranularity
    totals: UsageSummaryTotalsResponse
    series: list[UsageSummaryPointResponse]


class AuditLogListItemResponse(BaseModel):
    audit_log_id: str
    organization_id: str
    user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogListItemResponse]
    total: int
    limit: int
    offset: int
    range: UsageSummaryRange
