"""Run leases, heartbeats, concurrency caps, and the stale-run sweep (R06-11).

A lease is a conditional ``UPDATE``: the run is ``queued``, or ``running`` with no owner
(released after a long ``Retry-After`` or by the reaper), the same owner (a Celery retry or
redelivery of the same message), or a heartbeat older than
``CONNECTOR_SYNC_STALE_SECONDS``. Every page commit is conditional on the owner, so a
worker that lost its lease stops instead of writing next to the new owner.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, and_, func, literal, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.connector_sync import ConnectorSyncRun
from app.models.enums import ConnectorSyncRunStatus

QUEUED = ConnectorSyncRunStatus.queued.value
RUNNING = ConnectorSyncRunStatus.running.value


class LeaseLostError(Exception):
    """Another worker holds the run now; the current page is rolled back."""


def stale_before(now: datetime) -> datetime:
    return now - timedelta(seconds=settings.connector_sync_stale_seconds)


def _is_postgres(session: AsyncSession) -> bool:
    return bool(session.get_bind().dialect.name == "postgresql")


def _lock_key(kind: str, value: UUID) -> int:
    digest = hashlib.sha256(f"connector_sync_cap:{kind}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _count_leased(
    session: AsyncSession, *, run_id: UUID, column: Any, value: UUID, now: datetime
) -> int:
    result = await session.execute(
        select(func.count(ConnectorSyncRun.id)).where(
            column == value,
            ConnectorSyncRun.id != run_id,
            ConnectorSyncRun.status == RUNNING,
            ConnectorSyncRun.lease_owner.is_not(None),
            ConnectorSyncRun.heartbeat_at >= stale_before(now),
        )
    )
    return int(result.scalar_one())


async def over_cap(session: AsyncSession, run: ConnectorSyncRun, now: datetime) -> str | None:
    """``org_cap`` / ``connection_cap`` when leasing the run would exceed a cap, else None.

    On PostgreSQL a transaction-scoped advisory lock per organization and connection
    serializes concurrent leases, so two workers cannot both take the last slot.
    """
    caps = (
        ("org_cap", "org", settings.connector_sync_max_concurrent_per_org,
         ConnectorSyncRun.organization_id, run.organization_id),
        ("connection_cap", "connection", settings.connector_sync_max_concurrent_per_connection,
         ConnectorSyncRun.connection_id, run.connection_id),
    )  # fmt: skip
    for reason, kind, cap, column, value in caps:
        if cap <= 0:
            continue
        if _is_postgres(session):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(kind, value)}
            )
        if await _count_leased(session, run_id=run.id, column=column, value=value, now=now) >= cap:
            return reason
    return None


async def try_lease(session: AsyncSession, *, run_id: UUID, owner: str, now: datetime) -> bool:
    result = await session.execute(
        update(ConnectorSyncRun)
        .where(
            ConnectorSyncRun.id == run_id,
            or_(
                ConnectorSyncRun.status == QUEUED,
                and_(
                    ConnectorSyncRun.status == RUNNING,
                    or_(
                        ConnectorSyncRun.lease_owner.is_(None),
                        ConnectorSyncRun.lease_owner == owner,
                        ConnectorSyncRun.heartbeat_at.is_(None),
                        ConnectorSyncRun.heartbeat_at < stale_before(now),
                    ),
                ),
            ),
        )
        .values(
            status=RUNNING,
            lease_owner=owner,
            heartbeat_at=now,
            started_at=func.coalesce(
                ConnectorSyncRun.started_at, literal(now, type_=DateTime(timezone=True))
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return bool(getattr(result, "rowcount", 0) == 1)


async def owned_update(
    session: AsyncSession, *, run_id: UUID, owner: str, values: dict[str, Any]
) -> None:
    """Update the run only while ``owner`` holds the lease; raise ``LeaseLostError`` if not."""
    result = await session.execute(
        update(ConnectorSyncRun)
        .where(ConnectorSyncRun.id == run_id, ConnectorSyncRun.lease_owner == owner)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise LeaseLostError(str(run_id))


async def reap_stale_runs(session: AsyncSession, *, now: datetime, limit: int) -> list[Any]:
    """Release running runs whose heartbeat is stale; return (run_id, organization_id) rows.

    The heartbeat is refreshed so a run is re-enqueued at most once per stale interval
    while no worker picks it up. A run deferred for a long ``Retry-After`` has a heartbeat
    in the future and is left alone until then.
    """
    cutoff = stale_before(now)
    last_beat = func.coalesce(
        ConnectorSyncRun.heartbeat_at, ConnectorSyncRun.started_at, ConnectorSyncRun.created_at
    )
    stmt = (
        select(ConnectorSyncRun.id, ConnectorSyncRun.organization_id)
        .where(ConnectorSyncRun.status == RUNNING, last_beat < cutoff)
        .order_by(last_beat.asc())
        .limit(limit)
    )
    if _is_postgres(session):
        stmt = stmt.with_for_update(skip_locked=True)
    rows = list((await session.execute(stmt)).all())
    if rows:
        await session.execute(
            update(ConnectorSyncRun)
            .where(ConnectorSyncRun.id.in_([row[0] for row in rows]))
            .values(lease_owner=None, heartbeat_at=now)
            .execution_options(synchronize_session=False)
        )
    return rows
