from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class QuotaType(StrEnum):
    uploads = "uploads"
    questions = "questions"
    tokens = "tokens"
    storage_bytes = "storage_bytes"
    evaluations = "evaluations"
    api_calls = "api_calls"
    connectors = "connectors"
    agent_runs = "agent_runs"


class ResetWindow(StrEnum):
    per_minute = "per_minute"
    per_hour = "per_hour"
    per_day = "per_day"
    per_month = "per_month"
    none = "none"  # permanent cap — never resets


# ---------------------------------------------------------------------------
# Policy request / response
# ---------------------------------------------------------------------------


class QuotaLimitConfig(BaseModel):
    """Limit configuration for one quota type."""

    soft_limit: int | None = Field(default=None, ge=0)
    hard_limit: int | None = Field(default=None, ge=0)
    reset_window: ResetWindow = ResetWindow.per_day

    def model_post_init(self, __context: object) -> None:
        if (
            self.soft_limit is not None
            and self.hard_limit is not None
            and self.soft_limit > self.hard_limit
        ):
            raise ValueError("soft_limit must be less than or equal to hard_limit")


class UpdateOrgQuotaPolicyRequest(BaseModel):
    """All fields are optional; only supplied quota types are updated."""

    uploads: QuotaLimitConfig | None = None
    questions: QuotaLimitConfig | None = None
    tokens: QuotaLimitConfig | None = None
    storage_bytes: QuotaLimitConfig | None = None
    evaluations: QuotaLimitConfig | None = None
    api_calls: QuotaLimitConfig | None = None
    connectors: QuotaLimitConfig | None = None
    agent_runs: QuotaLimitConfig | None = None
    change_note: str | None = Field(default=None, max_length=1000)


class OrgQuotaPolicyResponse(BaseModel):
    organization_id: str
    limits: dict
    version: int
    updated_by_id: str | None = None
    updated_at: datetime


# ---------------------------------------------------------------------------
# Usage dashboard
# ---------------------------------------------------------------------------


class QuotaUsageItem(BaseModel):
    quota_type: str
    current_value: int
    soft_limit: int | None
    hard_limit: int | None
    reset_window: str
    next_reset_at: datetime | None
    near_limit: bool
    over_soft_limit: bool
    over_hard_limit: bool


class OrgQuotaDashboardResponse(BaseModel):
    organization_id: str
    policy_version: int
    quota_usage: list[QuotaUsageItem]
    has_overages: bool
    checked_at: datetime


# ---------------------------------------------------------------------------
# Override
# ---------------------------------------------------------------------------


class CreateQuotaOverrideRequest(BaseModel):
    quota_type: str = Field(max_length=64)
    target_user_id: str | None = None
    hard_limit_override: int | None = Field(default=None, ge=0)
    reason: str = Field(max_length=1000, min_length=1)
    expires_at: datetime | None = None


class QuotaOverrideResponse(BaseModel):
    override_id: str
    organization_id: str
    quota_type: str
    target_user_id: str | None
    hard_limit_override: int | None
    reason: str
    created_by_id: str | None
    expires_at: datetime | None
    created_at: datetime


class QuotaOverrideListResponse(BaseModel):
    items: list[QuotaOverrideResponse]
    total: int


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------


class QuotaChangeLogEntryResponse(BaseModel):
    entry_id: str
    organization_id: str
    version_number: int
    policy_snapshot: dict
    change_note: str | None = None
    changed_by_id: str | None = None
    created_at: datetime


class QuotaChangeLogResponse(BaseModel):
    items: list[QuotaChangeLogEntryResponse]
    total: int


# ---------------------------------------------------------------------------
# Quota check (internal)
# ---------------------------------------------------------------------------


class QuotaCheckResult(BaseModel):
    allowed: bool
    near_limit: bool
    over_soft_limit: bool
    over_hard_limit: bool
    current_value: int
    effective_hard_limit: int | None
    effective_soft_limit: int | None
