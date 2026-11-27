"""Worker-executed agent runs on PostgreSQL: lease races, SKIP LOCKED, strict RLS (R06-13)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_worker_support import (
    AgentWorkerEnv,
    WorkerKilled,
    agent_env_pg,  # noqa: F401  (fixture)
    build_runtime,
)
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.agents import run_reaper
from app.domains.agents.repositories import AgentRunWorkerRepository
from app.models.agent import AgentRun, AgentStep
from app.models.organization import Organization
from app.models.user import User
from app.workers.async_runtime import run_async

pytestmark = pytest.mark.requires_postgres

_worker = AgentRunWorkerRepository()


def test_worker_run_resumes_after_a_kill_on_postgres(agent_env_pg: AgentWorkerEnv) -> None:  # noqa: F811
    env = agent_env_pg
    env.use_runtime(build_runtime(env.tools, side_effect=True))
    seeded = env.seed()
    run_id = env.submit(seeded)
    repository = env.runtime._repository
    original = repository.update_agent_step
    armed = {"on": True}

    async def _update(session: Any, **kwargs: Any) -> Any:
        outputs = kwargs.get("outputs") or {}
        if armed["on"] and kwargs.get("status") == "completed" and outputs.get("response"):
            armed["on"] = False
            raise WorkerKilled("after side effect")
        return await original(session, **kwargs)

    env.monkeypatch.setattr(repository, "update_agent_step", _update)
    with pytest.raises(WorkerKilled):
        env.execute(run_id, seeded.organization_id, task_id="pg-exec-1")
    result = env.execute(run_id, seeded.organization_id, task_id="pg-exec-1")
    assert result.result["status"] == "completed"
    assert env.tools.calls == {"search": 1, "answer": 1}
    assert env.count(AgentStep, run_id) == 3
    assert len(env.tool_calls(run_id)) == 2
    assert env.run(run_id).lease_owner is None


async def _acquire_race(factory: async_sessionmaker[AsyncSession], run_id: UUID, org: UUID) -> Any:
    now = datetime.now(tz=UTC)
    first_locked = asyncio.Event()

    async def first() -> bool:
        async with factory() as session:
            won = await _worker.acquire(
                session, run_id=run_id, organization_id=org, owner="a", lease_seconds=60, now=now
            )
            first_locked.set()
            await asyncio.sleep(0.3)  # hold the row lock while the second task waits
            await session.commit()
            return won

    async def second() -> bool:
        await first_locked.wait()
        async with factory() as session:
            won = await _worker.acquire(
                session, run_id=run_id, organization_id=org, owner="b", lease_seconds=60, now=now
            )
            await session.commit()
            return won

    return await asyncio.gather(first(), second())


def test_two_tasks_racing_for_a_lease_have_one_winner(agent_env_pg: AgentWorkerEnv) -> None:  # noqa: F811
    env = agent_env_pg
    seeded = env.seed()
    run_id = env.submit(seeded)
    assert run_async(_acquire_race(env.factory, run_id, seeded.organization_id)) == [True, False]
    assert env.run(run_id).lease_owner == "a"


async def _reap_while_locked(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with factory() as holder:
        locked = await _worker.list_expired(holder, now=datetime.now(tz=UTC), limit=1000)
        assert locked, "the holder locks the expired run"
        counts = await run_reaper.reap_expired_runs(session_factory=factory)
        await holder.rollback()
        return counts


def test_reaper_skips_runs_another_reaper_holds(agent_env_pg: AgentWorkerEnv) -> None:  # noqa: F811
    env = agent_env_pg
    seeded = env.seed()
    run_id = env.submit(seeded)
    env.execute_sql(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(
            status="running",
            lease_owner="dead",
            lease_expires_at=datetime.now(tz=UTC) - timedelta(seconds=10),
        )
    )
    counts = run_async(_reap_while_locked(env.factory))
    assert counts["requeued"] == 0
    assert env.run(run_id).status == "running"


@pytest.mark.asyncio
async def test_lease_respects_strict_rls(rls_probe_session: Any) -> None:
    session = rls_probe_session.session
    org = Organization(name="Agent RLS", slug=f"agent-rls-{uuid4().hex[:10]}")
    other = Organization(name="Agent RLS other", slug=f"agent-rls-o-{uuid4().hex[:10]}")
    session.add_all([org, other])
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"rls-{uuid4().hex[:8]}",
        email=f"rls-{uuid4().hex[:8]}@example.com",
    )
    session.add(user)
    await session.flush()
    run = AgentRun(organization_id=org.id, user_id=user.id, status="queued", surface="api")
    session.add(run)
    await session.flush()
    await session.execute(
        text(
            "GRANT UPDATE ON agent_runs TO rudix_rls_probe"  # the probe only has SELECT, INSERT
        )
    )
    now = datetime.now(tz=UTC)
    await rls_probe_session.become_probe(organization_id=other.id, mode="strict")
    assert not await _worker.acquire(
        session, run_id=run.id, organization_id=org.id, owner="x", lease_seconds=60, now=now
    )
    await rls_probe_session.become_owner()
    await rls_probe_session.become_probe(organization_id=org.id, mode="strict")
    assert await _worker.acquire(
        session, run_id=run.id, organization_id=org.id, owner="x", lease_seconds=60, now=now
    )


async def _cancel_while_worker_completes(
    factory: async_sessionmaker[AsyncSession], run_id: UUID, org: UUID
) -> tuple[bool, bool]:
    """The worker's transaction holds the row (completed, not committed yet) while the API
    cancels: the cancel waits, re-checks the status, and refuses."""
    worker_wrote = asyncio.Event()

    async def worker() -> bool:
        async with factory() as session:
            await session.execute(
                update(AgentRun).where(AgentRun.id == run_id).values(status="completed")
            )
            conflict = await _worker.cancelled_elsewhere(
                session, run_id=run_id, organization_id=org
            )
            worker_wrote.set()
            await asyncio.sleep(0.3)  # the cancel waits on the row lock meanwhile
            await session.commit()
            return conflict

    async def api_cancel() -> bool:
        await worker_wrote.wait()
        async with factory() as session:
            cancelled = await _worker.cancel_active(
                session, run_id=run_id, organization_id=org, now=datetime.now(tz=UTC)
            )
            await session.commit()
            return cancelled

    conflict, cancelled = await asyncio.gather(worker(), api_cancel())
    return conflict, cancelled


async def _complete_after_cancel(
    factory: async_sessionmaker[AsyncSession], run_id: UUID, org: UUID
) -> bool:
    """The API cancel commits first: the worker's later write is detected before commit."""
    async with factory() as session:
        assert await _worker.cancel_active(
            session, run_id=run_id, organization_id=org, now=datetime.now(tz=UTC)
        )
        await session.commit()
    async with factory() as session:
        await session.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(status="completed")
        )
        conflict = await _worker.cancelled_elsewhere(session, run_id=run_id, organization_id=org)
        await session.rollback()
        return conflict


def test_cancel_and_completion_never_overwrite_each_other(agent_env_pg: AgentWorkerEnv) -> None:  # noqa: F811
    env = agent_env_pg
    seeded = env.seed()
    first = env.submit(seeded)
    env.execute_sql(update(AgentRun).where(AgentRun.id == first).values(status="running"))
    conflict, cancelled = run_async(
        _cancel_while_worker_completes(env.factory, first, seeded.organization_id)
    )
    assert (conflict, cancelled) == (False, False)
    assert env.run(first).status == "completed" and env.run(first).cancelled_at is None

    second = env.submit(seeded)
    env.execute_sql(update(AgentRun).where(AgentRun.id == second).values(status="running"))
    assert run_async(_complete_after_cancel(env.factory, second, seeded.organization_id))
    assert env.run(second).status == "cancelled"
