from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AnalyticsEventSurface = Literal["public", "app", "admin"]
AnalyticsFeatureArea = Literal[
    "documents",
    "chat",
    "evaluations",
    "settings",
    "connectors",
    "public",
    "dashboard",
    "admin",
]
AnalyticsSchemaVersion = Literal[1]
AnalyticsEventName = Literal[
    "activation.signup_completed",
    "activation.organization_created",
    "activation.first_upload",
    "activation.first_indexed_document",
    "activation.first_question",
    "activation.first_cited_answer",
    "feature.documents.viewed",
    "feature.documents.uploaded",
    "feature.documents.indexed",
    "feature.dashboard.viewed",
    "feature.chat.viewed",
    "feature.chat.question_submitted",
    "feature.chat.answer_rendered",
    "feature.chat.citation_opened",
    "feature.chat.retrieval_diagnostics_viewed",
    "feature.evaluations.viewed",
    "feature.settings.viewed",
    "feature.connectors.viewed",
    "feature.public_page.viewed",
]

ACTIVATION_EVENT_NAMES = (
    "activation.signup_completed",
    "activation.organization_created",
    "activation.first_upload",
    "activation.first_indexed_document",
    "activation.first_question",
    "activation.first_cited_answer",
)


class AnalyticsDateRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class AnalyticsEventIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: AnalyticsEventName
    schema_version: AnalyticsSchemaVersion = 1
    surface: AnalyticsEventSurface
    route: str | None = Field(default=None, max_length=255)
    page_key: str | None = Field(default=None, max_length=128)
    feature_area: AnalyticsFeatureArea | None = None
    entity_id: str | None = Field(default=None, max_length=128)
    entity_type: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=64)
    method: str | None = Field(default=None, max_length=32)
    count: int | None = Field(default=None, ge=0, le=100_000)
    citation_count: int | None = Field(default=None, ge=0, le=100_000)
    has_citations: bool | None = None
    locale: str | None = Field(default=None, max_length=16)
    source: str | None = Field(default=None, max_length=64)
    dedupe_key: str | None = Field(default=None, max_length=128)

    @field_validator(
        "route", "page_key", "entity_id", "entity_type", "status", "method", "source", "locale"
    )
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class AnalyticsEventIngestResponse(BaseModel):
    accepted: bool
    deduped: bool = False
    enabled: bool = True
    event_name: AnalyticsEventName
    schema_version: AnalyticsSchemaVersion = 1


class AnalyticsActivationSummaryResponse(BaseModel):
    signup_completed: int
    organization_created: int
    first_upload: int
    first_indexed_document: int
    first_question: int
    first_cited_answer: int
    funnel_completion_rate: float | None = None


class AnalyticsSummaryResponse(BaseModel):
    organization_id: str
    range: AnalyticsDateRange
    generated_at: datetime
    enabled: bool
    disabled_reason: str | None = None
    total_events: int
    active_users: int
    activation: AnalyticsActivationSummaryResponse
    feature_usage: dict[str, int] = Field(default_factory=dict)
    page_usage: dict[str, int] = Field(default_factory=dict)
    event_counts: dict[str, int] = Field(default_factory=dict)
