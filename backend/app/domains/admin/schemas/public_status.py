from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PublicComponentState = Literal[
    "operational",
    "degraded",
    "outage",
    "maintenance",
    "unknown",
]


class PublicStatusComponent(BaseModel):
    key: str
    label: str
    status: PublicComponentState
    summary: str
    affected_services: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class PublicStatusIncident(BaseModel):
    title: str
    status: str
    severity: str
    kind: Literal["incident", "maintenance"]
    affected_services: list[str] = Field(default_factory=list)
    message: str | None
    started_at: datetime
    resolved_at: datetime | None


class PublicStatusSnapshot(BaseModel):
    generated_at: datetime
    overall_status: PublicComponentState
    headline: str
    summary: str
    components: list[PublicStatusComponent]
    current_incidents: list[PublicStatusIncident]
    scheduled_maintenance: list[PublicStatusIncident]
    recent_history: list[PublicStatusIncident]
    uptime_notice: str
