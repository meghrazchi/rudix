from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agents.repositories import AgentRunRepository
from app.models import Organization, User
from app.models.enums import (
    AgentApprovalStatus,
    AgentRunStatus,
    AgentStepStatus,
    AgentToolCallStatus,
)


@pytest.fixture
def agent_run_repository() -> AgentRunRepository:
    return AgentRunRepository()


@pytest_asyncio.fixture
async def organizations_and_users(db_session: AsyncSession) -> tuple[UUID, UUID, UUID, UUID]:
    organization_a = Organization(name="Agent Org A", slug="agent-org-a")
    organization_b = Organization(name="Agent Org B", slug="agent-org-b")
    db_session.add_all([organization_a, organization_b])
    await db_session.flush()

    user_a = User(
        organization_id=organization_a.id,
        external_auth_id="agent-user-a",
        email="agent-user-a@example.com",
    )
    user_b = User(
        organization_id=organization_b.id,
        external_auth_id="agent-user-b",
        email="agent-user-b@example.com",
    )
    db_session.add_all([user_a, user_b])
    await db_session.flush()
    return organization_a.id, user_a.id, organization_b.id, user_b.id


@pytest.mark.asyncio
async def test_agent_run_repository_persists_sanitized_trace_records(
    db_session: AsyncSession,
    agent_run_repository: AgentRunRepository,
    organizations_and_users: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_id, user_id, _, _ = organizations_and_users
    run = await agent_run_repository.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        status=AgentRunStatus.running.value,
        budget={"token": "secret", "max_steps": 12},
        outcome={"answer": "Top secret answer"},
        observations={"document_text": "sensitive body"},
        error_details={"authorization": "Bearer very-secret-token"},
    )

    assert run.budget_json["token"] == "***"
    assert run.outcome_json["answer"] == "<redacted:answer>"
    assert run.observations_json["document_text"] == "<redacted:document_text>"
    assert run.error_details_json["authorization"] == "***"

    step = await agent_run_repository.create_agent_step(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
        user_id=user_id,
        sequence=0,
        step_name="retrieve",
        status=AgentStepStatus.running.value,
        inputs={"question": "show all customer data"},
        outputs={"notes": "token=abc123"},
        observation={"content": "raw chunk text"},
    )
    assert step.inputs_json["question"] == "<redacted:question>"
    assert step.outputs_json["notes"] == "token=***"
    assert step.observation_json["content"] == "<redacted:content>"

    tool_call = await agent_run_repository.create_agent_tool_call(
        db_session,
        agent_run_id=run.id,
        agent_step_id=step.id,
        organization_id=organization_id,
        user_id=user_id,
        tool_name="documents.get",
        surface="api",
        effect_policy="read_only",
        status=AgentToolCallStatus.succeeded.value,
        idempotency_key="unsafe-plain-key",
        arguments={"authorization": "Bearer xyz", "question": "sensitive"},
        output={"answer": "sensitive answer"},
        error={"api_key": "x"},
    )
    assert tool_call.arguments_json["authorization"] == "***"
    assert tool_call.arguments_json["question"] == "<redacted:question>"
    assert tool_call.output_json["answer"] == "<redacted:answer>"
    assert tool_call.error_json["api_key"] == "***"
    assert tool_call.idempotency_key_hash is not None
    assert tool_call.idempotency_key_hash != "unsafe-plain-key"
    assert len(tool_call.idempotency_key_hash) == 64

    approval = await agent_run_repository.create_agent_approval(
        db_session,
        organization_id=organization_id,
        agent_run_id=run.id,
        agent_step_id=step.id,
        tool_call_id=tool_call.id,
        requested_by_user_id=user_id,
        status=AgentApprovalStatus.pending.value,
        request_payload={"prompt": "raw internal prompt"},
    )
    assert approval.request_payload_json["prompt"] == "<redacted:prompt>"


@pytest.mark.asyncio
async def test_agent_run_repository_enforces_organization_scoped_reads(
    db_session: AsyncSession,
    agent_run_repository: AgentRunRepository,
    organizations_and_users: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_a, user_a, organization_b, _ = organizations_and_users
    run = await agent_run_repository.create_agent_run(
        db_session,
        organization_id=organization_a,
        user_id=user_a,
        status=AgentRunStatus.completed.value,
    )
    found_same_org = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_a,
    )
    found_other_org = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_b,
    )
    assert found_same_org is not None
    assert found_other_org is None

    calls = await agent_run_repository.list_agent_runs(
        db_session,
        organization_id=organization_b,
        limit=10,
        offset=0,
    )
    assert calls == []


@pytest.mark.asyncio
async def test_agent_run_repository_validation_failures(
    db_session: AsyncSession,
    agent_run_repository: AgentRunRepository,
    organizations_and_users: tuple[UUID, UUID, UUID, UUID],
) -> None:
    organization_id, user_id, _, _ = organizations_and_users

    with pytest.raises(ValueError, match="Unsupported agent run status"):
        await agent_run_repository.create_agent_run(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            status="invalid-status",
        )

    run = await agent_run_repository.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )

    with pytest.raises(ValueError, match="Unsupported agent tool call effect_policy"):
        await agent_run_repository.create_agent_tool_call(
            db_session,
            agent_run_id=run.id,
            organization_id=organization_id,
            user_id=user_id,
            tool_name="documents.get",
            surface="api",
            effect_policy="unsafe",
            status=AgentToolCallStatus.queued.value,
        )

    with pytest.raises(ValueError, match="Unsupported agent approval status"):
        await agent_run_repository.create_agent_approval(
            db_session,
            organization_id=organization_id,
            agent_run_id=run.id,
            status="unexpected",
        )
