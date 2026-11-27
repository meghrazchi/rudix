"""Harness for worker-executed agent runs (R06-13).

``AgentWorkerEnv`` binds ``app.application.agents.worker_execution.deps`` to a test
database (a SQLite copy of the schema template, or ``TEST_DATABASE_URL``), a fake tool
runtime, and a ``FakeRedis``, and switches ``AGENT_RUN_EXECUTION`` to ``worker``. Tasks run
through Celery's eager ``apply`` with an explicit task id, the way a worker delivery (or a
redelivery after the worker died) does. ``WorkerKilled`` is a ``BaseException``: like a
dying process it skips every ``except Exception`` and every commit after it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis_fakes import FakeRedis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.application.agents import run_submission, worker_execution
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.agents.schemas import (
    AgentRuntimeRequest,
    ToolCall,
    ToolEffectPolicy,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services import AgentRuntime, ToolRegistry
from app.models.agent import AgentRun, AgentStep, AgentToolCall
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.outbox import OutboxMessage
from app.models.user import User
from app.workers import agent_tasks
from app.workers.async_runtime import run_async
from app.workers.celery_app import celery_app

DOCUMENT_ID = "11111111-1111-1111-1111-111111111111"


class WorkerKilled(BaseException):
    """Stands in for the worker process dying inside a task."""


@dataclass
class FakeTools:
    """Tool handlers with call counters and optional failure hooks."""

    calls: dict[str, int] = field(default_factory=lambda: {"search": 0, "answer": 0})
    before_answer: Callable[[int], None] | None = None
    after_search: Callable[[], None] | None = None
    answer_tokens: int = 42

    async def search(self, call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, Any]:
        del call, principal
        self.calls["search"] += 1
        if self.after_search is not None:
            self.after_search()
        return {
            "total": 1,
            "items": [{"document_id": DOCUMENT_ID, "filename": "Policy.pdf", "status": "indexed"}],
        }

    async def answer(self, call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, Any]:
        del call, principal
        self.calls["answer"] += 1
        if self.before_answer is not None:
            self.before_answer(self.calls["answer"])
        return {
            "response": "Grounded answer",
            "not_found": False,
            "citations": [],
            "confidence": {"score": 0.8, "category": "high"},
            "debug": {"usage": {"total_tokens": self.answer_tokens, "total_cost_usd": 0.001}},
        }


def build_runtime(
    tools: FakeTools, *, side_effect: bool = False, approval: bool = False
) -> AgentRuntime:
    registry = ToolRegistry()
    registry.register_tool(
        spec=ToolSpec(
            name="search_documents",
            description="Search indexed documents",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=["viewer", "member", "admin", "owner"],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
        ),
        handler=tools.search,
    )
    registry.register_tool(
        spec=ToolSpec(
            name="answer_from_context",
            description="Answer from context",
            capability="documents.answer",
            effect_policy=ToolEffectPolicy.side_effect
            if side_effect
            else ToolEffectPolicy.read_only,
            required_roles=["member", "admin", "owner"],
            approval_required=approval,
            surfaces=[ToolSurface.api],
        ),
        handler=tools.answer,
    )
    return AgentRuntime(registry=registry)


@dataclass
class Seeded:
    organization_id: UUID
    user_id: UUID
    other_organization_id: UUID


@dataclass
class AgentWorkerEnv:
    factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    monkeypatch: pytest.MonkeyPatch
    tools: FakeTools
    redis: FakeRedis
    runtime: AgentRuntime
    created_orgs: list[UUID] = field(default_factory=list)

    def use_runtime(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    def seed(self, *, role: OrganizationRole = OrganizationRole.member) -> Seeded:
        seeded: Seeded = run_async(_seed(self.factory, role))
        self.created_orgs.extend([seeded.organization_id, seeded.other_organization_id])
        return seeded

    async def aseed(self, *, role: OrganizationRole = OrganizationRole.member) -> Seeded:
        """``seed`` for async tests (``run_async`` cannot nest in a running loop)."""
        seeded = await _seed(self.factory, role)
        self.created_orgs.extend([seeded.organization_id, seeded.other_organization_id])
        return seeded

    async def aoutbox(self, organization_id: UUID) -> list[OutboxMessage]:
        return await _query(
            self.factory,
            select(OutboxMessage)
            .where(OutboxMessage.organization_id == organization_id)
            .order_by(OutboxMessage.created_at),
        )

    def submit(self, seeded: Seeded, **request: Any) -> UUID:
        payload = {"objective": "Answer the policy question", "mode": "answer", **request}
        return run_async(_submit(self.factory, seeded, AgentRuntimeRequest(**payload)))

    def execute(self, run_id: UUID, organization_id: UUID, *, task_id: str = "exec-1") -> Any:
        return agent_tasks.execute_agent_run.apply(
            kwargs={"run_id": str(run_id), "organization_id": str(organization_id)},
            task_id=task_id,
        )

    def resume(
        self, run_id: UUID, organization_id: UUID, approval_id: UUID, *, task_id: str = "res-1"
    ) -> Any:
        return agent_tasks.resume_agent_run.apply(
            kwargs={
                "run_id": str(run_id),
                "organization_id": str(organization_id),
                "approval_id": str(approval_id),
            },
            task_id=task_id,
        )

    def query(self, statement: Any) -> list[Any]:
        return run_async(_query(self.factory, statement))

    def run(self, run_id: UUID) -> AgentRun:
        return self.query(select(AgentRun).where(AgentRun.id == run_id))[0]

    def steps(self, run_id: UUID) -> list[AgentStep]:
        return self.query(
            select(AgentStep).where(AgentStep.agent_run_id == run_id).order_by(AgentStep.sequence)
        )

    def tool_calls(self, run_id: UUID) -> list[AgentToolCall]:
        return self.query(select(AgentToolCall).where(AgentToolCall.agent_run_id == run_id))

    def outbox(self, organization_id: UUID) -> list[OutboxMessage]:
        return self.query(
            select(OutboxMessage)
            .where(OutboxMessage.organization_id == organization_id)
            .order_by(OutboxMessage.created_at)
        )

    def count(self, model: Any, run_id: UUID) -> int:
        rows = self.query(
            select(func.count()).select_from(model).where(model.agent_run_id == run_id)
        )
        return int(rows[0])

    def execute_sql(self, statement: Any) -> None:
        run_async(_execute(self.factory, statement))


async def _seed(factory: async_sessionmaker[AsyncSession], role: OrganizationRole) -> Seeded:
    async with factory() as session:
        org = Organization(name="Agent worker", slug=f"agent-worker-{uuid4().hex[:10]}")
        other = Organization(name="Agent worker other", slug=f"agent-worker-o-{uuid4().hex[:10]}")
        session.add_all([org, other])
        await session.flush()
        user = User(
            organization_id=org.id,
            external_auth_id=f"agent-worker-{uuid4().hex[:10]}",
            email=f"agent-worker-{uuid4().hex[:10]}@example.com",
        )
        session.add(user)
        await session.flush()
        session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
        await session.commit()
        return Seeded(organization_id=org.id, user_id=user.id, other_organization_id=other.id)


def principal_for(seeded: Seeded, role: str = "member") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(seeded.user_id),
        organization_id=str(seeded.organization_id),
        roles=[role],
        auth_provider="app",
    )


async def _submit(
    factory: async_sessionmaker[AsyncSession], seeded: Seeded, request: AgentRuntimeRequest
) -> UUID:
    async with factory() as session:
        run = await run_submission.create_queued_run(
            session,
            principal=principal_for(seeded),
            organization_id=seeded.organization_id,
            user_id=seeded.user_id,
            request=request,
            request_id="req-worker",
        )
        await session.commit()
        return run.id


async def _query(factory: async_sessionmaker[AsyncSession], statement: Any) -> list[Any]:
    async with factory() as session:
        result = await session.execute(statement)
        return list(result.scalars().all())


async def _execute(factory: async_sessionmaker[AsyncSession], statement: Any) -> None:
    async with factory() as session:
        await session.execute(statement)
        await session.commit()


async def _delete_orgs(factory: async_sessionmaker[AsyncSession], org_ids: list[UUID]) -> None:
    async with factory() as session:
        await session.execute(
            delete(OutboxMessage).where(OutboxMessage.organization_id.in_(org_ids))
        )
        await session.execute(delete(User).where(User.organization_id.in_(org_ids)))
        await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
        await session.commit()


def make_env(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> Iterator[AgentWorkerEnv]:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    tools = FakeTools()
    env = AgentWorkerEnv(
        factory=factory,
        engine=engine,
        monkeypatch=monkeypatch,
        tools=tools,
        redis=FakeRedis(),
        runtime=build_runtime(tools),
    )
    monkeypatch.setattr(settings, "agent_run_execution", "worker")
    monkeypatch.setattr(settings, "feature_enable_agents", True)
    deps = worker_execution.deps
    monkeypatch.setattr(deps, "session_factory", factory)
    monkeypatch.setattr(deps, "maintenance_factory", factory)
    monkeypatch.setattr(deps, "runtime_factory", lambda: env.runtime)
    monkeypatch.setattr(deps, "redis_factory", lambda: env.redis)
    always_eager = celery_app.conf.task_always_eager
    propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        yield env
    finally:
        celery_app.conf.task_always_eager = always_eager
        celery_app.conf.task_eager_propagates = propagates
        if engine.dialect.name == "postgresql" and env.created_orgs:
            run_async(_delete_orgs(factory, env.created_orgs))
        run_async(engine.dispose())


@asynccontextmanager
async def api_client(env: AgentWorkerEnv, *, redis: Any = None) -> AsyncIterator[AsyncClient]:
    """ASGI client whose request sessions, stream sessions, and Redis use the env."""
    from pydantic import SecretStr

    from app.auth.factory import get_auth_provider
    from app.clients import redis_client as redis_module
    from app.core.config import AuthProvider
    from app.db.session import get_db_session
    from app.interfaces.http import agent_runs as agent_runs_api
    from app.main import app

    mp = env.monkeypatch
    mp.setattr(settings, "auth_provider", AuthProvider.app)
    mp.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    mp.setattr(settings, "app_auth_issuer", "rudix-test")
    mp.setattr(settings, "app_auth_audience", "rudix-test-audience")
    mp.setattr(settings, "rate_limit_enabled", False)
    mp.setattr(redis_module, "redis_client", redis)
    mp.setattr(agent_runs_api, "stream_session_factory", lambda: env.factory)
    mp.setattr(agent_runs_api, "agent_runtime", env.runtime)
    get_auth_provider.cache_clear()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with env.factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_auth_provider.cache_clear()


async def add_user(
    env: AgentWorkerEnv, organization_id: UUID, role: OrganizationRole
) -> tuple[UUID, str]:
    async with env.factory() as session:
        user = User(
            organization_id=organization_id,
            external_auth_id=f"agent-worker-{uuid4().hex[:10]}",
            email=f"agent-worker-{uuid4().hex[:10]}@example.com",
        )
        session.add(user)
        await session.flush()
        session.add(
            OrganizationMember(organization_id=organization_id, user_id=user.id, role=role.value)
        )
        await session.commit()
        return user.id, user.external_auth_id


async def headers_for(env: AgentWorkerEnv, user_id: UUID, organization_id: UUID) -> dict[str, str]:
    from app.auth.token_codec import create_app_access_token

    async with env.factory() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization_id),
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(organization_id)}


@pytest.fixture
def agent_env(
    sqlite_template_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[AgentWorkerEnv]:
    db_file = tmp_path / "agent_worker.db"
    shutil.copyfile(sqlite_template_db, db_file)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", poolclass=NullPool)
    yield from make_env(engine, monkeypatch)


@pytest.fixture
def agent_env_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[AgentWorkerEnv]:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-backed tests")
    engine = create_async_engine(url, poolclass=NullPool)
    yield from make_env(engine, monkeypatch)
