from __future__ import annotations

import json
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.domains.admin.services.audit_service import sanitize_metadata
from app.models.enums import OrganizationRole

_ALLOWED_ORG_ROLES = {
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
}


class ToolEffectPolicy(StrEnum):
    read_only = "read_only"
    side_effect = "side_effect"


class ToolSurface(StrEnum):
    api = "api"
    mcp = "mcp"


class ToolErrorCode(StrEnum):
    validation_failed = "validation_failed"
    authorization_failed = "authorization_failed"
    budget_exceeded = "budget_exceeded"
    tool_unavailable = "tool_unavailable"
    internal_error = "internal_error"


class ToolBudget(BaseModel):
    max_calls_per_run: int = Field(default=20, ge=1, le=500)
    max_input_bytes: int = Field(default=32_768, ge=512, le=10_000_000)
    max_output_bytes: int = Field(default=65_536, ge=512, le=10_000_000)
    timeout_ms: int = Field(default=8_000, ge=100, le=300_000)
    max_retry_attempts: int = Field(default=1, ge=0, le=10)


class ToolRedactionPolicy(BaseModel):
    input_keys: list[str] = Field(default_factory=list, max_length=100)
    output_keys: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("input_keys", "output_keys")
    @classmethod
    def validate_keys(cls, value: list[str]) -> list[str]:
        normalized_keys: list[str] = []
        for key in value:
            normalized = key.strip().lower().replace("-", "_")
            if not normalized:
                raise ValueError("redaction keys must not be blank")
            normalized_keys.append(normalized)
        return normalized_keys


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
    description: str = Field(min_length=8, max_length=600)
    capability: str = Field(min_length=3, max_length=120)
    effect_policy: ToolEffectPolicy
    required_roles: list[str] = Field(
        default_factory=lambda: [OrganizationRole.viewer.value],
        max_length=4,
    )
    organization_scoped: bool = True
    approval_required: bool = False
    surfaces: list[ToolSurface] = Field(default_factory=lambda: [ToolSurface.api], max_length=2)
    budget: ToolBudget = Field(default_factory=ToolBudget)
    redaction: ToolRedactionPolicy = Field(default_factory=ToolRedactionPolicy)

    @field_validator("required_roles")
    @classmethod
    def validate_required_roles(cls, value: list[str]) -> list[str]:
        normalized_roles: list[str] = []
        for role in value:
            normalized = role.strip().lower()
            if normalized not in _ALLOWED_ORG_ROLES:
                raise ValueError(f"unsupported role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        if not normalized_roles:
            raise ValueError("required_roles must contain at least one role")
        return normalized_roles

    @field_validator("surfaces")
    @classmethod
    def validate_surfaces(cls, value: list[ToolSurface]) -> list[ToolSurface]:
        if not value:
            raise ValueError("surfaces must not be empty")
        unique = list(dict.fromkeys(value))
        return unique


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(default_factory=lambda: str(uuid4()), min_length=3, max_length=64)
    run_id: str = Field(min_length=3, max_length=64)
    tool_name: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
    organization_id: str = Field(min_length=3, max_length=64)
    user_id: str = Field(min_length=3, max_length=64)
    surface: ToolSurface = ToolSurface.api
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_effect_policy: ToolEffectPolicy | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    approval_id: str | None = Field(default=None, min_length=3, max_length=64)

    @field_validator("run_id", "tool_name", "organization_id", "user_id", "call_id")
    @classmethod
    def trim_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("idempotency_key", "approval_id")
    @classmethod
    def trim_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank")
        return normalized


class ToolError(BaseModel):
    code: ToolErrorCode
    safe_message: str = Field(min_length=1, max_length=400)
    retryable: bool = False
    request_id: str | None = Field(default=None, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: str = Field(min_length=3, max_length=64)
    tool_name: str = Field(min_length=3, max_length=120)
    success: bool
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    latency_ms: int | None = Field(default=None, ge=0, le=1_000_000)


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _apply_explicit_redaction(payload: dict[str, Any], redaction_keys: list[str]) -> dict[str, Any]:
    if not payload:
        return payload
    if not redaction_keys:
        return payload

    redaction_set = {key.strip().lower().replace("-", "_") for key in redaction_keys}
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = key.lower().replace("-", "_")
        if normalized_key in redaction_set:
            sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def redact_tool_payload(
    spec: ToolSpec,
    payload: dict[str, Any] | None,
    *,
    is_output: bool,
) -> dict[str, Any]:
    sanitized = sanitize_metadata(payload)
    if is_output:
        return _apply_explicit_redaction(sanitized, spec.redaction.output_keys)
    return _apply_explicit_redaction(sanitized, spec.redaction.input_keys)


def authorize_tool_call(spec: ToolSpec, call: ToolCall, principal: AuthenticatedPrincipal) -> None:
    if call.tool_name != spec.name:
        raise ValueError("Tool call does not match tool specification")

    if call.requested_effect_policy and call.requested_effect_policy != spec.effect_policy:
        raise ValueError("Requested effect policy does not match tool specification")

    if spec.effect_policy is ToolEffectPolicy.side_effect and call.idempotency_key is None:
        raise ValueError("idempotency_key is required for side-effect tools")
    if spec.approval_required and call.approval_id is None:
        raise ValueError("approval_id is required for this tool")

    principal_roles = {role.strip().lower() for role in principal.roles}
    if principal_roles.isdisjoint(spec.required_roles):
        raise AuthorizationError("Principal role is not authorized for this tool")

    if spec.organization_scoped:
        if principal.organization_id is None:
            raise AuthorizationError("No active organization context for principal")
        if principal.organization_id != call.organization_id:
            raise AuthorizationError("Cross-organization tool access is not allowed")


def validate_tool_call_budget(spec: ToolSpec, call: ToolCall) -> None:
    input_payload = redact_tool_payload(spec, call.arguments, is_output=False)
    payload_size = _payload_size_bytes(input_payload)
    if payload_size > spec.budget.max_input_bytes:
        raise ValueError(
            f"Tool call payload exceeded max_input_bytes budget ({payload_size} > {spec.budget.max_input_bytes})"
        )


def build_tool_success_result(
    spec: ToolSpec,
    call: ToolCall,
    *,
    output: dict[str, Any] | None,
    latency_ms: int | None = None,
) -> ToolResult:
    safe_output = redact_tool_payload(spec, output, is_output=True)
    output_size = _payload_size_bytes(safe_output)
    if output_size > spec.budget.max_output_bytes:
        raise ValueError(
            f"Tool output exceeded max_output_bytes budget ({output_size} > {spec.budget.max_output_bytes})"
        )
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        success=True,
        output=safe_output,
        error=None,
        latency_ms=latency_ms,
    )


def build_safe_tool_error_result(
    call: ToolCall,
    *,
    code: ToolErrorCode,
    safe_message: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    request_id: str | None = None,
    latency_ms: int | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        success=False,
        output=None,
        latency_ms=latency_ms,
        error=ToolError(
            code=code,
            safe_message=safe_message,
            retryable=retryable,
            request_id=request_id,
            details=sanitize_metadata(details),
        ),
    )
