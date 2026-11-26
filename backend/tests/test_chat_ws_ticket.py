"""R02-10: WebSocket chat ticket auth, header auth, the ?token= flag, and log redaction."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Address, Headers

# Strict settings must load before app.main is imported (ENVIRONMENT=test adds the
# root/``/api`` route aliases that other test modules rely on).
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.application.chat import ws_auth
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.auth.session_repository import AuthSessionRepository
from app.auth.token_codec import create_app_access_token
from app.clients import redis_client as redis_module
from app.core import metrics
from app.core.config import AuthProvider, settings
from app.core.logging import (
    QueryCredentialRedactionFilter,
    _redact_sensitive_fields,
    configure_logging,
)
from app.db.session import get_db_session
from app.domains.api_keys.services.api_keys_service import ApiKeysService
from app.domains.chat.services.ws_ticket_service import (
    WsTicketClaims,
    WsTicketService,
    WsTicketUnavailableError,
)
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.api_key import ApiKey
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

TICKET_URL = "/api/v1/chat/ws-ticket"


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, Any] = {}
        self.fail = fail
        self.getdel_calls = 0

    async def set(self, key: str, value: str, ex: int, nx: bool) -> bool:
        if self.fail:
            raise RuntimeError("redis down")
        assert ex > 0 and nx is True
        if key in self.store:
            return False
        self.store[key] = value
        return True

    async def getdel(self, key: str) -> Any:
        self.getdel_calls += 1
        if self.fail:
            raise RuntimeError("redis down")
        return self.store.pop(key, None)


class FakeWebSocket:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = Headers(headers=headers or {})
        self.client = Address("127.0.0.1", 50000)
        self.accepted = False
        self.closes: list[tuple[int, str]] = []
        self.sent: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closes.append((code, reason))

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


class _SessionLocalOverride:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> Any:
        session = self._session

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                return session

            async def __aexit__(self, *args: object) -> bool:
                return False

        return _Ctx()


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake)
    return fake


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, fake_redis: FakeRedis
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(settings, "chat_ws_allow_query_token", True)
    monkeypatch.setattr(chat_api, "SessionLocal", _SessionLocalOverride(db_session))
    get_auth_provider.cache_clear()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        yield http
    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


async def _seed(
    db_session: AsyncSession, *orgs_roles: OrganizationRole
) -> tuple[User, list[Organization]]:
    orgs = [Organization(name="WS", slug=f"ws-{uuid4().hex[:8]}") for _ in orgs_roles]
    db_session.add_all(orgs)
    await db_session.flush()
    user = User(
        organization_id=orgs[0].id,
        external_auth_id=f"ws-{uuid4().hex[:8]}",
        email=f"ws-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    for org, role in zip(orgs, orgs_roles, strict=True):
        db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, orgs


def _token(user: User, org: Organization, session_id: str | None = None) -> str:
    return create_app_access_token(
        subject=str(user.id), organization_id=str(org.id), session_id=session_id
    )


async def _issue(http: AsyncClient, token: str, org: Organization) -> str:
    resp = await http.post(
        TICKET_URL,
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(org.id)},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["ticket"])


async def _connect(
    ws: FakeWebSocket, *, ticket: str | None = None, token: str | None = None
) -> FakeWebSocket:
    await chat_api.chat_websocket(ws, token=token, ticket=ticket)  # type: ignore[arg-type]
    return ws


def _ready(ws: FakeWebSocket) -> bool:
    return ws.accepted and any(e["event"] == "connection.ready" for e in ws.sent)


def _principal(**overrides: Any) -> AuthenticatedPrincipal:
    data: dict[str, Any] = {
        "user_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "roles": ["member"],
        "auth_provider": "app",
        "auth_session_id": str(uuid4()),
    }
    data.update(overrides)
    return AuthenticatedPrincipal(**data)


# ── WsTicketService ───────────────────────────────────────────────────────────


async def test_ticket_redeems_once_and_only_hash_is_stored() -> None:
    fake = FakeRedis()
    service = WsTicketService(redis_getter=lambda: fake)
    principal = _principal()
    ticket, ttl = await service.issue(principal)
    assert ttl == settings.chat_ws_ticket_ttl_seconds
    expected_key = "rudix:ws_ticket:v1:" + hashlib.sha256(ticket.encode()).hexdigest()
    assert list(fake.store) == [expected_key]
    assert all(ticket not in k and ticket not in v for k, v in fake.store.items())
    claims = await service.redeem(ticket)
    assert claims is not None
    assert claims.user_id == principal.user_id
    assert claims.auth_session_id == principal.auth_session_id
    assert await service.redeem(ticket) is None


async def test_ticket_expires_by_clock() -> None:
    fake = FakeRedis()
    now = [1000.0]
    service = WsTicketService(redis_getter=lambda: fake, clock=lambda: now[0])
    ticket, ttl = await service.issue(_principal())
    now[0] += ttl + 1
    assert await service.redeem(ticket) is None


async def test_redis_none_and_errors() -> None:
    none_service = WsTicketService(redis_getter=lambda: None)
    with pytest.raises(WsTicketUnavailableError):
        await none_service.issue(_principal())
    assert await none_service.redeem("abc") is None
    failing = WsTicketService(redis_getter=lambda: FakeRedis(fail=True))
    with pytest.raises(WsTicketUnavailableError):
        await failing.issue(_principal())
    assert await failing.redeem("abc") is None
    with pytest.raises(WsTicketUnavailableError):
        await WsTicketService(redis_getter=FakeRedis).issue(_principal(organization_id=None))


async def test_issue_fails_when_set_not_stored() -> None:
    fake = FakeRedis()

    async def _set_false(*args: Any, **kwargs: Any) -> bool:
        return False

    fake.set = _set_false  # type: ignore[method-assign]
    with pytest.raises(WsTicketUnavailableError):
        await WsTicketService(redis_getter=lambda: fake).issue(_principal())


@pytest.mark.parametrize("bad", ["", "a" * 129, "abc$def", "../etc", "a b"])
async def test_malformed_ticket_rejected_before_lookup(bad: str) -> None:
    fake = FakeRedis()
    assert await WsTicketService(redis_getter=lambda: fake).redeem(bad) is None
    assert fake.getdel_calls == 0


async def test_redeem_handles_bytes_and_corrupt_values() -> None:
    fake = FakeRedis()
    service = WsTicketService(redis_getter=lambda: fake)
    ticket, _ = await service.issue(_principal())
    key = next(iter(fake.store))
    fake.store[key] = fake.store[key].encode()
    assert await service.redeem(ticket) is not None
    ticket, _ = await service.issue(_principal())
    fake.store[next(iter(fake.store))] = "not-json"
    assert await service.redeem(ticket) is None


# ── POST /chat/ws-ticket ─────────────────────────────────────────────────────


async def test_endpoint_returns_ttl_and_no_store(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_ws_ticket_ttl_seconds", 45)
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    resp = await client.post(TICKET_URL, headers={"Authorization": f"Bearer {_token(user, org)}"})
    assert resp.status_code == 200
    assert resp.json()["expires_in"] == 45
    assert resp.headers["cache-control"] == "no-store"


async def test_endpoint_503_when_redis_missing_or_feature_off(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    headers = {"Authorization": f"Bearer {_token(user, org)}"}
    monkeypatch.setattr(redis_module, "redis_client", None)
    resp = await client.post(TICKET_URL, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["detail"] == {"code": "ws_ticket_unavailable"}
    assert resp.headers["cache-control"] == "no-store"
    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", False)
    resp = await client.post(TICKET_URL, headers=headers)
    assert resp.status_code == 503
    assert resp.json()["detail"] == {"code": "chat_websocket_disabled"}


async def _api_key(db_session: AsyncSession, org: Organization, user: User) -> str:
    raw = ApiKeysService.generate_raw_key()
    db_session.add(
        ApiKey(
            organization_id=org.id,
            name="ws",
            key_prefix=ApiKeysService.key_prefix(raw),
            key_hash=ApiKeysService.hash_key(raw),
            scopes=["chat:query"],
            status="active",
            created_by_id=user.id,
        )
    )
    await db_session.commit()
    return raw


async def test_endpoint_rejects_api_key(client: AsyncClient, db_session: AsyncSession) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.admin)
    raw = await _api_key(db_session, org, user)
    resp = await client.post(TICKET_URL, headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 403


# ── /chat/ws handshake ───────────────────────────────────────────────────────


async def test_ticket_handshake_accepted_then_reuse_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    ticket = await _issue(client, _token(user, org), org)
    assert _ready(await _connect(FakeWebSocket(), ticket=ticket))
    reused = await _connect(FakeWebSocket(), ticket=ticket)
    assert reused.closes == [(4401, "Unauthorized")] and not reused.accepted


async def test_invalid_ticket_does_not_fall_through_to_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    ws = await _connect(FakeWebSocket(), ticket="bogus", token=_token(user, org))
    assert ws.closes == [(4401, "Unauthorized")]


async def test_membership_removed_after_issue_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    ticket = await _issue(client, _token(user, org), org)
    member = await ws_auth._auth_repository.get_membership(
        db_session, organization_id=org.id, user_id=user.id
    )
    await db_session.delete(member)
    await db_session.commit()
    assert (await _connect(FakeWebSocket(), ticket=ticket)).closes == [(4401, "Unauthorized")]


async def test_inactive_user_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    ticket = await _issue(client, _token(user, org), org)
    user.is_active = False
    await db_session.commit()
    assert (await _connect(FakeWebSocket(), ticket=ticket)).closes == [(4401, "Unauthorized")]


async def test_ticket_binds_issuing_org_and_current_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org_a, org_b) = await _seed(db_session, OrganizationRole.member, OrganizationRole.admin)
    ticket = await _issue(client, _token(user, org_a), org_a)
    member = await ws_auth._auth_repository.get_membership(
        db_session, organization_id=org_a.id, user_id=user.id
    )
    member.role = OrganizationRole.viewer.value
    await db_session.commit()
    result = await ws_auth.authenticate_ws_handshake(
        headers=Headers(headers={"x-organization-id": str(org_b.id)}),
        client=None,
        ticket=ticket,
        token=None,
        db_session=db_session,
    )
    assert result.method == "ticket" and result.principal is not None
    assert result.principal.organization_id == str(org_a.id)
    assert result.principal.roles == [OrganizationRole.viewer.value]


async def test_revoked_session_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    session_id = uuid4()
    repo = AuthSessionRepository()
    await repo.create_session(
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
    ticket = await _issue(client, _token(user, org, session_id=str(session_id)), org)
    await repo.mark_session_revoked(
        db_session, session_id=session_id, revoked_at=datetime.now(tz=UTC), reason="logout"
    )
    await db_session.commit()
    assert (await _connect(FakeWebSocket(), ticket=ticket)).closes == [(4401, "Unauthorized")]


async def test_ticket_claims_edge_cases(db_session: AsyncSession) -> None:
    def claims(**overrides: Any) -> WsTicketClaims:
        data: dict[str, Any] = {
            "user_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "auth_provider": "app",
            "auth_session_id": None,
            "issued_at": 0.0,
        }
        data.update(overrides)
        return WsTicketClaims(**data)

    assert await ws_auth.principal_from_ticket(db_session, claims(user_id="x")) is None
    assert await ws_auth.principal_from_ticket(db_session, claims()) is None
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    bad_session = claims(
        user_id=str(user.id), organization_id=str(org.id), auth_session_id="not-a-uuid"
    )
    assert await ws_auth.principal_from_ticket(db_session, bad_session) is None
    ok = claims(user_id=str(user.id), organization_id=str(org.id))
    principal = await ws_auth.principal_from_ticket(db_session, ok)
    assert principal is not None and principal.roles == ["member"]


async def test_authorization_header_jwt_accepted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    ws = FakeWebSocket({"authorization": f"Bearer {_token(user, org)}"})
    assert _ready(await _connect(ws))


async def test_authorization_header_api_key_gets_role_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, (org,) = await _seed(db_session, OrganizationRole.admin)
    raw = await _api_key(db_session, org, user)
    ws = await _connect(FakeWebSocket({"authorization": f"Bearer {raw}"}))
    assert ws.closes == [(4403, "Insufficient role")]


async def test_bad_header_and_missing_credentials(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _connect(FakeWebSocket({"authorization": "Bearer nope"}))
    assert ws.closes == [(4401, "Unauthorized")]
    ws = await _connect(FakeWebSocket())
    assert ws.closes == [(4401, "Missing auth credentials")]


async def test_unexpected_auth_error_fails_closed(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*args: Any) -> AuthenticatedPrincipal:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(ws_auth, "authenticate_bearer_request", _boom)
    result = await ws_auth.authenticate_ws_handshake(
        headers=Headers(headers={"authorization": "Bearer x"}),
        client=None,
        ticket=None,
        token=None,
        db_session=db_session,
    )
    assert result.principal is None and result.failure == "auth_error"


async def test_query_token_flag(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(ws_auth, "log_query_event", lambda **kw: events.append(kw))
    user, (org,) = await _seed(db_session, OrganizationRole.member)
    token = _token(user, org)
    assert _ready(await _connect(FakeWebSocket(), token=token))
    assert [e["event"] for e in events] == ["chat.ws.query_token_used"]
    assert set(events[0]) == {"event", "user_id", "organization_id"}
    assert token not in json.dumps(events)

    monkeypatch.setattr(settings, "chat_ws_allow_query_token", False)
    result = await ws_auth.authenticate_ws_handshake(
        headers=Headers(), client=None, ticket=None, token=token, db_session=db_session
    )
    assert result.failure == "query_token_disabled"
    assert (await _connect(FakeWebSocket(), token=token)).closes == [(4401, "Unauthorized")]


def test_ws_auth_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    counter = metrics.CHAT_WS_AUTH_TOTAL.labels(method="ticket", outcome="accepted")
    before = counter._value.get()
    metrics.record_chat_ws_auth("ticket", "accepted")
    assert counter._value.get() == before + 1

    class _Broken:
        def labels(self, **kwargs: str) -> Any:
            raise RuntimeError("bad")

    monkeypatch.setattr(metrics, "CHAT_WS_AUTH_TOTAL", _Broken())
    metrics.record_chat_ws_auth("ticket", "accepted")
    monkeypatch.setattr(settings, "metrics_enabled", False)
    metrics.record_chat_ws_auth("ticket", "accepted")


# ── Log redaction ─────────────────────────────────────────────────────────────


def _record(msg: str, args: Any) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, msg, args, None)


def test_uvicorn_filter_redacts_query_credentials() -> None:
    flt = QueryCredentialRedactionFilter()
    rec = _record('%s - "WebSocket %s" [accepted]', ("1.2.3.4:1", "/api/v1/chat/ws?ticket=abc&x=1"))
    assert flt.filter(rec)
    assert isinstance(rec.args, tuple)
    assert rec.getMessage() == '1.2.3.4:1 - "WebSocket /api/v1/chat/ws?ticket=***&x=1" [accepted]'
    rec = _record("GET %s %d", ("/api/v1/chat/ws?token=abc", 200))
    flt.filter(rec)
    assert rec.getMessage() == "GET /api/v1/chat/ws?token=*** 200"
    assert rec.args == ("/api/v1/chat/ws?token=***", 200)
    rec = _record("%(path)s", ({"path": "/x?a=1&access_token=abc"},))
    flt.filter(rec)
    assert rec.getMessage() == "/x?a=1&access_token=***" and rec.args is None
    rec = _record("/ok?q=1", None)
    flt.filter(rec)
    assert rec.msg == "/ok?q=1"
    broken = _record("%d", ("not-a-number",))
    assert flt.filter(broken)


def test_filter_installed_once_and_ticket_key_redacted() -> None:
    configure_logging()
    configure_logging()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, QueryCredentialRedactionFilter) for f in filters) == 1
    event = _redact_sensitive_fields(None, "info", {"event": "x", "detail": "ticket=abc"})
    assert event["detail"] == "ticket=***"


def test_session_owner_mismatch_raises() -> None:
    from types import SimpleNamespace

    from app.auth.errors import AuthenticationError
    from app.auth.providers.app_provider import AppAuthProvider

    record: Any = SimpleNamespace(user_id=uuid4())
    AppAuthProvider.ensure_session_owner(None, user_id=uuid4())
    with pytest.raises(AuthenticationError):
        AppAuthProvider.ensure_session_owner(record, user_id=uuid4())
