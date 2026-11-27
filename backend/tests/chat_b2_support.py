"""Shared setup for the B2 chat tests (R05-04, R05-05): a seeded organisation, the recording
fake providers, an in-memory Redis, and an in-process pipeline run (so coverage sees it)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from chat_golden_providers import RecordingChatProvider, install_providers
from chat_golden_support import GoldenWorld, SeedDoc, seed_documents
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import _FakeEmbeddingProvider

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.events import CollectingEmitter
from app.application.chat.pipeline.pipeline import ChatPipeline
from app.application.chat.pipeline.sessions import SingleSessionScope
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core import cache
from app.core.config import settings
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from tests.redis_fakes import FakeClock, FakeRedis

QUESTION = "How many days of annual leave do employees receive?"
TEXT = "Employees receive twenty days of annual leave each calendar year."


@dataclass
class B2World:
    user: User
    organization: Organization
    role: OrganizationRole
    provider: RecordingChatProvider
    embed: _FakeEmbeddingProvider
    seeded: dict[str, tuple[Any, Any]]

    @property
    def principal(self) -> AuthenticatedPrincipal:
        return principal_for(self.user, self.organization, self.role)

    def calls(self, kind: str) -> int:
        return sum(1 for call_kind, _ in self.provider.calls if call_kind == kind)


def principal_for(
    user: User, organization: Organization, role: OrganizationRole
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(organization.id),
        email=user.email,
        roles=[role.value],
        auth_provider="app",
    )


def install_fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    clock = FakeClock(1_800_000_000_000)
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "now_ms", clock)
    return redis


async def seed_org_user(
    db_session: AsyncSession, *, role: OrganizationRole = OrganizationRole.member
) -> tuple[User, Organization]:
    suffix = uuid4().hex[:8]
    organization = Organization(name=f"B2 Org {suffix}", slug=f"b2-{suffix}")
    db_session.add(organization)
    await db_session.flush()
    user = User(
        organization_id=organization.id,
        external_auth_id=f"b2-user-{uuid4().hex[:8]}",
        email=f"b2-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=role.value)
    )
    await db_session.commit()
    return user, organization


async def make_world(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    docs: list[SeedDoc] | None = None,
    role: OrganizationRole = OrganizationRole.member,
    provider: RecordingChatProvider | None = None,
) -> B2World:
    chat_provider = provider or RecordingChatProvider()
    embed = install_providers(monkeypatch, chat_provider)
    user, organization = await seed_org_user(db_session, role=role)
    golden = GoldenWorld(
        user=user, organization=organization, role=role, provider=chat_provider, payload={}
    )
    seeded = await seed_documents(
        db_session, golden, docs or [SeedDoc(f"b2-{uuid4().hex[:6]}", TEXT, 0.92)]
    )
    # The answer template is seeded lazily on an organisation's first question; seeding it
    # here keeps that one-off write (and its cache version bump) out of the tests.
    await PromptTemplateService().ensure_default_templates(
        db_session, organization_id=organization.id
    )
    await db_session.commit()
    return B2World(
        user=user,
        organization=organization,
        role=role,
        provider=chat_provider,
        embed=embed,
        seeded=seeded,
    )


async def run_pipeline(
    db_session: AsyncSession,
    principal: AuthenticatedPrincipal,
    *,
    question: str = QUESTION,
    **payload: Any,
) -> ChatContext:
    request = ChatQueryRequest.model_validate(
        {"question": question, "top_k": 3, "rerank": False, **payload}
    )
    return await ChatPipeline(default_deps).run(
        request,
        principal,
        "http",
        CollectingEmitter(),
        SingleSessionScope(db_session),
        "b2-test",
    )
