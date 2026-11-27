"""Chat configuration caches (R05-05, 0.4.0 deferral): change, commit, next read is fresh.

Covers every organisation-scoped namespace stage 2 and stage 4 read: AI policy (and the
collection override), RAG profile, answer prompt version, model profile, chat tool policy,
quota policy limits, and verified-answer candidates. Keys never cross organisations, and a
Redis outage reads the database.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from chat_b2_support import install_fake_redis, seed_org_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline import config_cache
from app.application.chat.pipeline.deps import default_deps
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.domains.agents.repositories.agent_policy import AgentToolPolicyRepository
from app.domains.ai.profile.schemas import ProfileSource, TaskType
from app.domains.ai.profile.service import resolve_task_profile_cached
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.quota_service import check_quota, get_effective_limits_cached
from app.domains.rag_profiles.repositories.rag_profiles import RagProfileRepository
from app.domains.verified_answers.services.shortcut_matcher import load_candidates
from app.models.agent_policy import AgentToolPolicyOverride
from app.models.ai_response_policy import CollectionAiResponsePolicyOverride, OrgAiResponsePolicy
from app.models.collection import Collection
from app.models.model_profile import OrgModelProfile
from app.models.organization import Organization
from app.models.prompt_template import PromptTemplate, PromptTemplateVersion
from app.models.quotas import OrgQuotaPolicy
from app.models.rag_profile import RagProfile
from app.models.verified_answer import VerifiedAnswer
from tests.redis_fakes import BrokenRedis, FakeRedis

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    return install_fake_redis(monkeypatch)


async def _org(db_session: AsyncSession) -> Organization:
    _, organization = await seed_org_user(db_session)
    return organization


# ---------------------------------------------------------------------------
# AI response policy and collection override
# ---------------------------------------------------------------------------


async def _policy(db_session: AsyncSession, organization_id: UUID, topics: list[str]) -> Any:
    policy = OrgAiResponsePolicy(
        organization_id=organization_id,
        policy_name=f"p-{uuid4().hex[:6]}",
        is_active=True,
        blocked_topics_json=topics,
    )
    db_session.add(policy)
    await db_session.commit()
    return policy


async def _effective(
    db_session: AsyncSession, organization_id: UUID, collection: Any = None
) -> Any:
    return await config_cache.effective_ai_policy(
        db_session, default_deps, organization_id=organization_id, collection_id=collection
    )


async def test_ai_policy_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    assert (await _effective(db_session, org.id)).source == "none"
    policy = await _policy(db_session, org.id, ["salaries"])

    first = await _effective(db_session, org.id)
    assert first.source == "org" and first.blocked_topics == ["salaries"]
    # A hit: deleting the row without the ORM (no flush event) keeps the cached value.
    assert (await _effective(db_session, org.id)).blocked_topics == ["salaries"]

    policy.blocked_topics_json = ["bonuses"]
    await db_session.commit()
    assert (await _effective(db_session, org.id)).blocked_topics == ["bonuses"]


async def test_collection_override_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    user, org = await seed_org_user(db_session)
    policy = await _policy(db_session, org.id, [])
    collection = Collection(organization_id=org.id, owner_id=user.id, name="HR")
    db_session.add(collection)
    await db_session.commit()
    assert (await _effective(db_session, org.id, collection.id)).source == "org"

    override = CollectionAiResponsePolicyOverride(
        org_policy_id=policy.id, collection_id=collection.id, refusal_message="no"
    )
    db_session.add(override)
    await db_session.commit()
    cached = await _effective(db_session, org.id, collection.id)
    assert cached.source == "collection" and cached.refusal_message == "no"

    db_session.expunge(policy)  # the override's parent is resolved on the flush connection
    override.refusal_message = "never"
    await db_session.commit()
    assert (await _effective(db_session, org.id, collection.id)).refusal_message == "never"


# ---------------------------------------------------------------------------
# RAG profile, answer prompt version, model profile
# ---------------------------------------------------------------------------


async def test_rag_profile_change_and_core_update_are_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    profile = RagProfile(
        organization_id=org.id, name="Default", is_default=True, config={"rerank_enabled": True}
    )
    db_session.add(profile)
    await db_session.commit()

    def read() -> Awaitable[config_cache.ResolvedRagProfile]:
        return config_cache.rag_profile_for_context(
            db_session, organization_id=org.id, collection_id=None
        )

    first = await read()
    assert first.source == "org_default" and first.profile is not None
    assert first.profile.config == {"rerank_enabled": True}

    profile.config = {"rerank_enabled": False}
    await db_session.commit()
    second = await read()
    assert second.profile is not None and second.profile.config == {"rerank_enabled": False}

    # Core UPDATE (no flush event): clear_default_flag records the invalidation itself.
    await RagProfileRepository().clear_default_flag(db_session, organization_id=org.id)
    await db_session.commit()
    assert (await read()).source == "system_default"


async def test_answer_prompt_version_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    await PromptTemplateService().ensure_default_templates(db_session, organization_id=org.id)
    await db_session.commit()

    first = await config_cache.answer_prompt_version(db_session, organization_id=org.id)
    version = await db_session.get(PromptTemplateVersion, first.id)
    assert version is not None
    template = await db_session.get(PromptTemplate, version.prompt_template_id)
    assert template is not None
    db_session.expunge(template)  # resolve the parent organisation through a query
    version.content = first.content + "\nEdited."
    await db_session.commit()

    second = await config_cache.answer_prompt_version(db_session, organization_id=org.id)
    assert second.id == first.id and second.content.endswith("Edited.")


async def test_answer_prompt_seeded_in_a_rolled_back_transaction_is_not_cached(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    # The first question of an organisation seeds its default templates in the read
    # transaction. If that transaction rolls back, no cached snapshot may keep the id of a
    # version that was never committed.
    org_id = (await _org(db_session)).id

    seeded = await config_cache.answer_prompt_version(db_session, organization_id=org_id)
    await db_session.rollback()
    assert await db_session.get(PromptTemplateVersion, seeded.id) is None

    reseeded = await config_cache.answer_prompt_version(db_session, organization_id=org_id)
    assert reseeded.id != seeded.id
    await db_session.commit()
    assert await db_session.get(PromptTemplateVersion, reseeded.id) is not None

    cached = await config_cache.answer_prompt_version(db_session, organization_id=org_id)
    assert cached.id == reseeded.id
    assert not db_session.new and not db_session.dirty


async def test_model_profile_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)

    async def read() -> Any:
        return await resolve_task_profile_cached(
            db_session, organization_id=org.id, task_type=TaskType.chat
        )

    assert (await read()).source == ProfileSource.env_default
    profile = OrgModelProfile(
        organization_id=org.id,
        profile_name="chat",
        task_type=TaskType.chat.value,
        provider_type="openai",
        base_model="model-a",
    )
    db_session.add(profile)
    await db_session.commit()
    assert (await read()).base_model == "model-a"

    profile.base_model = "model-b"
    await db_session.commit()
    resolved = await read()
    assert resolved.base_model == "model-b" and resolved.source == ProfileSource.org_profile


# ---------------------------------------------------------------------------
# Chat tool policy, quota policy limits
# ---------------------------------------------------------------------------


async def test_tool_policy_change_and_core_delete_are_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    repo = AgentToolPolicyRepository()

    async def read() -> frozenset[str]:
        return await repo.disabled_tool_names_cached(db_session, organization_id=org.id)

    assert await read() == frozenset()
    override = AgentToolPolicyOverride(organization_id=org.id, tool_name="graph_search")
    override.enabled = False
    db_session.add(override)
    await db_session.commit()
    assert await read() == frozenset({"graph_search"})

    assert await repo.delete_by_tool(db_session, organization_id=org.id, tool_name="graph_search")
    await db_session.commit()
    assert await read() == frozenset()


async def test_quota_policy_limits_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    policy = OrgQuotaPolicy(
        organization_id=org.id,
        limits={"questions": {"hard_limit": 5, "reset_window": "per_day"}},
    )
    db_session.add(policy)
    await db_session.commit()

    first = await get_effective_limits_cached(db_session, organization_id=org.id)
    assert first["questions"]["hard_limit"] == 5
    check = await check_quota(
        db_session, organization_id=org.id, quota_type=QuotaType.questions, requested_amount=6
    )
    assert check.allowed is False

    policy.limits = {"questions": {"hard_limit": 50, "reset_window": "per_day"}}
    await db_session.commit()
    check = await check_quota(
        db_session, organization_id=org.id, quota_type=QuotaType.questions, requested_amount=6
    )
    assert check.allowed is True and check.effective_hard_limit == 50
    # Usage counters are never cached: the namespace holds only the limits (one key per
    # cache version; the older one is orphaned by the bump, never deleted).
    keys = [k for k in fake_redis.keyspace.strings if ":quota_policy:" in k]
    assert keys and all(k.endswith(":quota_policy:limits") for k in keys)


# ---------------------------------------------------------------------------
# Verified-answer candidates
# ---------------------------------------------------------------------------


async def test_verified_answer_candidates_change_is_seen_after_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org = await _org(db_session)
    assert (await load_candidates(db_session, organization_id=org.id)).candidates == []
    card = VerifiedAnswer(
        organization_id=org.id,
        title="Leave",
        question="How much leave?",
        answer_text="Twenty days.",
        status="published",
        published_at=datetime.now(UTC),
    )
    db_session.add(card)
    await db_session.commit()
    first = await load_candidates(db_session, organization_id=org.id)
    assert [c.normalised_question for c in first.candidates] == ["how much leave?"]

    card.status = "deprecated"
    await db_session.commit()
    assert (await load_candidates(db_session, organization_id=org.id)).candidates == []


async def test_verified_answer_candidates_above_the_cap_are_not_matched(
    db_session: AsyncSession, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_verified_answer_max_candidates", 1)
    org = await _org(db_session)
    for index in range(2):
        db_session.add(
            VerifiedAnswer(
                organization_id=org.id,
                title=f"t{index}",
                question=f"q{index}",
                answer_text="a",
                status="published",
            )
        )
    await db_session.commit()
    result = await load_candidates(db_session, organization_id=org.id)
    assert result.over_cap is True and result.candidates == []


# ---------------------------------------------------------------------------
# Isolation and fallbacks
# ---------------------------------------------------------------------------


async def test_keys_never_cross_organisations(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    await _policy(db_session, org_a.id, ["a-topic"])
    await _policy(db_session, org_b.id, ["b-topic"])
    db_session.add_all(
        [
            AgentToolPolicyOverride(organization_id=org_a.id, tool_name="a_tool", enabled=False),
            AgentToolPolicyOverride(organization_id=org_b.id, tool_name="b_tool", enabled=False),
        ]
    )
    await db_session.commit()
    repo = AgentToolPolicyRepository()

    for org, topic, tool in ((org_a, "a-topic", "a_tool"), (org_b, "b-topic", "b_tool")):
        assert (await _effective(db_session, org.id)).blocked_topics == [topic]
        assert await repo.disabled_tool_names_cached(db_session, organization_id=org.id) == {tool}

    for key in fake_redis.keyspace.strings:
        if key.endswith(":version"):
            continue
        owners = [org for org in (org_a, org_b) if f":org:{org.id}:" in key]
        assert len(owners) == 1, key


Reader = Callable[[AsyncSession, UUID], Awaitable[Any]]


async def test_redis_down_reads_the_database(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "cache_enabled", True)
    org = await _org(db_session)
    policy = await _policy(db_session, org.id, ["x"])
    tool = AgentToolPolicyOverride(organization_id=org.id, tool_name="t", enabled=False)
    db_session.add(tool)
    await db_session.commit()

    assert (await _effective(db_session, org.id)).blocked_topics == ["x"]
    policy.blocked_topics_json = ["y"]
    await db_session.commit()
    assert (await _effective(db_session, org.id)).blocked_topics == ["y"]
    assert await AgentToolPolicyRepository().disabled_tool_names_cached(
        db_session, organization_id=org.id
    ) == {"t"}
    rows = (
        await db_session.execute(
            select(AgentToolPolicyOverride).where(AgentToolPolicyOverride.organization_id == org.id)
        )
    ).scalars()
    assert [row.tool_name for row in rows] == ["t"]
    assert (
        await config_cache.rag_profile_for_context(
            db_session, organization_id=org.id, collection_id=None
        )
    ).source == "system_default"
