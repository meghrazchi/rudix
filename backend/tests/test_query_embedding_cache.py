"""Query-embedding cache and the original-question prefetch (R05-05, R05-04)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from chat_b2_support import (
    QUESTION,
    install_fake_redis,
    make_world,
    principal_for,
    run_pipeline,
)
from chat_golden_support import SeedDoc
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.stages._embedding import (
    build_query_embedder,
    start_embedding_prefetch,
)
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.metrics import CHAT_QUERY_EMBEDDING_CACHE_TOTAL
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.chat.services.query_embedding_cache import (
    NAMESPACE_QUERY_EMBEDDING,
    query_embedding_key,
)
from app.interfaces.http import chat as chat_api
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.models.rag_profile import RagProfile
from app.models.user import User
from tests.redis_fakes import BrokenRedis

pytestmark = [pytest.mark.asyncio]


def _metric(result: str) -> float:
    return float(CHAT_QUERY_EMBEDDING_CACHE_TOTAL.labels(result=result)._value.get())


def _retrieve_entries(ctx: Any) -> list[Any]:
    return [entry for entry in ctx.ledger.entries if entry.stage == "retrieve"]


async def test_key_normalises_text_and_separates_model_dimensions_and_index() -> None:
    base = {"model": "m", "dimensions": 8, "index_version": "v1"}
    key = query_embedding_key(question="How many  Days?", **base)  # type: ignore[arg-type]
    assert key == query_embedding_key(question="  how many days? ", **base)  # type: ignore[arg-type]
    # NFKC: a full-width letter normalises to the ASCII one.
    assert key == query_embedding_key(question="How many Ｄays?", **base)  # type: ignore[arg-type]
    assert len(key) == 64 and "days" not in key
    for change in ({"model": "n"}, {"dimensions": 9}, {"index_version": "v2"}):
        assert key != query_embedding_key(question="how many days?", **{**base, **change})  # type: ignore[arg-type]


async def test_repeated_question_skips_the_second_embedding_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = install_fake_redis(monkeypatch)
    world = await make_world(db_session, monkeypatch)
    hits, misses = _metric("hit"), _metric("miss")

    first = await run_pipeline(db_session, world.principal)
    second = await run_pipeline(db_session, world.principal, question=f"  {QUESTION.upper()} ")

    assert len(world.embed.calls) == 1
    assert first.generation.not_found is False and second.generation.not_found is False
    assert [e.prompt_tokens for e in _retrieve_entries(first)] == [7]
    # A hit records a zero-token ledger entry for the retrieval query.
    assert [e.prompt_tokens for e in _retrieve_entries(second)] == [0]
    assert _metric("hit") == hits + 1 and _metric("miss") == misses + 1
    keys = [k for k in redis.keyspace.strings if f":{NAMESPACE_QUERY_EMBEDDING}:" in k]
    assert len(keys) == 1 and str(world.organization.id) in keys[0]


async def test_prefetch_is_off_by_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await make_world(db_session, monkeypatch)

    ctx = await run_pipeline(db_session, world.principal)

    assert settings.chat_query_embedding_prefetch_enabled is False
    assert ctx.prefetched_embedding is None
    assert len(world.embed.calls) == 1


async def test_another_organisation_misses(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_redis(monkeypatch)
    world = await make_world(db_session, monkeypatch)
    other = await make_world(db_session, monkeypatch, docs=[SeedDoc("b2-other", "x", 0.9)])
    other.embed.calls.clear()

    await run_pipeline(db_session, world.principal)
    await run_pipeline(db_session, other.principal)

    # install_providers in the second world replaced the provider: both calls land there.
    assert len(other.embed.calls) == 2


async def test_redis_down_falls_back_to_the_provider(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await make_world(db_session, monkeypatch)
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "cache_enabled", True)

    first = await run_pipeline(db_session, world.principal)
    second = await run_pipeline(db_session, world.principal)

    assert len(world.embed.calls) == 2
    assert first.generation.not_found is False and second.generation.not_found is False


async def test_cache_disabled_embeds_every_time(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_redis(monkeypatch)
    monkeypatch.setattr(settings, "cache_enabled", False)
    world = await make_world(db_session, monkeypatch)

    await run_pipeline(db_session, world.principal)
    await run_pipeline(db_session, world.principal)

    assert len(world.embed.calls) == 2


async def test_prefetch_runs_once_while_configuration_resolves(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    world = await make_world(db_session, monkeypatch)

    ctx = await run_pipeline(db_session, world.principal)

    assert ctx.prefetched_embedding is not None
    assert len(world.embed.calls) == 1
    assert [e.prompt_tokens for e in _retrieve_entries(ctx)] == [7]


async def test_no_prefetch_when_rewriting_can_change_the_query(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    monkeypatch.setattr(settings, "feature_enable_query_rewriting", True)
    world = await make_world(db_session, monkeypatch)

    ctx = await run_pipeline(db_session, world.principal)

    assert ctx.prefetched_embedding is None
    assert ctx.generation.not_found is False


async def test_no_prefetch_for_a_guidance_question(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    world = await make_world(db_session, monkeypatch)

    ctx = await run_pipeline(db_session, world.principal, question="How do I upload a document?")

    assert ctx.prefetched_embedding is None
    assert world.embed.calls == []


class _FailingOnceEmbedding:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.calls.append(request)
        if len(self.calls) == 1:
            raise RuntimeError("embedding provider failed")
        return await self.inner.embed(request)  # type: ignore[no-any-return]


async def test_failed_prefetch_is_embedded_again_by_retrieve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    world = await make_world(db_session, monkeypatch)
    failing = _FailingOnceEmbedding(world.embed)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", failing)

    ctx = await run_pipeline(db_session, world.principal)

    assert ctx.prefetched_embedding is not None and ctx.prefetched_embedding.done()
    assert len(failing.calls) == 2
    assert ctx.generation.not_found is False


async def test_embedder_uses_the_prefetch_once_then_the_cache(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    world = await make_world(db_session, monkeypatch)
    ctx = await run_pipeline(db_session, world.principal)
    world.embed.calls.clear()
    ctx.prefetched_embedding = None
    ctx.background_tasks.clear()
    assert start_embedding_prefetch(ctx) is True
    assert start_embedding_prefetch(ctx) is True  # already started: not started twice
    embed = build_query_embedder(ctx)

    first = await embed(QUESTION)
    again = await embed(QUESTION)
    other = await embed("A different retrieval query")

    assert first[1] == 7 and again[1] == 7 and other[1] == 7
    assert len(world.embed.calls) == 3
    assert ctx.prefetched_embedding is not None
    await asyncio.gather(*ctx.background_tasks)


async def test_other_user_of_the_same_organisation_shares_the_vector(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_redis(monkeypatch)
    world = await make_world(db_session, monkeypatch)
    colleague = User(
        organization_id=world.organization.id,
        external_auth_id="b2-colleague",
        email="b2-colleague@example.com",
    )
    db_session.add(colleague)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=world.organization.id,
            user_id=colleague.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    await run_pipeline(db_session, world.principal)
    await run_pipeline(
        db_session, principal_for(colleague, world.organization, OrganizationRole.member)
    )

    assert len(world.embed.calls) == 1


async def test_profile_without_rewriting_allows_the_prefetch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    monkeypatch.setattr(settings, "feature_enable_query_rewriting", True)
    world = await make_world(db_session, monkeypatch)
    db_session.add(
        RagProfile(
            organization_id=world.organization.id,
            name="No rewriting",
            is_default=True,
            config={"query_rewriting_enabled": False, "query_decomposition_enabled": False},
        )
    )
    await db_session.commit()

    ctx = await run_pipeline(db_session, world.principal)

    assert ctx.prefetched_embedding is not None
    assert len(world.embed.calls) == 1


async def test_cancelled_prefetch_is_embedded_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_query_embedding_prefetch_enabled", True)
    world = await make_world(db_session, monkeypatch)
    ctx = await run_pipeline(db_session, world.principal)
    world.embed.calls.clear()

    async def never() -> Any:
        await asyncio.Event().wait()

    task = asyncio.create_task(never())
    ctx.prefetched_embedding = task
    task.cancel()
    embed = build_query_embedder(ctx)

    vector, tokens = await embed(QUESTION)

    assert tokens == 7 and len(vector) == settings.qdrant_vector_size
    assert len(world.embed.calls) == 1
