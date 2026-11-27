"""R05-02 on PostgreSQL: 20 concurrent WebSocket runs share a pool of two connections.

The engine has ``pool_size=2``, ``max_overflow=0`` and ``pool_timeout=2``; the stub model
sleeps 200 ms per call. A run that held a connection while "generating" would starve the
others past the pool timeout, so every run completing shows the connections are released
around generation. No latency is asserted or recorded.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from chat_golden_providers import install_providers
from chat_golden_support import SeedDoc, seed_documents
from chat_pipeline_probe import ProbingChatProvider, run_ws_question, ws_principal
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from test_chat_golden_transcripts import QUESTION, TEXT_A, GoldenWorld

from app.core.config import RlsEnforcement, settings
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.interfaces.http import chat as chat_api
from app.models import OrganizationMember
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.user import User

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

RUNS = 20
STUB_LATENCY_SECONDS = 0.2


@pytest_asyncio.fixture
async def small_pool_engine(pg_migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_migrated_url, pool_size=2, max_overflow=0, pool_timeout=2)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed(
    factory: async_sessionmaker[AsyncSession], provider: ProbingChatProvider
) -> GoldenWorld:
    suffix = uuid4().hex[:10]
    async with factory() as session:
        organization = Organization(name=f"R05-02 {suffix}", slug=f"r05-02-{suffix}")
        session.add(organization)
        await session.flush()
        user = User(
            organization_id=organization.id,
            external_auth_id=f"r05-02-{suffix}",
            email=f"r05-02-{suffix}@example.com",
        )
        session.add(user)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.member.value,
            )
        )
        await session.commit()
        world = GoldenWorld(
            user=user,
            organization=organization,
            role=OrganizationRole.member,
            provider=provider,
            payload={"question": QUESTION, "top_k": 3, "rerank": False},
        )
        await seed_documents(session, world, [SeedDoc(f"a-{suffix}", TEXT_A, 0.92)])
        # Seed the answer template once; concurrent first questions would race on it.
        await PromptTemplateService().ensure_default_templates(
            session, organization_id=organization.id
        )
        await session.commit()
    return world


async def _cleanup(factory: async_sessionmaker[AsyncSession], world: GoldenWorld) -> None:
    async with factory() as session:
        await session.execute(delete(User).where(User.id == world.user.id))
        await session.execute(delete(Organization).where(Organization.id == world.organization.id))
        await session.commit()


@pytest.mark.parametrize("mode", [None, RlsEnforcement.strict], ids=["default", "strict"])
async def test_twenty_concurrent_websocket_runs_complete_on_a_pool_of_two(
    small_pool_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement | None,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    factory = async_sessionmaker(
        bind=small_pool_engine, class_=AsyncSession, expire_on_commit=False
    )
    provider = ProbingChatProvider(delay_seconds=STUB_LATENCY_SECONDS)
    install_providers(monkeypatch, provider)
    world = await _seed(factory, provider)
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    monkeypatch.setattr(chat_api, "SessionLocal", factory)
    principal = ws_principal(world.user.id, world.organization.id, "member")
    try:
        sockets = await asyncio.gather(
            *(
                run_ws_question(principal=principal, payload=world.payload, request_id=f"c-{i}")
                for i in range(RUNS)
            )
        )

        outcomes = [socket.events[-1] for socket in sockets]
        assert [o["event"] for o in outcomes] == ["chat.completed"] * RUNS, [
            o.get("safe_error_code") for o in outcomes
        ]
        assert len({o["message_id"] for o in outcomes}) == RUNS
        assert len([o for o in provider.observations if o.kind == "answer"]) == RUNS
        async with factory() as session:
            sessions = await session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.organization_id == world.organization.id)
            )
            messages = await session.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
                .where(ChatSession.organization_id == world.organization.id)
            )
        assert (sessions, messages) == (RUNS, 2 * RUNS)
    finally:
        monkeypatch.setattr(settings, "rls_enforcement", None)
        await _cleanup(factory, world)
