from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

IncidentStatus = Literal["investigating", "identified", "monitoring", "resolved"]
IncidentSeverity = Literal["critical", "high", "medium", "low"]

_ACTIVE_STATUSES = frozenset({"investigating", "identified", "monitoring"})


class IncidentNoteEntry(BaseModel):
    id: UUID
    note: str
    status_change: str | None
    created_by_id: UUID | None
    created_at: datetime


class IncidentSummary(BaseModel):
    id: UUID
    organization_id: UUID
    title: str
    status: str
    severity: str
    affected_services: list[str]
    message: str | None
    is_public: bool
    started_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentSummary):
    notes: list[IncidentNoteEntry] = Field(default_factory=list)


class IncidentsListResponse(BaseModel):
    items: list[IncidentSummary]
    total: int
    page: int
    page_size: int


class CreateIncidentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    severity: IncidentSeverity = "medium"
    affected_services: list[str] = Field(default_factory=list, max_length=20)
    message: str | None = Field(None, max_length=5000)
    is_public: bool = False
    started_at: datetime | None = None


class UpdateIncidentRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    status: IncidentStatus | None = None
    severity: IncidentSeverity | None = None
    affected_services: list[str] | None = None
    message: str | None = None
    is_public: bool | None = None
    resolved_at: datetime | None = None


class AddIncidentNoteRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=5000)
    status_change: IncidentStatus | None = None


class ServiceStatusBanner(BaseModel):
    has_active_incident: bool
    has_active_maintenance: bool
    active_incident_count: int
    banner_message: str | None
    highest_severity: str | None


class ServiceStatusSnapshot(BaseModel):
    organization_id: UUID
    generated_at: datetime
    active_incidents: list[IncidentSummary]
    recently_resolved: list[IncidentSummary]
    open_failed_job_count: int
    banner: ServiceStatusBanner
