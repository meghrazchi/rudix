from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import (
    ToolBudget,
    ToolCall,
    ToolEffectPolicy,
    ToolRedactionPolicy,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services import AgentToolExecutor, ToolRegistry
from app.models import AuditLog, Organization, User
from app.models.enums import AgentApprovalStatus, AgentRunStatus


def _principal(*, user_id: UUID, organization_id: UUID, role: str = "viewer") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(user_id),
        organization_id=str(organization_id),
        email="agent@example.com",
        roles=[role],
        auth_provider="app",
    )


@pytest_asyncio.fixture
async def org_user_ids(db_session: AsyncSession) -> tuple[UUID, UUID, UUID, UUID]:
    organization_a = Organization(name="Exec Org A", slug="exec-org-a")
    organization_b = Organization(name="Exec Org B", slug="exec-org-b")
    db_session.add_all([organization_a, organization_b])
    await db_session.flush()

    user_a = User(
        organization_id=organization_a.id,
        external_auth_id="exec-user-a",
        email="exec-a@example.com",
    )
    user_b = User(
        organization_id=organization_b.id,
        external_auth_id="exec-user-b",
        email="exec-b@example.com",
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()
    return organization_a.id, user_a.id, organization_b.id, user_b.id


@pytest.mark.asyncio
async def test_agent_tool_executor_success_persists_and_audits(
    db_session: AsyncSession,
    org_user_ids: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_id, user_id, _, _ = org_user_ids
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        status=AgentRunStatus.running.value,
    )

    async def _handler(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del call, principal
        return {"answer": "private answer", "status": "ok"}

    spec = ToolSpec(
        name="documents.get",
        description="Read one document with organization-scoped authorization.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api],
        budget=ToolBudget(max_calls_per_run=2, timeout_ms=500),
        redaction=ToolRedactionPolicy(output_keys=["answer"]),
    )
    registry = ToolRegistry()
    registry.register_tool(spec=spec, handler=_handler)
    executor = AgentToolExecutor(registry=registry, repository=repository)

    call = ToolCall(
        run_id=str(run.id),
        tool_name="documents.get",
        organization_id=str(organization_id),
        user_id=str(user_id),
        arguments={"document_id": "doc-1", "authorization": "Bearer secret"},
    )
    result = await executor.execute(
        session=db_session,
        call=call,
        principal=_principal(user_id=user_id, organization_id=organization_id),
        request_id="req-1",
    )

    assert result.success is True
    assert result.output == {"answer": "***", "status": "ok"}
    persisted_calls = await repository.list_agent_tool_calls(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
    )
    assert len(persisted_calls) == 1
    assert persisted_calls[0].status == "succeeded"
    assert persisted_calls[0].arguments_json["authorization"] == "***"

    audit_logs = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == organization_id,
                AuditLog.action.in_(("agent.tool_call.started", "agent.tool_call.succeeded")),
            )
        )
    ).scalars().all()
    assert len(audit_logs) >= 2


