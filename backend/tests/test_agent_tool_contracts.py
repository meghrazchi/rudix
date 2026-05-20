from __future__ import annotations

import pytest

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.schemas import (
    ToolBudget,
    ToolCall,
    ToolEffectPolicy,
    ToolErrorCode,
    ToolRedactionPolicy,
    ToolSpec,
    ToolSurface,
    authorize_tool_call,
    build_safe_tool_error_result,
    build_tool_success_result,
    validate_tool_call_budget,
)
from app.domains.agents.services import build_default_tool_specs


def _principal(*, role: str, organization_id: str = "org-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        organization_id=organization_id,
        email="user@example.com",
        roles=[role],
        auth_provider="app",
    )


def test_tool_contract_success_and_output_redaction() -> None:
    spec = ToolSpec(
        name="documents.get",
        description="Read a document metadata payload for the caller.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api, ToolSurface.mcp],
        redaction=ToolRedactionPolicy(output_keys=["answer"]),
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="documents.get",
        organization_id="org-1",
        user_id="user-1",
        arguments={"document_id": "doc-1"},
    )
    principal = _principal(role="viewer")

    authorize_tool_call(spec, call, principal)
    validate_tool_call_budget(spec, call)
    result = build_tool_success_result(
        spec,
        call,
        output={"answer": "private", "status": "ok"},
        latency_ms=120,
    )

    assert result.success is True
    assert result.error is None
    assert result.output == {"answer": "***", "status": "ok"}
    assert result.latency_ms == 120


def test_tool_contract_validation_failure_mismatched_tool_name() -> None:
    spec = ToolSpec(
        name="chat.answer",
        description="Run a grounded answer generation query with citations.",
        capability="chat.answer",
        effect_policy=ToolEffectPolicy.side_effect,
        required_roles=["member"],
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="chat.other",
        organization_id="org-1",
        user_id="user-1",
        arguments={"question": "hello"},
        requested_effect_policy=ToolEffectPolicy.side_effect,
        idempotency_key="idem-12345678",
    )
    principal = _principal(role="member")

    with pytest.raises(ValueError, match="does not match tool specification"):
        authorize_tool_call(spec, call, principal)


def test_tool_contract_validation_failure_side_effect_requires_idempotency_key() -> None:
    spec = ToolSpec(
        name="documents.delete",
        description="Delete a document and associated retrieval artifacts.",
        capability="documents.delete",
        effect_policy=ToolEffectPolicy.side_effect,
        required_roles=["admin"],
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="documents.delete",
        organization_id="org-1",
        user_id="user-1",
        arguments={"document_id": "doc-1"},
    )
    principal = _principal(role="admin")

    with pytest.raises(ValueError, match="idempotency_key is required"):
        authorize_tool_call(spec, call, principal)


def test_authorization_failure_cross_organization_isolation() -> None:
    spec = ToolSpec(
        name="documents.get",
        description="Read document detail in the active organization scope.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="documents.get",
        organization_id="org-2",
        user_id="user-1",
        arguments={"document_id": "doc-1"},
    )
    principal = _principal(role="viewer", organization_id="org-1")

    with pytest.raises(AuthorizationError, match="Cross-organization tool access is not allowed"):
        authorize_tool_call(spec, call, principal)


def test_authorization_failure_missing_role() -> None:
    spec = ToolSpec(
        name="evaluations.run",
        description="Queue an evaluation run for a selected evaluation set.",
        capability="evaluations.run",
        effect_policy=ToolEffectPolicy.side_effect,
        required_roles=["admin"],
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="evaluations.run",
        organization_id="org-1",
        user_id="user-1",
        arguments={"evaluation_set_id": "set-1"},
        idempotency_key="idem-12345678",
    )
    principal = _principal(role="viewer")

    with pytest.raises(AuthorizationError, match="not authorized"):
        authorize_tool_call(spec, call, principal)


def test_budget_validation_failure() -> None:
    spec = ToolSpec(
        name="documents.list",
        description="List accessible documents for the active organization.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        budget=ToolBudget(max_input_bytes=512),
    )
    call = ToolCall(
        run_id="run-1",
        tool_name="documents.list",
        organization_id="org-1",
        user_id="user-1",
        arguments={"very_large_argument": "x" * 800},
    )

    with pytest.raises(ValueError, match="max_input_bytes"):
        validate_tool_call_budget(spec, call)


def test_safe_error_result_redacts_sensitive_data() -> None:
    call = ToolCall(
        run_id="run-1",
        tool_name="chat.answer",
        organization_id="org-1",
        user_id="user-1",
        arguments={},
    )

    result = build_safe_tool_error_result(
        call,
        code=ToolErrorCode.internal_error,
        safe_message="Downstream service unavailable",
        request_id="req-123",
        retryable=True,
        details={
            "authorization": "Bearer abc.def.ghi",
            "token": "super-secret-token",
            "prompt": "raw protected document text",
            "nested": {
                "password": "db-password",
                "question": "sensitive question text",
            },
            "note": "token=super-secret-token",
        },
    )

    assert result.success is False
    assert result.output is None
    assert result.error is not None
    assert result.error.code is ToolErrorCode.internal_error
    assert result.error.safe_message == "Downstream service unavailable"
    assert result.error.request_id == "req-123"
    assert result.error.retryable is True
    assert result.error.details["authorization"] == "***"
    assert result.error.details["token"] == "***"
    assert result.error.details["prompt"] == "<redacted:prompt>"
    assert result.error.details["nested"]["password"] == "***"
    assert result.error.details["nested"]["question"] == "<redacted:question>"
    assert result.error.details["note"] == "token=***"


def test_default_registry_separates_mcp_from_side_effect_tools() -> None:
    specs = build_default_tool_specs()
    assert specs

    read_only_with_mcp = [
        spec for spec in specs if spec.effect_policy is ToolEffectPolicy.read_only and ToolSurface.mcp in spec.surfaces
    ]
    side_effect_with_mcp = [
        spec for spec in specs if spec.effect_policy is ToolEffectPolicy.side_effect and ToolSurface.mcp in spec.surfaces
    ]

    assert read_only_with_mcp, "Expected read-only tools to be exposed to MCP"
    assert not side_effect_with_mcp, "Side-effect tools must stay API-only"
