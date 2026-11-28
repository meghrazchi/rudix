"""Single-use account tokens (0.9.0, S1): storage, consume-once, attempts, revoke, purge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.metrics_account import AUTH_ONE_TIME_TOKENS_TOTAL
from app.domains.auth.repositories import one_time_tokens as token_repository
from app.domains.auth.schemas.one_time_tokens import OneTimeTokenPurpose
from app.domains.auth.services import one_time_tokens as tokens
from app.models.auth_one_time_token import ONE_TIME_TOKEN_PURPOSES, AuthOneTimeToken
from app.models.organization import Organization
from app.models.user import User
from app.workers import account_tasks

pytestmark = pytest.mark.both_dialects

T0 = datetime(2026, 11, 29, 12, 0, tzinfo=UTC)
RESET = OneTimeTokenPurpose.password_reset


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    pinned = Clock(T0)
    monkeypatch.setattr(tokens, "clock", pinned)
    yield pinned


async def _seed_user(session: AsyncSession) -> tuple[UUID, UUID]:
    org_id = uuid4()
    session.add(
        Organization(id=org_id, name=f"Tokens {org_id.hex[:10]}", slug=f"tokens-{org_id.hex[:10]}")
    )
    await session.flush()
    user = User(organization_id=org_id, email=f"tokens-{uuid4().hex[:10]}@example.com")
    session.add(user)
    await session.flush()
    return org_id, user.id


async def _row(session: AsyncSession, raw: str) -> AuthOneTimeToken:
    session.expire_all()
    result = await session.execute(
        select(AuthOneTimeToken).where(AuthOneTimeToken.token_hash == tokens.hash_token(raw))
    )
    return result.scalar_one()


def _metric(purpose: str, outcome: str) -> float:
    return AUTH_ONE_TIME_TOKENS_TOTAL.labels(purpose=purpose, outcome=outcome)._value.get()


def test_purpose_enum_matches_the_check_constraint() -> None:
    assert tuple(OneTimeTokenPurpose) == ONE_TIME_TOKEN_PURPOSES


def test_sqlite_returning_version_gate() -> None:
    assert token_repository.sqlite_supports_returning((3, 35, 0)) is True
    assert token_repository.sqlite_supports_returning((3, 34, 1)) is False


async def test_issue_stores_only_the_hash(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)
    raw = await tokens.issue(
        db_session,
        purpose=OneTimeTokenPurpose.email_verification,
        user_id=user_id,
        organization_id=org_id,
        ttl_seconds=3600,
        metadata={"source": "invite"},
        created_ip="203.0.113.7",
    )
    assert len(raw) >= 43
    row = await _row(db_session, raw)
    assert row.token_hash == tokens.hash_token(raw) and len(row.token_hash) == 64
    for column in AuthOneTimeToken.__table__.columns:
        value = getattr(row, column.key)
        assert raw not in str(value), column.name
    assert row.purpose == "email_verification"
    assert row.metadata_json == {"source": "invite"}
    assert row.created_ip == "203.0.113.7"
    assert row.attempt_count == 0 and row.max_attempts == 1 and row.consumed_at is None
    assert row.expires_at.replace(tzinfo=UTC) == T0 + timedelta(hours=1)


async def test_consume_once_then_none(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)
    raw = await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=600
    )
    consumed_before = _metric("password_reset", "consumed")
    first = await tokens.consume(db_session, purpose=RESET, raw_token=raw)
    assert first is not None and first.user_id == user_id
    assert first.consumed_at is not None
    assert await tokens.consume(db_session, purpose=RESET, raw_token=raw) is None
    assert (await _row(db_session, raw)).consumed_at is not None
    if settings.metrics_enabled:
        assert _metric("password_reset", "consumed") == consumed_before + 1


async def test_expired_wrong_purpose_unknown_and_empty_are_none(
    db_session: AsyncSession, clock: Clock
) -> None:
    org_id, user_id = await _seed_user(db_session)
    raw = await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=60
    )
    assert (
        await tokens.consume(
            db_session, purpose=OneTimeTokenPurpose.email_verification, raw_token=raw
        )
        is None
    )
    assert await tokens.consume(db_session, purpose=RESET, raw_token="not-a-token") is None
    assert await tokens.consume(db_session, purpose=RESET, raw_token="") is None
    clock.advance(seconds=61)
    assert await tokens.consume(db_session, purpose=RESET, raw_token=raw) is None
    assert (await _row(db_session, raw)).consumed_at is None


async def test_user_and_session_binding(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)
    _, other_user = await _seed_user(db_session)
    session_id = uuid4()
    raw = await tokens.issue(
        db_session,
        purpose=OneTimeTokenPurpose.step_up,
        user_id=user_id,
        organization_id=org_id,
        session_id=session_id,
        ttl_seconds=300,
    )
    step_up = OneTimeTokenPurpose.step_up
    assert (
        await tokens.consume(db_session, purpose=step_up, raw_token=raw, user_id=other_user) is None
    )
    assert (
        await tokens.consume(db_session, purpose=step_up, raw_token=raw, session_id=uuid4()) is None
    )
    token = await tokens.consume(
        db_session, purpose=step_up, raw_token=raw, user_id=user_id, session_id=session_id
    )
    assert token is not None and token.session_id == session_id


async def test_failed_attempts_exhaust_the_token(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)
    challenge = OneTimeTokenPurpose.mfa_challenge
    raw = await tokens.issue(
        db_session,
        purpose=challenge,
        user_id=user_id,
        organization_id=org_id,
        ttl_seconds=300,
        max_attempts=3,
    )
    counts = [
        await tokens.record_failed_attempt(db_session, purpose=challenge, raw_token=raw)
        for _ in range(4)
    ]
    assert counts == [1, 2, 3, None]
    assert await tokens.consume(db_session, purpose=challenge, raw_token=raw) is None
    assert await tokens.record_failed_attempt(db_session, purpose=challenge, raw_token="") is None
    assert (
        await tokens.record_failed_attempt(db_session, purpose=challenge, raw_token="unknown")
        is None
    )


async def test_one_failed_attempt_leaves_a_multi_use_budget(
    db_session: AsyncSession, clock: Clock
) -> None:
    org_id, user_id = await _seed_user(db_session)
    challenge = OneTimeTokenPurpose.mfa_challenge
    raw = await tokens.issue(
        db_session,
        purpose=challenge,
        user_id=user_id,
        organization_id=org_id,
        ttl_seconds=300,
        max_attempts=2,
    )
    assert await tokens.record_failed_attempt(db_session, purpose=challenge, raw_token=raw) == 1
    assert await tokens.consume(db_session, purpose=challenge, raw_token=raw) is not None


async def test_revoke_for_user(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)
    _, other_user = await _seed_user(db_session)
    mine = [
        await tokens.issue(
            db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=600
        )
        for _ in range(2)
    ]
    verification = await tokens.issue(
        db_session,
        purpose=OneTimeTokenPurpose.email_verification,
        user_id=user_id,
        organization_id=org_id,
        ttl_seconds=600,
    )
    theirs = await tokens.issue(
        db_session, purpose=RESET, user_id=other_user, organization_id=None, ttl_seconds=600
    )
    assert await tokens.revoke_for_user(db_session, user_id=user_id, purpose=RESET) == 2
    assert await tokens.revoke_for_user(db_session, user_id=user_id, purpose=RESET) == 0
    for raw in mine:
        assert await tokens.consume(db_session, purpose=RESET, raw_token=raw) is None
    assert (
        await tokens.consume(
            db_session, purpose=OneTimeTokenPurpose.email_verification, raw_token=verification
        )
        is not None
    )
    assert await tokens.consume(db_session, purpose=RESET, raw_token=theirs) is not None


async def test_purge_expired_and_consumed(db_session: AsyncSession, clock: Clock) -> None:
    org_id, user_id = await _seed_user(db_session)

    async def _issue(ttl_seconds: int) -> str:
        return await tokens.issue(
            db_session,
            purpose=RESET,
            user_id=user_id,
            organization_id=org_id,
            ttl_seconds=ttl_seconds,
        )

    clock.now = T0 - timedelta(days=3)
    expired_long_ago = await _issue(86_400)
    consumed_long_ago = await _issue(7 * 86_400)
    await tokens.consume(db_session, purpose=RESET, raw_token=consumed_long_ago)
    clock.now = T0
    active = await _issue(3600)
    consumed_recently = await _issue(3600)
    await tokens.consume(db_session, purpose=RESET, raw_token=consumed_recently)

    assert await tokens.purge_expired(db_session, T0 - timedelta(days=1)) == 2
    session_hashes = set(
        (await db_session.execute(select(AuthOneTimeToken.token_hash))).scalars().all()
    )
    assert tokens.hash_token(expired_long_ago) not in session_hashes
    assert tokens.hash_token(consumed_long_ago) not in session_hashes
    assert {tokens.hash_token(active), tokens.hash_token(consumed_recently)} <= session_hashes
    with pytest.raises(ValueError, match="timezone-aware"):
        await tokens.purge_expired(db_session, datetime(2026, 1, 1))


async def test_registered_raw_token_and_duplicate(db_session: AsyncSession, clock: Clock) -> None:
    org_id, _ = await _seed_user(db_session)
    assertion = OneTimeTokenPurpose.saml_assertion
    saml_id = f"_assertion-{uuid4().hex}"
    returned = await tokens.issue(
        db_session,
        purpose=assertion,
        user_id=None,
        organization_id=org_id,
        ttl_seconds=600,
        raw_token=saml_id,
    )
    assert returned == saml_id
    with pytest.raises(tokens.DuplicateToken) as excinfo:
        await tokens.issue(
            db_session,
            purpose=assertion,
            user_id=None,
            organization_id=org_id,
            ttl_seconds=600,
            raw_token=saml_id,
        )
    assert excinfo.value.purpose == "saml_assertion"
    # The duplicate did not abort the transaction: later statements still run.
    rows = (
        await db_session.execute(
            select(AuthOneTimeToken).where(AuthOneTimeToken.organization_id == org_id)
        )
    ).scalars()
    assert len(list(rows)) == 1


async def test_issue_validates_arguments(db_session: AsyncSession, clock: Clock) -> None:
    common: dict[str, Any] = {"purpose": RESET, "user_id": None, "organization_id": None}
    with pytest.raises(ValueError, match="ttl_seconds"):
        await tokens.issue(db_session, ttl_seconds=0, **common)
    with pytest.raises(ValueError, match="ttl_seconds"):
        await tokens.issue(db_session, ttl_seconds=tokens.MAX_TTL_SECONDS + 1, **common)
    with pytest.raises(ValueError, match="max_attempts"):
        await tokens.issue(db_session, ttl_seconds=60, max_attempts=0, **common)
    with pytest.raises(ValueError, match="raw_token"):
        await tokens.issue(db_session, ttl_seconds=60, raw_token="", **common)
    with pytest.raises(ValueError):
        await tokens.issue(
            db_session, purpose="not_a_purpose", user_id=None, organization_id=None, ttl_seconds=60
        )


async def test_consume_fallback_without_returning(
    db_session: AsyncSession, clock: Clock, monkeypatch: pytest.MonkeyPatch, db_backend: str
) -> None:
    if db_backend != "sqlite":
        pytest.skip("the select-then-update fallback exists for old SQLite builds only")
    monkeypatch.setattr(token_repository, "sqlite_supports_returning", lambda: False)
    org_id, user_id = await _seed_user(db_session)
    raw = await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=60
    )
    token = await tokens.consume(db_session, purpose=RESET, raw_token=raw, user_id=user_id)
    assert token is not None and token.consumed_at is not None
    assert await tokens.consume(db_session, purpose=RESET, raw_token=raw) is None


async def test_fallback_reports_a_lost_race(
    db_session: AsyncSession, clock: Clock, monkeypatch: pytest.MonkeyPatch, db_backend: str
) -> None:
    if db_backend != "sqlite":
        pytest.skip("the select-then-update fallback exists for old SQLite builds only")
    monkeypatch.setattr(token_repository, "sqlite_supports_returning", lambda: False)
    org_id, user_id = await _seed_user(db_session)
    raw = await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=60
    )
    repository = token_repository.OneTimeTokenRepository()
    real_execute = db_session.execute
    calls = {"n": 0}

    async def _execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            # Another consumer won between the select and the update.
            await real_execute(
                AuthOneTimeToken.__table__.update()
                .where(AuthOneTimeToken.token_hash == tokens.hash_token(raw))
                .values(consumed_at=T0)
            )
        return await real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _execute)
    token = await repository.consume(
        db_session, token_hash=tokens.hash_token(raw), purpose="password_reset", now=T0
    )
    assert token is None


async def test_purge_task_uses_the_retention_window(
    db_session: AsyncSession, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id = await _seed_user(db_session)
    clock.now = T0 - timedelta(days=2)
    await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=60
    )
    clock.now = T0
    kept = await tokens.issue(
        db_session, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=60
    )

    @asynccontextmanager
    async def _maintenance() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(account_tasks, "maintenance_session", _maintenance)
    monkeypatch.setattr(settings, "auth_one_time_token_retention_hours", 24)
    result = await account_tasks.purge_expired_tokens(T0)
    assert result == {"purged": 1, "cutoff": (T0 - timedelta(hours=24)).isoformat()}
    hashes = (await db_session.execute(select(AuthOneTimeToken.token_hash))).scalars().all()
    assert list(hashes) == [tokens.hash_token(kept)]


def test_purge_task_is_registered_routed_and_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers.celery_app import BEAT_SCHEDULE, INCLUDE, TASK_ROUTES, celery_app

    assert "app.workers.account_tasks" in INCLUDE
    assert TASK_ROUTES["auth.tokens.purge_expired"]["queue"] == settings.celery_task_default_queue
    assert BEAT_SCHEDULE["auth-tokens-purge-expired"]["task"] == "auth.tokens.purge_expired"
    assert "auth.tokens.purge_expired" in celery_app.tasks
    seen: list[datetime] = []

    async def _fake(now: datetime) -> dict[str, Any]:
        seen.append(now)
        return {"purged": 0}

    monkeypatch.setattr(account_tasks, "purge_expired_tokens", _fake)
    assert account_tasks.purge_expired_tokens_task.run() == {"purged": 0}
    assert seen and seen[0].tzinfo is not None


@pytest.mark.requires_postgres
async def test_concurrent_consumers_win_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as setup:
        org_id, user_id = await _seed_user(setup)
        raw = await tokens.issue(
            setup, purpose=RESET, user_id=user_id, organization_id=org_id, ttl_seconds=600
        )
        await setup.commit()
    try:
        start = asyncio.Event()

        async def _consume() -> bool:
            async with pg_session_factory() as session:
                await session.connection()
                await start.wait()
                token = await tokens.consume(session, purpose=RESET, raw_token=raw)
                await session.commit()
                return token is not None

        racers = [asyncio.create_task(_consume()) for _ in range(2)]
        await asyncio.sleep(0.05)
        start.set()
        results = await asyncio.gather(*racers)
        assert sorted(results) == [False, True]
    finally:
        async with pg_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuthOneTimeToken).where(AuthOneTimeToken.organization_id == org_id)
            )
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup.commit()
