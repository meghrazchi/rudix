"""``POST /agent/runs`` and the approval decision in worker mode (R06-13).

The request returns ``201`` with ``status: queued`` at once; the outbox publication after
the commit runs ``agents.run.execute`` eagerly (in a thread, like the broker hand-off), so
the run is complete when the test reads it back.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_worker_support import (
    AgentWorkerEnv,
    add_user,
    agent_env,  # noqa: F401  (fixture)
    api_client,
    build_runtime,
    headers_for,
)
from redis_fakes import FakeRedis
from sqlalchemy import select

from app.application import outbox
from app.models.agent import AgentApproval, AgentRun
from app.models.enums import OrganizationRole
from app.models.usage import UsageEvent
from app.workers import async_runtime

BODY = {
    "agentic_mode": True,
    "request": {"objective": "Answer the policy question", "mode": "answer"},
}


@pytest.fixture(autouse=True)
def _fresh_worker_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The eager task runs in a thread; give it its own event loop.
    monkeypatch.setattr(async_runtime, "_worker_loop", None)


async def _rows(env: AgentWorkerEnv, statement: Any) -> list[Any]:
    async with env.factory() as session:
        return list((await session.execute(statement)).scalars().all())


@pytest.mark.asyncio
async def test_worker_mode_returns_queued_and_the_task_completes_the_run(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    redis = FakeRedis()
    agent_env.redis = redis
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.post("/api/v1/agent/runs", headers=headers, json=BODY)
        assert response.status_code == 201
        run_payload = response.json()["run"]
        assert run_payload["status"] == "queued"
        assert run_payload["steps_executed"] == 0 and run_payload["outcome"] is None
        detail = await client.get(f"/api/v1/agent/runs/{run_payload['run_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert agent_env.tools.calls == {"search": 1, "answer": 1}
    runs = await _rows(agent_env, select(AgentRun))
    assert len(runs) == 1 and runs[0].lease_owner is None
    rows = await agent_env.aoutbox(seeded.organization_id)
    assert [(row.task_name, row.status) for row in rows] == [("agents.run.execute", "published")]
    assert rows[0].dedupe_key == f"agents.run.execute:{run_payload['run_id']}"
    quota = await _rows(
        agent_env,
        select(UsageEvent).where(UsageEvent.organization_id == seeded.organization_id),
    )
    assert any(event.event_type == "agent.runtime" for event in quota)
    events = [entry for key, entry in redis.keyspace.lists.items() if key.endswith(":events")]
    assert events and '"agent.run.status"' in events[0][0]


@pytest.mark.asyncio
async def test_publish_failure_leaves_the_row_for_the_relay(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = await agent_env.aseed()

    class _Down:
        def delay(self, **_: Any) -> None:
            raise ConnectionError("broker down")

    monkeypatch.setattr(outbox, "resolve_task", lambda name: _Down())
    async with api_client(agent_env) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.post("/api/v1/agent/runs", headers=headers, json=BODY)
    assert response.status_code == 201 and response.json()["run"]["status"] == "queued"
    rows = await agent_env.aoutbox(seeded.organization_id)
    assert [(row.task_name, row.status) for row in rows] == [("agents.run.execute", "pending")]


@pytest.mark.asyncio
async def test_approval_resumes_the_run_in_a_worker(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    agent_env.use_runtime(build_runtime(agent_env.tools, side_effect=True, approval=True))
    seeded = await agent_env.aseed()
    admin_id, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.admin)
    async with api_client(agent_env) as client:
        member = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        admin = await headers_for(agent_env, admin_id, seeded.organization_id)
        created = await client.post("/api/v1/agent/runs", headers=member, json=BODY)
        run_id = created.json()["run"]["run_id"]
        waiting = await client.get(f"/api/v1/agent/runs/{run_id}", headers=member)
        assert waiting.json()["status"] == "waiting_approval"
        approval_id = waiting.json()["approvals"][0]["approval_id"]
        assert agent_env.tools.calls == {"search": 1, "answer": 0}

        decided = await client.post(
            f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
            headers=admin,
            json={"status": "approved", "reason": "ok"},
        )
        assert decided.status_code == 200
        done = await client.get(f"/api/v1/agent/runs/{run_id}", headers=member)
    assert done.json()["status"] == "completed"
    assert agent_env.tools.calls == {"search": 1, "answer": 1}
    tasks = [
        (row.task_name, row.status) for row in (await agent_env.aoutbox(seeded.organization_id))
    ]
    assert tasks == [("agents.run.execute", "published"), ("agents.run.resume", "published")]
    assert (await agent_env.aoutbox(seeded.organization_id))[1].dedupe_key == (
        f"agents.run.resume:{approval_id}"
    )


@pytest.mark.asyncio
async def test_rejected_approval_keeps_todays_behaviour(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    agent_env.use_runtime(build_runtime(agent_env.tools, side_effect=True, approval=True))
    seeded = await agent_env.aseed()
    admin_id, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.admin)
    async with api_client(agent_env) as client:
        member = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        admin = await headers_for(agent_env, admin_id, seeded.organization_id)
        created = await client.post("/api/v1/agent/runs", headers=member, json=BODY)
        run_id = created.json()["run"]["run_id"]
        approvals = await _rows(agent_env, select(AgentApproval))
        decided = await client.post(
            f"/api/v1/agent/runs/{run_id}/approvals/{approvals[0].id}/decision",
            headers=admin,
            json={"status": "rejected", "reason": "no"},
        )
        assert decided.status_code == 200
        run = await client.get(f"/api/v1/agent/runs/{run_id}", headers=member)
    assert run.json()["status"] == "failed"
    assert run.json()["error_message"] == "Approval rejected: no"
    tasks = [row.task_name for row in (await agent_env.aoutbox(seeded.organization_id))]
    assert tasks == ["agents.run.execute"]
    assert agent_env.tools.calls["answer"] == 0


@pytest.mark.asyncio
async def test_cancel_refuses_a_run_a_worker_finished_meanwhile(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The handler read the run as waiting; a worker commits a terminal state before the
    # conditional cancel UPDATE runs, so the cancel is refused instead of overwriting it.
    from app.interfaces.http import agent_runs as agent_runs_http

    agent_env.use_runtime(build_runtime(agent_env.tools, approval=True))
    seeded = await agent_env.aseed()
    original = agent_runs_http.agent_run_worker_repository.cancel_active

    async def _finished_first(session: Any, **kwargs: Any) -> bool:
        async with agent_env.factory() as other:
            run = await other.get(AgentRun, kwargs["run_id"])
            assert run is not None
            run.status = "completed"
            await other.commit()
        return await original(session, **kwargs)

    async with api_client(agent_env) as client:
        member = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        created = await client.post("/api/v1/agent/runs", headers=member, json=BODY)
        run_id = created.json()["run"]["run_id"]
        waiting = await client.get(f"/api/v1/agent/runs/{run_id}", headers=member)
        assert waiting.json()["status"] == "waiting_approval"
        monkeypatch.setattr(
            agent_runs_http.agent_run_worker_repository, "cancel_active", _finished_first
        )
        refused = await client.post(f"/api/v1/agent/runs/{run_id}/cancel", headers=member)
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "run_already_terminal"
        monkeypatch.setattr(agent_runs_http.agent_run_worker_repository, "cancel_active", original)
        run = await client.get(f"/api/v1/agent/runs/{run_id}", headers=member)
    assert run.json()["status"] == "completed" and run.json()["cancelled_at"] is None
