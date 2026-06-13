from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class SloSuggestion(BaseModel):
    metric: str
    current_value: float
    suggested_threshold: float
    unit: str
    rationale: str


class ProviderHealthCard(BaseModel):
    provider_key: str
    total_events: int
    failed_events: int
    failure_rate: float | None
    timed_out_events: int
    timeout_rate: float | None
    fallback_events: int
    fallback_rate: float | None
    retry_events: int
    retry_rate: float | None
    avg_retry_count: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    slo_suggestions: list[SloSuggestion] = Field(default_factory=list)
    telemetry_missing: bool


class ProviderObservabilityRange(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")

    model_config = {"populate_by_name": True}


class ProviderObservabilitySnapshot(BaseModel):
    organization_id: str
    range: ProviderObservabilityRange
    generated_at: datetime
    providers: list[ProviderHealthCard]
    telemetry_missing: bool
