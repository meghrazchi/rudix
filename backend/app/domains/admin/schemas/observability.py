from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ObservabilityRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class ApiMetrics(BaseModel):
    total_requests: int
    failed_requests: int
    error_rate: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    telemetry_missing: bool


class LlmModelSummary(BaseModel):
    model_name: str
    event_count: int
    error_count: int


class LlmMetrics(BaseModel):
    total_events: int
    failed_events: int
    error_rate: float | None
    avg_latency_ms: float | None
    top_models: list[LlmModelSummary]
    telemetry_missing: bool


class IndexingMetrics(BaseModel):
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    in_progress_jobs: int
    success_rate: float | None
    telemetry_missing: bool


class StorageMetrics(BaseModel):
    total_documents: int
    indexed_documents: int
    failed_documents: int
    pending_documents: int
    total_chunks: int


ObservabilityStatus = Literal["healthy", "degraded", "unknown"]


class ObservabilitySnapshot(BaseModel):
    organization_id: str
    range: ObservabilityRange
    generated_at: datetime
    api_metrics: ApiMetrics
    llm_metrics: LlmMetrics
    indexing_metrics: IndexingMetrics
    storage_metrics: StorageMetrics
