from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectorObservabilityRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class ConnectorErrorSummary(BaseModel):
    code: str
    count: int


class ConnectorProviderHealthSummary(BaseModel):
    provider_key: str
    provider_display_name: str
    connection_count: int
    active_connection_count: int
    sync_job_count: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    running_runs: int
    rate_limited_runs: int
    auth_failed_runs: int
    skipped_items: int
    ingestion_failures: int
    retry_events: int
    token_refresh_failures: int
    citation_usage: int
    connector_documents: int
    connector_files: int
    items_seen: int
    items_upserted: int
    items_deleted: int
    avg_run_latency_ms: float | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    health_status: Literal["healthy", "degraded", "unknown", "disabled"]
    top_error_codes: list[ConnectorErrorSummary] = Field(default_factory=list)


class ConnectorPlatformTotals(BaseModel):
    connection_count: int
    active_connection_count: int
    sync_job_count: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    running_runs: int
    rate_limited_runs: int
    auth_failed_runs: int
    skipped_items: int
    ingestion_failures: int
    retry_events: int
    token_refresh_failures: int
    citation_usage: int
    connector_documents: int
    connector_files: int
    items_seen: int
    items_upserted: int
    items_deleted: int
    avg_run_latency_ms: float | None


ConnectorPlatformStatus = Literal["healthy", "degraded", "unknown", "disabled"]


class ConnectorPlatformHealthResponse(BaseModel):
    organization_id: str
    range: ConnectorObservabilityRange
    generated_at: datetime
    feature_enabled: bool
    rollout_stage: str
    overall_status: ConnectorPlatformStatus
    totals: ConnectorPlatformTotals
    providers: list[ConnectorProviderHealthSummary]
