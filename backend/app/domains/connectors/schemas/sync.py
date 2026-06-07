"""Request/response Pydantic schemas for the connector sync API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateSyncJobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    external_source_id: str | None = None
    collection_id: str | None = None
    schedule: dict[str, Any] = Field(
        default_factory=lambda: {"type": "interval", "interval_minutes": 60}
    )


class SyncScheduleResponse(BaseModel):
    type: str
    interval_minutes: int | None = None


class SyncJobResponse(BaseModel):
    id: str
    organization_id: str
    connection_id: str
    external_source_id: str | None
    collection_id: str | None
    name: str
    status: str
    schedule: dict[str, Any]
    last_run_at: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class SyncRunResponse(BaseModel):
    id: str
    organization_id: str
    sync_job_id: str
    connection_id: str
    external_source_id: str | None
    status: str
    trigger_type: str
    sync_version: int
    started_at: str | None
    completed_at: str | None
    items_seen: int
    items_upserted: int
    items_deleted: int
    cursor_before: dict[str, Any]
    cursor_after: dict[str, Any]
    error_message: str | None
    error_details: dict[str, Any]
    created_at: str
    updated_at: str


class TriggerSyncNowResponse(BaseModel):
    sync_run_id: str
    status: str
    message: str


class SyncRunsListResponse(BaseModel):
    items: list[SyncRunResponse]
    total: int


class SyncJobsListResponse(BaseModel):
    items: list[SyncJobResponse]
    total: int


class UpdateSyncJobStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|paused|disabled)$")
