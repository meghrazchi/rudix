"""Cached auth principal, permission sets, and feature flags over HTTP (R04-05).

Every test runs with ``tests.redis_fakes.FakeRedis`` as the app's Redis client, on SQLite and
(when ``TEST_DATABASE_URL`` is set) PostgreSQL. A probe app exercises only the auth
dependencies so statement counts measure the authentication overhead; real routes perform
the writes (logout, team role change, member removal, SCIM delete, custom-role update,
feature-flag set/clear) whose commit must invalidate the cache before the next request.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.dependencies import get_current_principal, require_feature, require_permission
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.auth.session_repository import AuthSessionRepository
from app.auth.token_codec import create_app_access_token, create_app_refresh_token
from app.clients import redis_client as redis_module
from app.core import cache
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.scim.services.scim_service import _hash_token
from app.interfaces.http.auth import _hash_refresh_token
from app.main import app
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.org_scim_config import OrgSCIMConfig
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from tests.redis_fakes import BrokenRedis, FakeRedis

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

_SESSION_CONTEXT_MARKER = "/* rudix:session-context */"
_CUSTOM_PERMISSION = "billing:manage"
_API = settings.api_prefix


probe_app = FastAPI()


@probe_app.get("/probe")
async def probe(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> dict[str, Any]:
    return {"organization_id": principal.organization_id, "roles": principal.roles}


@probe_app.get("/probe/permission")
async def probe_permission(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_CUSTOM_PERMISSION))],
) -> dict[str, Any]:
    return {"roles": principal.roles}


@probe_app.get("/probe/feature")
async def probe_feature(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _flag: Annotated[None, Depends(require_feature("agents"))],
) -> dict[str, Any]:
    return {"roles": principal.roles}


@probe_app.get("/probe/all")
async def probe_all(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_CUSTOM_PERMISSION))],
    _flag: Annotated[None, Depends(require_feature("agents"))],
) -> dict[str, Any]:
    return {"roles": principal.roles}


class StatementCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        del conn, cursor, args
        if _SESSION_CONTEXT_MARKER not in statement:
            self.statements.append(statement)

    def reset(self) -> None:
        self.statements.clear()

    @property
    def count(self) -> int:
        return len(self.statements)


@dataclass
class Ctx:
    main: AsyncClient
    probe: AsyncClient
    db: AsyncSession
    redis: FakeRedis
    counter: StatementCounter


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRedis]:
    redis = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(settings, "cache_enabled", True)
    yield redis


@pytest_asyncio.fixture
async def ctx(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, fake_redis: FakeRedis
) -> AsyncIterator[Ctx]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_agents", False)
    get_auth_provider.cache_clear()

    # One session per request, like production (a shared identity map would serve stale
    # relationship collections); on PostgreSQL each joins the test's rolled-back connection.
    bind = db_session.bind
    factory = async_sessionmaker(
        bind=bind,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_db_session] = _override
    probe_app.dependency_overrides[get_db_session] = _override

    target = bind.sync_engine if isinstance(bind, AsyncEngine) else bind.sync_connection
    counter = StatementCounter()
    event.listen(target, "before_cursor_execute", counter)
    try:
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as main,
            AsyncClient(transport=ASGITransport(app=probe_app), base_url="http://test") as probe,
        ):
            yield Ctx(main=main, probe=probe, db=db_session, redis=fake_redis, counter=counter)
    finally:
        event.remove(target, "before_cursor_execute", counter)
        app.dependency_overrides.clear()
        probe_app.dependency_overrides.clear()


@dataclass
class Seeded:
    org_a: Organization
    org_b: Organization
    owner: User
    owner_token: str
    user: User
    member_a: OrganizationMember
    session_id: UUID
    refresh_token: str
    token: str


def _access_token(user: User, session_id: UUID, org: Organization) -> str:
    return create_app_access_token(
        subject=str(user.id), session_id=str(session_id), organization_id=str(org.id)
    )


async def _session_row(db: AsyncSession, user: User, org: Organization) -> tuple[UUID, str]:
    session_id = uuid4()
    refresh_token = create_app_refresh_token(
        subject=str(user.id), session_id=str(session_id), organization_id=str(org.id)
    )
    await AuthSessionRepository().create_session(
        db,
        organization_id=org.id,
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        refresh_token_jti=uuid4().hex,
        device_name=None,
        user_agent=None,
        ip_address=None,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    return session_id, refresh_token


async def _seed(db: AsyncSession) -> Seeded:
    org_a = Organization(name="Cache A", slug=f"cache-a-{uuid4().hex[:8]}")
    org_b = Organization(name="Cache B", slug=f"cache-b-{uuid4().hex[:8]}")
    db.add_all([org_a, org_b])
    await db.flush()
    owner = User(
        organization_id=org_a.id,
        external_auth_id=f"owner-{uuid4().hex[:8]}",
        email=f"owner-{uuid4().hex[:8]}@example.com",
        display_name="Owner",
    )
    user = User(
        organization_id=org_b.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="User",
        scim_external_id=f"scim-{uuid4().hex[:8]}",
    )
    db.add_all([owner, user])
    await db.flush()
    member_a = OrganizationMember(organization_id=org_a.id, user_id=user.id, role="member")
    db.add_all(
        [
            OrganizationMember(organization_id=org_a.id, user_id=owner.id, role="owner"),
            member_a,
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role="viewer"),
        ]
    )
    owner_session, _ = await _session_row(db, owner, org_a)
    # The user's session belongs to org B, so removal from org A does not revoke it.
    session_id, refresh_token = await _session_row(db, user, org_b)
    await db.commit()
    return Seeded(
        org_a=org_a,
        org_b=org_b,
        owner=owner,
        owner_token=_access_token(owner, owner_session, org_a),
        user=user,
        member_a=member_a,
        session_id=session_id,
        refresh_token=refresh_token,
        token=_access_token(user, session_id, org_b),
    )


def _headers(token: str, org: Organization) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


async def _assign_custom_role(db: AsyncSession, s: Seeded, permissions: list[str]) -> CustomRole:
    role = CustomRole(organization_id=s.org_a.id, name=f"cr-{uuid4().hex[:6]}")
    db.add(role)
    await db.flush()
    for permission in permissions:
        db.add(CustomRolePermission(custom_role_id=role.id, permission=permission))
    s.member_a.custom_role_id = role.id
    await db.commit()
    return role


async def test_warm_cache_authenticated_request_issues_at_most_one_statement(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    await _assign_custom_role(ctx.db, s, [_CUSTOM_PERMISSION])
    await ctx.main.put(
        f"{_API}/admin/feature-flags/agents",
        headers=_headers(s.owner_token, s.org_a),
        json={"enabled": True},
    )
    headers = _headers(s.token, s.org_a)

    ctx.counter.reset()
    cold = await ctx.probe.get("/probe/all", headers=headers)
    cold_count = ctx.counter.count
    ctx.counter.reset()
    warm = await ctx.probe.get("/probe/all", headers=headers)
    warm_count = ctx.counter.count

    assert cold.status_code == warm.status_code == 200
    assert warm.json() == cold.json() == {"roles": ["member"]}
    # Cold: session, user, memberships(+orgs), custom-role permissions and base role, flags.
    assert cold_count >= 5
    assert warm_count <= 1, ctx.counter.statements

    ctx.counter.reset()
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200
    assert ctx.counter.count <= 1


async def test_logout_all_rejects_old_access_token_on_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers = _headers(s.token, s.org_b)
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200  # warm

    response = await ctx.main.post(f"{_API}/auth/logout-all", headers=headers)
    assert response.status_code == 200

    rejected = await ctx.probe.get("/probe", headers=headers)
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Session has been revoked"


async def test_logout_with_refresh_token_rejects_old_access_token(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers = _headers(s.token, s.org_b)
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200

    response = await ctx.main.post(f"{_API}/auth/logout", json={"refresh_token": s.refresh_token})
    assert response.status_code == 200

    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 401
    # Revoked sessions are never cached: still rejected, still from the database.
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 401


async def test_team_role_change_applies_on_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers = _headers(s.token, s.org_a)
    assert (await ctx.probe.get("/probe", headers=headers)).json()["roles"] == ["member"]

    response = await ctx.main.patch(
        f"{_API}/team/members/{s.member_a.id}/role",
        headers=_headers(s.owner_token, s.org_a),
        json={"role": "viewer"},
    )
    assert response.status_code == 200, response.text

    assert (await ctx.probe.get("/probe", headers=headers)).json()["roles"] == ["viewer"]


async def test_member_removal_forbids_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers = _headers(s.token, s.org_a)
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200

    response = await ctx.main.delete(
        f"{_API}/team/members/{s.member_a.id}", headers=_headers(s.owner_token, s.org_a)
    )
    assert response.status_code == 200, response.text

    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 403
    # The user's other organisation still works.
    other = await ctx.probe.get("/probe", headers=_headers(s.token, s.org_b))
    assert other.json()["roles"] == ["viewer"]


async def test_scim_deprovisioning_rejects_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    raw = uuid4().hex
    ctx.db.add(
        OrgSCIMConfig(
            organization_id=s.org_b.id, enabled=True, token_hash=_hash_token(raw), token_hint="x"
        )
    )
    await ctx.db.commit()
    headers = _headers(s.token, s.org_b)
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200

    response = await ctx.main.delete(
        f"{_API}/scim/v2/Users/{s.user.scim_external_id}",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 204, response.text

    rejected = await ctx.probe.get("/probe", headers=headers)
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Account has been deprovisioned"


async def test_custom_role_permission_change_applies_on_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    role = await _assign_custom_role(ctx.db, s, ["audit_logs:view"])
    headers = _headers(s.token, s.org_a)
    assert (await ctx.probe.get("/probe/permission", headers=headers)).status_code == 403
    assert (await ctx.probe.get("/probe/permission", headers=headers)).status_code == 403

    response = await ctx.main.patch(
        f"{_API}/admin/roles/{role.id}",
        headers=_headers(s.owner_token, s.org_a),
        json={"permissions": [_CUSTOM_PERMISSION]},
    )
    assert response.status_code == 200, response.text
    assert (await ctx.probe.get("/probe/permission", headers=headers)).status_code == 200

    response = await ctx.main.patch(
        f"{_API}/admin/roles/{role.id}",
        headers=_headers(s.owner_token, s.org_a),
        json={"permissions": ["audit_logs:view"]},
    )
    assert response.status_code == 200, response.text
    assert (await ctx.probe.get("/probe/permission", headers=headers)).status_code == 403


async def test_feature_flag_set_and_clear_apply_on_next_request(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers_a = _headers(s.token, s.org_a)
    headers_b = _headers(s.token, s.org_b)
    assert (await ctx.probe.get("/probe/feature", headers=headers_a)).status_code == 403
    assert (await ctx.probe.get("/probe/feature", headers=headers_b)).status_code == 403

    response = await ctx.main.put(
        f"{_API}/admin/feature-flags/agents",
        headers=_headers(s.owner_token, s.org_a),
        json={"enabled": True},
    )
    assert response.status_code == 200, response.text
    assert (await ctx.probe.get("/probe/feature", headers=headers_a)).status_code == 200
    # Org B has no override: the org A value never leaks into org B's key.
    assert (await ctx.probe.get("/probe/feature", headers=headers_b)).status_code == 403

    response = await ctx.main.delete(
        f"{_API}/admin/feature-flags/agents", headers=_headers(s.owner_token, s.org_a)
    )
    assert response.status_code == 200, response.text
    assert (await ctx.probe.get("/probe/feature", headers=headers_a)).status_code == 403


async def test_same_user_gets_the_right_role_per_organisation(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    for _ in range(2):  # cold, then warm
        response_a = await ctx.probe.get("/probe", headers=_headers(s.token, s.org_a))
        response_b = await ctx.probe.get("/probe", headers=_headers(s.token, s.org_b))
        assert response_a.json() == {"organization_id": str(s.org_a.id), "roles": ["member"]}
        assert response_b.json() == {"organization_id": str(s.org_b.id), "roles": ["viewer"]}

    # A custom role in org A grants nothing in org B.
    await _assign_custom_role(ctx.db, s, [_CUSTOM_PERMISSION])
    allowed = await ctx.probe.get("/probe/permission", headers=_headers(s.token, s.org_a))
    assert allowed.status_code == 200
    denied = await ctx.probe.get("/probe/permission", headers=_headers(s.token, s.org_b))
    assert denied.status_code == 403

    outsider_org = Organization(name="Outsider", slug=f"out-{uuid4().hex[:8]}")
    ctx.db.add(outsider_org)
    await ctx.db.commit()
    forbidden = await ctx.probe.get("/probe", headers=_headers(s.token, outsider_org))
    assert forbidden.status_code == 403


async def test_expired_cached_session_is_rejected(ctx: Ctx) -> None:
    s = await _seed(ctx.db)
    headers = _headers(s.token, s.org_b)
    assert (await ctx.probe.get("/probe", headers=headers)).status_code == 200

    # Expire the snapshot's session without a write the listeners see (clock moves on).
    snapshot_key = next(k for k in ctx.redis.keyspace.strings if ":auth_principal:" in k)
    raw = ctx.redis.keyspace.strings[snapshot_key]
    past = (datetime.now(tz=UTC) - timedelta(minutes=1)).isoformat()
    payload = json.loads(raw)
    payload["session"]["expires_at"] = past
    ctx.redis.keyspace.strings[snapshot_key] = json.dumps(payload)

    rejected = await ctx.probe.get("/probe", headers=headers)
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Session has been revoked"


async def test_redis_down_gives_same_responses_from_database(
    ctx: Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await _seed(ctx.db)
    await _assign_custom_role(ctx.db, s, [_CUSTOM_PERMISSION])
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    before = cache.CACHE_ERRORS_TOTAL.labels(
        namespace=cache.NAMESPACE_AUTH_PRINCIPAL, operation="version"
    )._value.get()

    headers_a = _headers(s.token, s.org_a)
    assert (await ctx.probe.get("/probe", headers=headers_a)).json()["roles"] == ["member"]
    assert (await ctx.probe.get("/probe/permission", headers=headers_a)).status_code == 200
    assert (await ctx.probe.get("/probe/feature", headers=headers_a)).status_code == 403

    response = await ctx.main.post(f"{_API}/auth/logout-all", headers=headers_a)
    assert response.status_code == 200
    assert (await ctx.probe.get("/probe", headers=headers_a)).status_code == 401

    after = cache.CACHE_ERRORS_TOTAL.labels(
        namespace=cache.NAMESPACE_AUTH_PRINCIPAL, operation="version"
    )._value.get()
    assert after >= before + 3


async def test_require_permission_reads_membership_without_snapshot(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """Principals from other providers carry no snapshot: the membership row is read."""
    s = await _seed(db_session)
    await _assign_custom_role(db_session, s, [_CUSTOM_PERMISSION])

    dependency = require_permission(_CUSTOM_PERMISSION)
    principal = AuthenticatedPrincipal(
        user_id=str(s.user.id),
        organization_id=str(s.org_a.id),
        roles=["member"],
        auth_provider="clerk",
    )
    request = Request({"type": "http", "headers": []})
    assert await dependency(request, principal, db_session) is principal


def test_snapshot_helpers_handle_missing_and_foreign_state() -> None:

    from app.auth.principal_snapshot import (
        PrincipalSnapshot,
        SessionSnapshot,
        request_snapshot,
        store_request_snapshot,
    )

    assert SessionSnapshot(present=False).is_expired() is False
    naive_future = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(hours=1)
    assert SessionSnapshot(present=True, expires_at=naive_future).is_expired() is False

    user_id = uuid4()
    snapshot = PrincipalSnapshot(
        user_id=user_id, is_active=True, memberships={}, session=SessionSnapshot(present=False)
    )
    assert snapshot.custom_role_id_for(str(uuid4())) is None
    request = Request({"type": "http", "headers": []})
    assert request_snapshot(request, user_id=str(user_id)) is None
    store_request_snapshot(request, snapshot)
    assert request_snapshot(request, user_id=str(user_id)) is snapshot
    assert request_snapshot(request, user_id=str(uuid4())) is None
