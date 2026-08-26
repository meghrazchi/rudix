"""Pydantic schemas for the admin usage & adoption report API (F353).

Returned by GET /admin/usage-adoption/*. Aggregates existing usage-event,
chat, citation, feedback, verified-answer, share, and invitation signals
already tracked across prior features into adoption metrics, an activation
funnel, charts, and a per-user table. No new persisted fields are
introduced by this feature.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

OnboardingStatus = str  # "not_started" | "in_progress" | "completed"


class UsageAdoptionSummaryResponse(BaseModel):
    """Org-scoped counters for the top-of-dashboard metric cards."""

    active_users: int = 0
    new_users: int = 0
    returning_users: int = 0
    questions_asked: int = 0
    documents_uploaded: int = 0
    collections_used: int = 0
    connectors_used: int = 0
    citation_clicks: int = 0
    trust_panel_opens: int = 0
    feedback_submitted: int = 0
    saved_answers: int = 0
    onboarding_completion_rate: float | None = None
    invitations_sent: int = 0
    invitations_accepted: int = 0
    generated_at: datetime


class ActivationFunnelStepResponse(BaseModel):
    step: str
    label: str
    users_reached: int
    drop_off_rate: float | None = None


class ActiveUsersPoint(BaseModel):
    date: str
    active_users: int


class QuestionsPerUserBucket(BaseModel):
    bucket: str
    user_count: int


class RoleAdoptionRow(BaseModel):
    role: str
    user_count: int
    active_users: int
    questions_asked: int
    activation_rate: float | None = None


class UsageAdoptionChartsResponse(BaseModel):
    active_users_series: list[ActiveUsersPoint] = Field(default_factory=list)
    questions_per_user: list[QuestionsPerUserBucket] = Field(default_factory=list)
    feature_usage: dict[str, int] = Field(default_factory=dict)
    funnel: list[ActivationFunnelStepResponse] = Field(default_factory=list)
    role_adoption_comparison: list[RoleAdoptionRow] = Field(default_factory=list)
    drop_off_points: list[ActivationFunnelStepResponse] = Field(default_factory=list)
    generated_at: datetime


class UsageAdoptionUserRow(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    last_active_at: datetime | None = None
    questions_asked: int = 0
    sources_used: int = 0
    citation_clicks: int = 0
    feedback_submitted: int = 0
    saved_answers: int = 0
    onboarding_status: OnboardingStatus = "not_started"


class UsageAdoptionUserListResponse(BaseModel):
    rows: list[UsageAdoptionUserRow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25


class OnboardingReminderResponse(BaseModel):
    sent: bool
