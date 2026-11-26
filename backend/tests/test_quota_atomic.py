"""R02-07: atomic quota accounting on SQLite (upsert increment + conditional reset)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  # register all mappers
from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.quota_service import (
    check_quota,
    get_quota_dashboard,
    increment_quota_usage,
)
from app.models.organization import Organization
from app.models.quotas import OrgQuotaUsage

pytestmark = pytest.mark.both_dialects

QT = QuotaType.questions.value


async def _org(db_session: AsyncSession) -> Organization:
    org = Organization(name="Atomic quota org", slug=f"atomic-quota-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    return org


async def _seed(
    db_session: AsyncSession,
    org: Organization,
    *,
    value: int,
    next_reset_at: datetime | None,
) -> OrgQuotaUsage:
    usage = OrgQuotaUsage(
        organization_id=org.id,
        quota_type=QT,
        current_value=value,
        next_reset_at=next_reset_at,
    )
    db_session.add(usage)
    await db_session.flush()
    return usage


async def test_first_increment_creates_row_and_second_adds(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    repo = QuotaRepository()
    reset_at = datetime.now(UTC) + timedelta(days=1)

    first = await repo.increment_usage(
        db_session, organization_id=org.id, quota_type=QT, amount=3, next_reset_at=reset_at
    )
    assert first.current_value == 3
    assert first.next_reset_at is not None

    second = await repo.increment_usage(db_session, organization_id=org.id, quota_type=QT, amount=4)
    assert second.current_value == 7
    assert second.id == first.id
    # next_reset_at is untouched on conflict
    assert second.next_reset_at is not None

    rows = (
        (
            await db_session.execute(
                select(OrgQuotaUsage).where(OrgQuotaUsage.organization_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_negative_amount_floors_at_zero(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    repo = QuotaRepository()

    created = await repo.increment_usage(
        db_session, organization_id=org.id, quota_type=QT, amount=-5
    )
    assert created.current_value == 0

    await repo.increment_usage(db_session, organization_id=org.id, quota_type=QT, amount=2)
    floored = await repo.increment_usage(
        db_session, organization_id=org.id, quota_type=QT, amount=-10
    )
    assert floored.current_value == 0


async def test_increment_refreshes_stale_identity_map_object(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    loaded = await _seed(db_session, org, value=5, next_reset_at=None)
    repo = QuotaRepository()

    returned = await repo.increment_usage(
        db_session, organization_id=org.id, quota_type=QT, amount=2
    )

    assert returned is loaded
    assert loaded.current_value == 7


async def test_increment_rejects_unsupported_dialect() -> None:
    fake_session: Any = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    )
    with pytest.raises(RuntimeError, match="mysql"):
        await QuotaRepository().increment_usage(
            fake_session, organization_id=uuid4(), quota_type=QT, amount=1
        )


async def test_reset_usage_skips_future_window(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    usage = await _seed(db_session, org, value=9, next_reset_at=now + timedelta(hours=1))

    reset = await QuotaRepository().reset_usage(
        db_session, usage, next_reset_at=now + timedelta(days=1), now=now
    )

    assert reset is False
    assert usage.current_value == 9


async def test_reset_usage_skips_permanent_cap(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    usage = await _seed(db_session, org, value=9, next_reset_at=None)

    reset = await QuotaRepository().reset_usage(
        db_session, usage, next_reset_at=now + timedelta(days=1), now=now
    )

    assert reset is False
    assert usage.current_value == 9
    assert usage.next_reset_at is None


async def test_reset_usage_zeroes_expired_window_once(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    usage = await _seed(db_session, org, value=9, next_reset_at=now - timedelta(minutes=1))
    repo = QuotaRepository()
    new_reset = now + timedelta(days=1)

    assert await repo.reset_usage(db_session, usage, next_reset_at=new_reset, now=now) is True
    assert usage.current_value == 0
    assert usage.next_reset_at is not None

    # A second reset in the same window is a no-op.
    await repo.increment_usage(db_session, organization_id=org.id, quota_type=QT, amount=1)
    assert await repo.reset_usage(db_session, usage, next_reset_at=new_reset, now=now) is False
    assert usage.current_value == 1


async def test_check_quota_after_expired_window_reports_real_value(
    db_session: AsyncSession,
) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    usage = await _seed(db_session, org, value=50, next_reset_at=now - timedelta(minutes=1))

    # Simulate another request that already reset the window and incremented: the row in
    # the database is current, but the identity map still holds the stale expired object.
    await db_session.execute(
        update(OrgQuotaUsage)
        .where(OrgQuotaUsage.id == usage.id)
        .values(current_value=4, next_reset_at=now + timedelta(days=1))
        .execution_options(synchronize_session=False)
    )
    assert usage.current_value == 50

    result = await check_quota(db_session, organization_id=org.id, quota_type=QuotaType.questions)

    assert result.current_value == 4
    assert result.next_reset_at is not None
    assert result.next_reset_at > now


async def test_check_quota_resets_expired_window(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    await _seed(db_session, org, value=50, next_reset_at=now - timedelta(minutes=1))

    result = await check_quota(db_session, organization_id=org.id, quota_type=QuotaType.questions)

    assert result.current_value == 0
    assert result.next_reset_at is not None
    assert result.next_reset_at > now


async def test_increment_quota_usage_returns_new_value_and_resets(
    db_session: AsyncSession,
) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    await _seed(db_session, org, value=100, next_reset_at=now - timedelta(minutes=1))

    value = await increment_quota_usage(
        db_session, organization_id=org.id, quota_type=QuotaType.questions, amount=2
    )
    assert value == 2

    value = await increment_quota_usage(
        db_session, organization_id=org.id, quota_type=QuotaType.questions
    )
    assert value == 3


async def test_increment_quota_usage_creates_row_with_window(db_session: AsyncSession) -> None:
    org = await _org(db_session)

    value = await increment_quota_usage(
        db_session, organization_id=org.id, quota_type=QuotaType.questions
    )

    assert value == 1
    usage = await QuotaRepository().get_usage(db_session, organization_id=org.id, quota_type=QT)
    assert usage is not None
    assert usage.next_reset_at is not None


async def test_increment_quota_usage_seats_returns_none(db_session: AsyncSession) -> None:
    org = await _org(db_session)

    value = await increment_quota_usage(
        db_session, organization_id=org.id, quota_type=QuotaType.seats
    )

    assert value is None


async def test_dashboard_resets_expired_window(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    now = datetime.now(UTC)
    await _seed(db_session, org, value=12, next_reset_at=now - timedelta(minutes=1))

    dashboard = await get_quota_dashboard(db_session, organization_id=org.id)

    item = next(i for i in dashboard.quota_usage if i.quota_type == QT)
    assert item.current_value == 0
    assert item.next_reset_at is not None
    assert item.next_reset_at > now
