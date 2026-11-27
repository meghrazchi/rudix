"""R05-02: no database connection is held while the stubbed model generates.

The stub provider looks at the pool inside ``complete()``: zero connections checked out on
the engine behind the session factory and, over HTTP, no open transaction on the request
session. A control run on one long session proves the probe sees a held connection. A
failure before persistence leaves no chat session or message row on either transport.
"""

from __future__ import annotations

import pytest
from chat_golden_providers import install_providers
from chat_golden_support import SeedDoc, seed_documents
from chat_pipeline_probe import (
    PoolProbe,
    ProbingChatProvider,
    ProbingEmbeddingProvider,
    run_ws_question,
    ws_principal,
)
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_chat_golden_transcripts import QUESTION, TEXT_A, GoldenWorld
from test_chat_query_api import (
    _auth_headers,
    _seed_principal,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.events import CollectingEmitter
from app.application.chat.pipeline.pipeline import ChatPipeline
from app.application.chat.pipeline.sessions import SingleSessionScope
from app.auth.token_codec import create_app_access_token
from app.core.config import RlsEnforcement, settings
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.interfaces.http import chat as chat_api
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import OrganizationRole

pytestmark = [pytest.mark.asyncio]

PAYLOAD = {"question": QUESTION, "top_k": 3, "rerank": False}


async def _world(db_session: AsyncSession, provider: ProbingChatProvider) -> GoldenWorld:
    user, organization, _ = await _seed_principal(db_session)
    world = GoldenWorld(
        user=user,
        organization=organization,
        role=OrganizationRole.member,
        provider=provider,
        payload=dict(PAYLOAD),
    )
    await seed_documents(db_session, world, [SeedDoc("a", TEXT_A, 0.92)])
    await db_session.commit()
    return world


async def _chat_rows(db_session: AsyncSession, world: GoldenWorld) -> tuple[int, int]:
    sessions = await db_session.scalar(
        select(func.count())
        .select_from(ChatSession)
        .where(ChatSession.organization_id == world.organization.id)
    )
    messages = await db_session.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(ChatSession.organization_id == world.organization.id)
    )
    return int(sessions or 0), int(messages or 0)


async def _ask_http(client: AsyncClient, world: GoldenWorld) -> int:
    token = create_app_access_token(
        subject=world.user.external_auth_id,
        organization_id=str(world.organization.id),
        expires_in_seconds=600,
    )
    response = await client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(world.organization.id)),
        json=world.payload,
    )
    return response.status_code


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    assert db_session.bind is not None
    return async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)


async def test_http_holds_no_connection_while_the_model_generates(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider(request_session=db_session)
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)

    assert db_session.bind is not None
    with PoolProbe(db_session.bind) as probe:
        provider.probe = probe
        status_code = await _ask_http(chat_query_client, world)

    assert status_code == 200
    answer_calls = [o for o in provider.observations if o.kind == "answer"]
    assert len(answer_calls) == 1
    assert [(o.checked_out, o.request_in_transaction) for o in answer_calls] == [(0, False)]
    assert await _chat_rows(db_session, world) == (1, 2)


async def test_websocket_holds_no_connection_while_the_model_generates(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider()
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)
    monkeypatch.setattr(chat_api, "SessionLocal", _factory(db_session))
    assert db_session.bind is not None

    with PoolProbe(db_session.bind) as probe:
        provider.probe = probe
        websocket = await run_ws_question(
            principal=ws_principal(world.user.id, world.organization.id, "member"),
            payload=world.payload,
        )
        held_after_run = probe.checked_out

    events = websocket.events
    assert events[-1]["event"] == "chat.completed", events
    assert [o.checked_out for o in provider.observations] == [0]
    assert held_after_run == 0
    assert await _chat_rows(db_session, world) == (1, 2)


async def test_http_holds_no_connection_while_the_question_is_embedded(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The query embedding is a provider call too: the graph flag lookup that precedes it
    runs in its own short session, so no connection is held across it."""
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider()
    embed_provider = install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)

    assert db_session.bind is not None
    with PoolProbe(db_session.bind) as probe:
        probing = ProbingEmbeddingProvider(embed_provider, probe=probe, request_session=db_session)
        monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", probing)
        status_code = await _ask_http(chat_query_client, world)

    assert status_code == 200
    assert probing.observations == [(0, False)]


async def test_websocket_holds_no_connection_while_the_question_is_embedded(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider()
    embed_provider = install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)
    monkeypatch.setattr(chat_api, "SessionLocal", _factory(db_session))
    assert db_session.bind is not None

    with PoolProbe(db_session.bind) as probe:
        probing = ProbingEmbeddingProvider(embed_provider, probe=probe)
        monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", probing)
        websocket = await run_ws_question(
            principal=ws_principal(world.user.id, world.organization.id, "member"),
            payload=world.payload,
        )

    assert websocket.events[-1]["event"] == "chat.completed", websocket.events
    assert [checked_out for checked_out, _ in probing.observations] == [0]


async def test_control_probe_sees_a_session_held_across_generation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One session for the whole run (the pre-R05-02 shape) is visible to the probe."""
    provider = ProbingChatProvider()
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)
    assert db_session.bind is not None

    async with _factory(db_session)() as held_session:
        provider.request_session = held_session
        with PoolProbe(db_session.bind) as probe:
            provider.probe = probe
            await ChatPipeline(default_deps).run(
                ChatQueryRequest.model_validate(world.payload),
                ws_principal(world.user.id, world.organization.id, "member"),
                "ws",
                CollectingEmitter(),
                SingleSessionScope(held_session),
                "control",
            )

    assert [(o.checked_out, o.request_in_transaction) for o in provider.observations] == [(1, True)]


async def test_http_generation_failure_leaves_no_chat_rows(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider(fail_kinds=frozenset({"answer"}))
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)

    assert await _ask_http(chat_query_client, world) == 503
    # Nothing was flushed: no rollback is needed to see an empty table.
    assert await _chat_rows(db_session, world) == (0, 0)


async def test_websocket_generation_failure_leaves_no_chat_rows(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider(fail_kinds=frozenset({"answer"}))
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)
    monkeypatch.setattr(chat_api, "SessionLocal", _factory(db_session))

    websocket = await run_ws_question(
        principal=ws_principal(world.user.id, world.organization.id, "member"),
        payload=world.payload,
    )

    last = websocket.events[-1]
    assert (last["event"], last["safe_error_code"]) == ("chat.error", "generation_failed")
    assert await _chat_rows(db_session, world) == (0, 0)


async def test_websocket_run_passes_under_strict_rls_with_the_orm_guard(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = ProbingChatProvider()
    install_providers(monkeypatch, provider)
    world = await _world(db_session, provider)
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    factory = _factory(db_session)
    opened: list[AsyncSession] = []

    def _recording_factory() -> AsyncSession:
        session = factory()
        opened.append(session)
        return session

    monkeypatch.setattr(chat_api, "SessionLocal", _recording_factory)

    websocket = await run_ws_question(
        principal=ws_principal(world.user.id, world.organization.id, "member"),
        payload=world.payload,
    )

    events = websocket.events
    assert events[-1]["event"] == "chat.completed", events
    assert opened, "the run opened no pipeline session"
    assert all(s.info.get("enforce_tenant_guard") is True for s in opened)
    assert all(s.info.get("organization_id") == world.organization.id for s in opened)
    assert await _chat_rows(db_session, world) == (1, 2)
