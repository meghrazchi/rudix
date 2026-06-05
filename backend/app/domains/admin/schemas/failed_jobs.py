from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FailedJobStatus = Literal["failed", "retrying", "resolved", "cancelled"]
FailedJobAction = Literal["retry", "cancel", "mark_resolved"]

JOB_TYPE_LABELS: dict[str, str] = {
    "documents.process": "extraction",
    "documents.delete": "deletion_cleanup",
    "documents.reindex": "reindex",
    "evaluations.run": "evaluation",
}


class FailedJobSummary(BaseModel):
    id: UUID
    organization_id: UUID
    task_id: str
    task_name: str
    job_type: str
    status: str
    queue_name: str | None
    error_code: str | None
    attempt_count: int
    is_retryable: bool
    entity_type: str | None
    entity_id: UUID | None
    last_attempted_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FailedJobAuditEntry(BaseModel):
    id: UUID
    action: str
    performed_by_id: UUID | None
    note: str | None
    created_at: datetime


class FailedJobDetail(FailedJobSummary):
    error_message: str | None
    metadata_json: dict = Field(default_factory=dict)
    audit_log: list[FailedJobAuditEntry] = Field(default_factory=list)


class FailedJobsListResponse(BaseModel):
    items: list[FailedJobSummary]
    total: int
    page: int
    page_size: int


class BulkRetryRequest(BaseModel):
    job_ids: list[UUID] = Field(..., min_length=1, max_length=100)


class BulkRetryResponse(BaseModel):
    queued: list[UUID]
    skipped: list[UUID]
    skip_reasons: dict[str, str]
