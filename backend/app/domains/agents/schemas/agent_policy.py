from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import OrganizationRole

_ALLOWED_ROLES = {role.value for role in OrganizationRole}


class ToolPolicyOverrideState(BaseModel):
    """Effective per-tool policy as resolved from spec defaults + org overrides."""

    tool_name: str
    enabled: bool
    approval_required: bool
    required_roles: list[str]
    max_calls_per_run: int
    max_input_bytes: int
    max_output_bytes: int
    timeout_ms: int
    max_retry_attempts: int
    # True when this row was explicitly set by an admin (vs. inherited from spec defaults)
    is_overridden: bool


class OrgToolPolicyOverride(BaseModel):
    """Admin-editable settings for a single tool within an organization."""

    tool_name: str
    enabled: bool = True
    approval_required: bool | None = None
    required_roles: list[str] | None = Field(default=None, max_length=8)
    max_calls_per_run: int | None = Field(default=None, ge=1, le=500)
    max_input_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    max_output_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    timeout_ms: int | None = Field(default=None, ge=100, le=300_000)
    max_retry_attempts: int | None = Field(default=None, ge=0, le=10)
    updated_at: datetime | None = None
    updated_by_user_id: str | None = None

    @field_validator("required_roles")
    @classmethod
    def validate_required_roles(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for role in value:
            r = role.strip().lower()
            if r not in _ALLOWED_ROLES:
                raise ValueError(f"unsupported role: {role}")
            if r not in normalized:
                normalized.append(r)
        if not normalized:
            raise ValueError("required_roles must not be empty")
        return normalized


class AgentPolicyResponse(BaseModel):
    """Full policy response returned from GET /admin/agent-policy."""

    organization_id: str
    org_budget: OrgBudgetPolicySummary
    tool_overrides: list[OrgToolPolicyOverride]
    resolved_tools: list[ToolPolicyOverrideState]
    policy_updated_at: datetime | None = None


class OrgBudgetPolicySummary(BaseModel):
    """Budget limits enforced at org level (subset of GovernanceBudgetConfig)."""

    max_steps: int | None = None
    max_tool_calls_per_run: int | None = None
    max_tool_timeout_ms: int | None = None
    max_tool_input_bytes: int | None = None
    max_tool_output_bytes: int | None = None
    max_tool_retry_attempts: int | None = None
    max_total_tokens: int | None = None
    max_total_cost_usd: float | None = None


# Re-declare after OrgBudgetPolicySummary is defined so AgentPolicyResponse forward ref resolves.
AgentPolicyResponse.model_rebuild()


class ToolPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = True
    approval_required: bool | None = None
    required_roles: list[str] | None = Field(default=None, max_length=8)
    max_calls_per_run: int | None = Field(default=None, ge=1, le=500)
    max_input_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    max_output_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    timeout_ms: int | None = Field(default=None, ge=100, le=300_000)
    max_retry_attempts: int | None = Field(default=None, ge=0, le=10)

    @field_validator("required_roles")
    @classmethod
    def validate_required_roles(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for role in value:
            r = role.strip().lower()
            if r not in _ALLOWED_ROLES:
                raise ValueError(f"unsupported role: {role}")
            if r not in normalized:
                normalized.append(r)
        if not normalized:
            raise ValueError("required_roles must not be empty")
        return normalized


class ToolPolicyUpsertResponse(BaseModel):
    organization_id: str
    override: OrgToolPolicyOverride
    audit_recorded: bool


class EffectivePolicyResponse(BaseModel):
    """Effective policy snapshot attached to an agent run."""

    run_id: str
    organization_id: str
    snapshot: dict[str, Any] | None = None
    resolved_tools: list[ToolPolicyOverrideState] = Field(default_factory=list)
    org_budget: OrgBudgetPolicySummary | None = None
    snapshot_recorded_at: datetime | None = None
