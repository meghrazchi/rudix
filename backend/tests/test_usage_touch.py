"""Buffered API-key / service-account usage (R04-06): no request-path writes, max-guarded flush."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth import usage_touch
from app.auth.usage_touch import UsageTouch, UsageTouchKind
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.api_keys.services.api_keys_service import ApiKeysService
from app.domains.service_accounts.services.service_accounts_service import (
    ServiceAccountsService,
)
from app.main import app
from app.models.api_key import ApiKey
from app.models.organization import Organization
from app.models.service_account import ServiceAccount, ServiceAccountToken
from app.workers import usage_touch_tasks
from app.workers.base_task import TransientTaskError
from app.workers.celery_app import celery_app
from tests.redis_fakes import BrokenRedis, FakeRedis

_SESSION_CONTEXT_MARKER = "/* rudix:session-context */"
_T1 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _dropped(kind: str, reason: str) -> float:
    return usage_touch.USAGE_TOUCH_DROPPED_TOTAL.labels(kind=kind, reason=reason)._value.get()


def _flushed(kind: str) -> float:
    return usage_touch.USAGE_TOUCH_FLUSHED_TOTAL.labels(kind=kind)._value.get()


class _SessionOverride:
    """Session factory that hands the test session to the flush task."""

    def __init__(self, session: AsyncSession, *, fail: bool = False) -> None:
        self._session = session
        self._fail = fail

    def __call__(self) -> Any:
        session, fail = self._session, self._fail

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                if fail:
                    raise ConnectionError("database down")
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
async def client(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
def statements(db_session: AsyncSession) -> Iterator[list[str]]:
    captured: list[str] = []
    engine = db_session.bind.sync_engine  # type: ignore[union-attr]

    def _capture(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if _SESSION_CONTEXT_MARKER not in statement:
            captured.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    yield captured
    event.remove(engine, "before_cursor_execute", _capture)


async def _org(db_session: AsyncSession) -> Organization:
    org = Organization(name=f"Usage {uuid4().hex[:8]}", slug=f"usage-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    return org


async def _api_key(db_session: AsyncSession) -> tuple[ApiKey, str]:
    org = await _org(db_session)
    raw = ApiKeysService.generate_raw_key()
    key = ApiKey(
        organization_id=org.id,
        name="usage",
        key_prefix=ApiKeysService.key_prefix(raw),
        key_hash=ApiKeysService.hash_key(raw),
        scopes=["documents:read"],
        status="active",
    )
    db_session.add(key)
    await db_session.commit()
    return key, raw


async def _service_account(
    db_session: AsyncSession,
) -> tuple[ServiceAccount, ServiceAccountToken, str]:
    org = await _org(db_session)
    account = ServiceAccount(organization_id=org.id, name="usage", scopes=["documents:read"])
    db_session.add(account)
    await db_session.flush()
    raw = ServiceAccountsService.generate_raw_token()
    token = ServiceAccountToken(
        service_account_id=account.id,
        organization_id=org.id,
        name="t",
        token_prefix=ServiceAccountsService.token_prefix(raw),
        token_hash=ServiceAccountsService.hash_token(raw),
    )
    db_session.add(token)
    await db_session.commit()
    return account, token, raw


def _writes(captured: list[str]) -> list[str]:
    return [s for s in captured if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]


# ── Request path ─────────────────────────────────────────────────────────────


async def test_api_key_request_issues_no_update(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    statements: list[str],
) -> None:
    key, raw = await _api_key(db_session)
    statements.clear()
    response = await client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {raw}", "X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
    )
    assert response.status_code == 200
    assert _writes(statements) == []
    assert fake_redis.script_calls == [fake_redis.registered_scripts[0]]
    member = f"api_key:{key.id}"
    assert fake_redis.keyspace.sets[usage_touch.dirty_key()] == {member}
    stored = fake_redis.keyspace.hgetall(f"{usage_touch.key_prefix()}{member}")
    assert stored["ip"] == "203.0.113.7"


async def test_service_account_request_issues_no_update_and_one_round_trip(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    statements: list[str],
) -> None:
    account, token, raw = await _service_account(db_session)
    statements.clear()
    response = await client.get(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {raw}",
            "X-Organization-ID": str(account.organization_id),
        },
    )
    assert response.status_code == 200
    assert _writes(statements) == []
    assert fake_redis.commands == ["EVALSHA"]
    assert fake_redis.keyspace.sets[usage_touch.dirty_key()] == {
        f"service_account_token:{token.id}",
        f"service_account:{account.id}",
    }


async def test_redis_missing_drops_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    before = _dropped("api_key", "redis_unavailable")
    await usage_touch.record_touches([UsageTouch(UsageTouchKind.api_key, uuid4(), _T1)])
    assert _dropped("api_key", "redis_unavailable") == before + 1


async def test_redis_error_drops_counts_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    before = _dropped("service_account", "redis_error")
    await usage_touch.record_touches(
        [
            UsageTouch(UsageTouchKind.service_account_token, uuid4(), _T1),
            UsageTouch(UsageTouchKind.service_account, uuid4(), _T1),
        ]
    )
    assert _dropped("service_account", "redis_error") == before + 1


async def test_buffer_counts_and_empty_is_noop(fake_redis: FakeRedis) -> None:
    await usage_touch.buffer_touches(fake_redis, [])
    assert fake_redis.round_trips == 0
    before = usage_touch.USAGE_TOUCH_BUFFERED_TOTAL.labels(kind="api_key")._value.get()
    await usage_touch.record_touches([UsageTouch(UsageTouchKind.api_key, uuid4(), _T1)])
    after = usage_touch.USAGE_TOUCH_BUFFERED_TOTAL.labels(kind="api_key")._value.get()
    assert after == before + 1


# ── Touch script semantics ──────────────────────────────────────────────────


async def test_older_touch_never_overwrites_newer(fake_redis: FakeRedis) -> None:
    credential = uuid4()
    newer = UsageTouch(UsageTouchKind.api_key, credential, _T1, "198.51.100.2")
    older = UsageTouch(UsageTouchKind.api_key, credential, _T1 - timedelta(minutes=5), "x")
    await usage_touch.buffer_touches(fake_redis, [newer])
    await usage_touch.buffer_touches(fake_redis, [older])
    popped = await usage_touch.pop_touches(fake_redis, batch_size=10)
    assert popped == [newer]


async def test_naive_datetime_is_treated_as_utc(fake_redis: FakeRedis) -> None:
    credential = uuid4()
    naive = datetime(2026, 11, 1, 12, 0, 0)
    await usage_touch.buffer_touches(
        fake_redis, [UsageTouch(UsageTouchKind.api_key, credential, naive)]
    )
    (popped,) = await usage_touch.pop_touches(fake_redis, batch_size=10)
    assert popped.used_at == _T1 and popped.ip_address is None


def test_parse_popped_skips_malformed_members_and_decodes_bytes() -> None:
    credential = uuid4()
    reply = [
        b"api_key:" + str(credential).encode(),
        [b"used_at_ms", b"1793534400000", b"ip", b""],
        "unknown_kind:abc",
        ["used_at_ms", "1"],
        f"service_account:{uuid4()}",
        [],
    ]
    touches = usage_touch.parse_popped(reply)
    assert touches == [
        UsageTouch(
            UsageTouchKind.api_key,
            credential,
            datetime.fromtimestamp(1793534400, tz=UTC),
            None,
        )
    ]


# ── Flush ───────────────────────────────────────────────────────────────────


async def _reload(db_session: AsyncSession, model: Any, row_id: UUID) -> Any:
    db_session.expire_all()
    return (await db_session.execute(select(model).where(model.id == row_id))).scalar_one()


@pytest.mark.both_dialects
async def test_flush_writes_max_values_and_twice_is_noop(
    db_session: AsyncSession, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage_touch_tasks, "session_factory", _SessionOverride(db_session))
    key, _ = await _api_key(db_session)
    account, token, _ = await _service_account(db_session)
    before = _flushed("api_key")
    for minutes, ip in ((1, "10.0.0.1"), (3, "10.0.0.3"), (2, "10.0.0.2")):
        used_at = _T1 + timedelta(minutes=minutes)
        await usage_touch.buffer_touches(
            fake_redis, [UsageTouch(UsageTouchKind.api_key, key.id, used_at, ip)]
        )
        await usage_touch.buffer_touches(
            fake_redis,
            [
                UsageTouch(UsageTouchKind.service_account_token, token.id, used_at, ip),
                UsageTouch(UsageTouchKind.service_account, account.id, used_at),
            ],
        )

    assert await usage_touch_tasks.flush_usage_touches(fake_redis, batch_size=2) == 3
    assert _flushed("api_key") == before + 1
    key_id, token_id, account_id = key.id, token.id, account.id
    reloaded_key = await _reload(db_session, ApiKey, key_id)
    assert _utc(reloaded_key.last_used_at) == _T1 + timedelta(minutes=3)
    assert reloaded_key.last_used_ip == "10.0.0.3"
    reloaded_token = await _reload(db_session, ServiceAccountToken, token_id)
    assert _utc(reloaded_token.last_used_at) == _T1 + timedelta(minutes=3)
    assert reloaded_token.last_used_ip == "10.0.0.3"
    reloaded_account = await _reload(db_session, ServiceAccount, account_id)
    assert _utc(reloaded_account.last_used_at) == _T1 + timedelta(minutes=3)

    assert await usage_touch_tasks.flush_usage_touches(fake_redis) == 0
    assert _flushed("api_key") == before + 1


@pytest.mark.both_dialects
async def test_flush_never_moves_database_value_backwards(
    db_session: AsyncSession, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage_touch_tasks, "session_factory", _SessionOverride(db_session))
    key, _ = await _api_key(db_session)
    key.last_used_at = _T1 + timedelta(hours=1)
    key.last_used_ip = "192.0.2.9"
    await db_session.commit()
    await usage_touch.buffer_touches(
        fake_redis, [UsageTouch(UsageTouchKind.api_key, key.id, _T1, "10.9.9.9")]
    )
    key_id = key.id
    assert await usage_touch_tasks.flush_usage_touches(fake_redis) == 1
    reloaded = await _reload(db_session, ApiKey, key_id)
    assert _utc(reloaded.last_used_at) == _T1 + timedelta(hours=1)
    assert reloaded.last_used_ip == "192.0.2.9"


async def test_flush_database_failure_rebuffers_and_raises_for_retry(
    db_session: AsyncSession, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        usage_touch_tasks, "session_factory", _SessionOverride(db_session, fail=True)
    )
    credential = uuid4()
    touch = UsageTouch(UsageTouchKind.api_key, credential, _T1, "10.0.0.1")
    await usage_touch.buffer_touches(fake_redis, [touch])
    with pytest.raises(TransientTaskError):
        await usage_touch_tasks.flush_usage_touches(fake_redis)
    # Nothing lost: the touch is back in the buffer for the retry.
    assert await usage_touch.pop_touches(fake_redis, batch_size=10) == [touch]


def test_celery_task_runs_flush_with_factory_client(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRedis()
    closed: list[bool] = []

    async def _aclose() -> None:
        closed.append(True)

    fake.aclose = _aclose  # type: ignore[attr-defined]
    monkeypatch.setattr(usage_touch_tasks, "redis_factory", lambda: fake)
    monkeypatch.setattr(usage_touch_tasks, "session_factory", _SessionOverride(db_session))
    assert usage_touch_tasks.flush_usage_touch_task.run() == 0
    assert closed == [True]


def test_flush_task_is_included_scheduled_and_routed() -> None:
    assert "app.workers.usage_touch_tasks" in celery_app.conf.include
    beat = celery_app.conf.beat_schedule["usage-touch-flush"]
    assert beat["task"] == "usage.touch.flush"
    assert beat["schedule"] == settings.usage_touch_flush_interval_seconds
    route = celery_app.conf.task_routes["usage.touch.flush"]
    assert route["queue"] == settings.celery_task_default_queue
    assert "usage.touch.flush" in celery_app.tasks


def test_keys_use_environment_hash_tag() -> None:
    prefix = usage_touch.key_prefix()
    assert prefix == f"rudix:{{{settings.environment.value}}}:usage_touch:"
    assert usage_touch.dirty_key() == f"{prefix}dirty"
