"""Post-commit cache invalidation listeners (R04-05), on SQLite and PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")

from app.auth.session_repository import AuthSessionRepository
from app.clients import redis_client as redis_module
from app.core import cache, cache_invalidation
from app.core.cache_invalidation import (
    PENDING_INFO_KEY,
    install_cache_invalidation_listeners,
    mark_dirty,
)
from app.domains.admin.repositories.feature_flags import FeatureFlagRepository
from app.models.auth_session import AuthRefreshSession
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.feature_flags import OrgFeatureFlagOverride
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from tests.redis_fakes import FakeClock, FakeRedis

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

_START_MS = 1_800_000_000_000


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRedis]:
    clock = FakeClock(_START_MS)
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(cache, "now_ms", clock)
    yield redis


def _version(redis: FakeRedis, kind: str, scope_id: UUID) -> int | None:
    raw = redis.keyspace.get(cache.version_key(kind, str(scope_id)))
    return int(raw) if raw is not None else None


def _bumped(redis: FakeRedis, kind: str, scope_id: UUID) -> bool:
    return _version(redis, kind, scope_id) == _START_MS + 1


async def _seed(db_session: AsyncSession) -> tuple[Organization, User, OrganizationMember]:
    org = Organization(name="Cache Org", slug=f"cache-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"cache-{uuid4().hex[:8]}",
        email=f"cache-{uuid4().hex[:8]}@example.com",
        display_name="Cache User",
    )
    db_session.add(user)
    await db_session.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role="member")
    db_session.add(member)
    await db_session.commit()
    return org, user, member


def _reset(redis: FakeRedis) -> None:
    for key in [k for k in redis.keyspace.strings if k.endswith(":version")]:
        redis.keyspace.delete(key)


async def test_listeners_install_once() -> None:
    install_cache_invalidation_listeners()
    install_cache_invalidation_listeners()
    assert event.contains(Session, "after_commit", cache_invalidation._after_commit)
    assert event.contains(Session, "after_flush", cache_invalidation._after_flush)


async def test_membership_insert_update_delete_bump_user_and_org(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, user, member = await _seed(db_session)
    assert _bumped(fake_redis, "org", org.id)
    assert _bumped(fake_redis, "user", user.id)

    _reset(fake_redis)
    member.role = "admin"
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)
    assert _bumped(fake_redis, "user", user.id)

    _reset(fake_redis)
    await db_session.delete(member)
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)
    assert _bumped(fake_redis, "user", user.id)


async def test_user_bumps_only_for_cached_fields(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    _, user, _ = await _seed(db_session)
    _reset(fake_redis)
    user.display_name = "Renamed"
    await db_session.commit()
    assert _version(fake_redis, "user", user.id) is None

    user.is_active = False
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)


async def test_rollback_discards_pending_bumps(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, user, member = await _seed(db_session)
    org_id, user_id = org.id, user.id
    _reset(fake_redis)
    member.role = "viewer"
    await db_session.flush()
    assert db_session.info.get(PENDING_INFO_KEY)
    await db_session.rollback()
    assert PENDING_INFO_KEY not in db_session.info
    assert _version(fake_redis, "org", org_id) is None
    assert _version(fake_redis, "user", user_id) is None


async def test_savepoint_release_waits_for_the_outer_commit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, user, member = await _seed(db_session)
    _reset(fake_redis)
    async with db_session.begin_nested():
        member.role = "admin"
    # RELEASE SAVEPOINT is not a commit: nothing is bumped until the outer commit.
    assert _version(fake_redis, "user", user.id) is None
    assert db_session.info[PENDING_INFO_KEY]["user"] == {str(user.id)}
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)
    assert _bumped(fake_redis, "org", org.id)


async def test_savepoint_rollback_keeps_the_outer_bumps(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    _, user, member = await _seed(db_session)
    user_id = user.id
    _reset(fake_redis)
    member.role = "admin"
    await db_session.flush()
    savepoint = await db_session.begin_nested()
    await savepoint.rollback()
    # The outer write still commits, so its bump must survive ROLLBACK TO SAVEPOINT.
    await db_session.commit()
    assert _bumped(fake_redis, "user", user_id)

    # A full rollback with a savepoint open drops every pending bump.
    _reset(fake_redis)
    member.role = "viewer"
    await db_session.flush()
    await db_session.begin_nested()
    await db_session.rollback()
    assert PENDING_INFO_KEY not in db_session.info
    assert _version(fake_redis, "user", user_id) is None


async def test_custom_role_and_permission_changes_bump_org(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, _, _ = await _seed(db_session)
    role = CustomRole(organization_id=org.id, name=f"r-{uuid4().hex[:6]}")
    db_session.add(role)
    await db_session.commit()
    _reset(fake_redis)

    db_session.add(CustomRolePermission(custom_role_id=role.id, permission="documents:read"))
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)

    # The role is not in the identity map: its organisation is read on the flush connection.
    _reset(fake_redis)
    role_id = role.id
    db_session.expunge(role)
    db_session.add(CustomRolePermission(custom_role_id=role_id, permission="documents:write"))
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)


async def test_permission_for_unknown_role_is_counted_unresolved(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    before = cache_invalidation.CACHE_UNRESOLVED._value.get()
    sync_session = db_session.sync_session
    orphan = CustomRolePermission(custom_role_id=uuid4(), permission="x")
    sync_session.info.pop(PENDING_INFO_KEY, None)

    def collect(session: Session) -> None:
        cache_invalidation._collect(session, orphan, is_dirty=False)

    await db_session.run_sync(collect)
    assert cache_invalidation.CACHE_UNRESOLVED._value.get() == before + 1
    assert cache_invalidation._custom_role_org(sync_session, None) is None
    assert db_session.info[PENDING_INFO_KEY]["org"] == set()
    await db_session.rollback()


async def test_feature_flag_upsert_and_core_delete_bump_org(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, _, _ = await _seed(db_session)
    repository = FeatureFlagRepository()
    _reset(fake_redis)
    await repository.upsert(
        db_session,
        organization_id=org.id,
        flag_name="agents",
        enabled=True,
        reason=None,
        overridden_by_user_id=None,
    )
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)

    _reset(fake_redis)
    assert await repository.delete(db_session, organization_id=org.id, flag_name="agents")
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)

    _reset(fake_redis)
    db_session.add(OrgFeatureFlagOverride(organization_id=org.id, flag_name="mcp", enabled=False))
    await db_session.commit()
    assert _bumped(fake_redis, "org", org.id)


async def _session_row(db_session: AsyncSession, org: Organization, user: User) -> UUID:
    session_id = uuid4()
    await AuthSessionRepository().create_session(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=uuid4().hex,
        refresh_token_jti=uuid4().hex,
        device_name=None,
        user_agent=None,
        ip_address=None,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    await db_session.commit()
    return session_id


async def test_core_session_revocations_bump_owner(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, user, _ = await _seed(db_session)
    repository = AuthSessionRepository()
    now = datetime.now(tz=UTC)

    session_id = await _session_row(db_session, org, user)
    _reset(fake_redis)
    revoked = await repository.mark_session_revoked(
        db_session, session_id=session_id, revoked_at=now, reason="logout"
    )
    assert revoked == 1
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)

    # Nothing left to revoke: no owner, no bump.
    _reset(fake_redis)
    assert (
        await repository.mark_session_revoked(
            db_session, session_id=session_id, revoked_at=now, reason="logout"
        )
        == 0
    )
    await db_session.commit()
    assert _version(fake_redis, "user", user.id) is None

    record_session = await _session_row(db_session, org, user)
    record = await repository.get_session_by_id(db_session, session_id=record_session)
    assert record is not None
    _reset(fake_redis)
    assert (
        await repository.mark_token_revoked(
            db_session, refresh_token_hash=record.refresh_token_hash, revoked_at=now, reason="x"
        )
        == 1
    )
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)

    await _session_row(db_session, org, user)
    _reset(fake_redis)
    assert (
        await repository.mark_user_sessions_revoked(
            db_session, user_id=user.id, revoked_at=now, reason="logout_all"
        )
        == 1
    )
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)


async def test_orm_session_revocation_bumps_owner(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org, user, _ = await _seed(db_session)
    session_id = await _session_row(db_session, org, user)
    record = await AuthSessionRepository().get_session_by_id(db_session, session_id=session_id)
    assert isinstance(record, AuthRefreshSession)

    _reset(fake_redis)
    record.last_used_at = datetime.now(tz=UTC)
    await db_session.commit()
    assert _version(fake_redis, "user", user.id) is None

    record.revoked_at = datetime.now(tz=UTC)
    await db_session.commit()
    assert _bumped(fake_redis, "user", user.id)


async def test_mark_dirty_accepts_sync_and_async_sessions(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    org_id, user_id = uuid4(), uuid4()
    mark_dirty(db_session, org_ids=[org_id, None], user_ids=[None])
    mark_dirty(db_session.sync_session, user_ids=[user_id])
    await db_session.commit()
    assert _bumped(fake_redis, "org", org_id)
    assert _bumped(fake_redis, "user", user_id)


async def test_commit_without_redis_counts_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    before = cache.CACHE_INVALIDATIONS_TOTAL.labels(scope="org", result="unavailable")._value.get()
    mark_dirty(db_session, org_ids=[uuid4()])
    await db_session.commit()
    after = cache.CACHE_INVALIDATIONS_TOTAL.labels(scope="org", result="unavailable")._value.get()
    assert after == before + 1


async def test_sync_commit_outside_greenlet_is_skipped(fake_redis: FakeRedis) -> None:
    before = cache.CACHE_INVALIDATIONS_TOTAL.labels(scope="user", result="skipped")._value.get()
    sync_session = Session()
    user_id = uuid4()
    mark_dirty(sync_session, user_ids=[user_id])
    cache_invalidation._after_commit(sync_session)
    after = cache.CACHE_INVALIDATIONS_TOTAL.labels(scope="user", result="skipped")._value.get()
    assert after == before + 1
    assert _version(fake_redis, "user", user_id) is None