@pytest.mark.asyncio
async def test_agent_tool_executor_validation_and_auth_failures(
    db_session: AsyncSession,
    org_user_ids: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a, user_a, organization_b, _ = org_user_ids
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=organization_a,
        user_id=user_a,
        status=AgentRunStatus.running.value,
    )

    async def _handler(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del call, principal
        return {"ok": True}

    spec = ToolSpec(
        name="documents.delete",
        description="Delete a document in the current organization scope.",
        capability="documents.delete",
        effect_policy=ToolEffectPolicy.side_effect,
        required_roles=["admin"],
        approval_required=True,
        surfaces=[ToolSurface.api],
        budget=ToolBudget(max_calls_per_run=1, timeout_ms=500),
    )
    registry = ToolRegistry()
    registry.register_tool(spec=spec, handler=_handler)
    executor = AgentToolExecutor(registry=registry, repository=repository)

    missing_approval_call = ToolCall(
        run_id=str(run.id),
        tool_name="documents.delete",
        organization_id=str(organization_a),
        user_id=str(user_a),
        idempotency_key="idem-12345678",
        arguments={"document_id": "doc-1"},
    )
    missing_approval_result = await executor.execute(
        session=db_session,
        call=missing_approval_call,
        principal=_principal(user_id=user_a, organization_id=organization_a, role="admin"),
    )
    assert missing_approval_result.success is False
    assert missing_approval_result.error is not None
    assert missing_approval_result.error.code.value == "approval_required"
    assert missing_approval_result.error.details.get("approval_id")
    pending_approvals = await repository.list_agent_approvals(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_a,
    )
    assert len(pending_approvals) == 1
    assert pending_approvals[0].status == AgentApprovalStatus.pending.value

    approval = await repository.create_agent_approval(
        db_session,
        organization_id=organization_a,
        agent_run_id=run.id,
        status=AgentApprovalStatus.approved.value,
        requested_by_user_id=user_a,
    )
    cross_org_call = ToolCall(
        run_id=str(run.id),
        tool_name="documents.delete",
        organization_id=str(organization_a),
        user_id=str(user_a),
        idempotency_key="idem-12345679",
        approval_id=str(approval.id),
        arguments={"document_id": "doc-1"},
    )
    cross_org_result = await executor.execute(
        session=db_session,
        call=cross_org_call,
        principal=_principal(user_id=user_a, organization_id=organization_b, role="admin"),
    )
    assert cross_org_result.success is False
    assert cross_org_result.error is not None
    assert cross_org_result.error.code.value == "authorization_failed"


@pytest.mark.asyncio
async def test_agent_tool_executor_budget_timeout_and_safe_error(
    db_session: AsyncSession,
    org_user_ids: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_id, user_id, _, _ = org_user_ids
    repository = AgentRunRepository()
    run = await repository.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        status=AgentRunStatus.running.value,
    )

    async def _slow_handler(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del call, principal
        await asyncio.sleep(0.2)
        return {"status": "late"}

    async def _failing_handler(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del call, principal
        raise RuntimeError("token=secret-value")

    timeout_spec = ToolSpec(
        name="pipeline.runs.get",
        description="Read pipeline runs for diagnostics and observability.",
        capability="pipeline.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api],
        budget=ToolBudget(max_calls_per_run=1, timeout_ms=100),
    )
    failure_spec = ToolSpec(
        name="documents.list",
        description="List organization documents visible to the principal.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api],
        budget=ToolBudget(max_calls_per_run=2, timeout_ms=500),
    )
    registry = ToolRegistry()
    registry.register_tool(spec=timeout_spec, handler=_slow_handler)
    registry.register_tool(spec=failure_spec, handler=_failing_handler)
    executor = AgentToolExecutor(registry=registry, repository=repository)

    timeout_call = ToolCall(
        run_id=str(run.id),
        tool_name="pipeline.runs.get",
        organization_id=str(organization_id),
        user_id=str(user_id),
        arguments={},
    )
    timeout_result = await executor.execute(
        session=db_session,
        call=timeout_call,
        principal=_principal(user_id=user_id, organization_id=organization_id),
    )
    assert timeout_result.success is False
    assert timeout_result.error is not None
    assert timeout_result.error.code.value == "tool_unavailable"

    budget_call = ToolCall(
        run_id=str(run.id),
        tool_name="pipeline.runs.get",
        organization_id=str(organization_id),
        user_id=str(user_id),
        arguments={},
    )
    budget_result = await executor.execute(
        session=db_session,
        call=budget_call,
        principal=_principal(user_id=user_id, organization_id=organization_id),
    )
    assert budget_result.success is False
    assert budget_result.error is not None
    assert budget_result.error.code.value == "budget_exceeded"

    fail_call = ToolCall(
        run_id=str(run.id),
        tool_name="documents.list",
        organization_id=str(organization_id),
        user_id=str(user_id),
        arguments={},
    )
    fail_result = await executor.execute(
        session=db_session,
        call=fail_call,
        principal=_principal(user_id=user_id, organization_id=organization_id),
    )
    assert fail_result.success is False
    assert fail_result.error is not None
    assert fail_result.error.code.value == "internal_error"
    assert fail_result.error.details["error"] == "RuntimeError"
