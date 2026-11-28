"""Read-replica routing for staleness-tolerant reporting routes (0.8.0, R08-04).

A reporting request (plan section 3: ``GET /admin/usage/dashboard``, the F353
``GET /admin/usage-adoption/*`` reads, ``GET /reports``, ``GET /reports/answer-quality``)
asks :func:`reporting_session` for a session. It routes to the replica only when
``DATABASE_REPLICA_URL`` is set and the last lag sample is fresh and at most
``DB_REPLICA_MAX_LAG_SECONDS``; otherwise it hands back the request's primary session.

Lag is sampled on demand, not by a background task: when a reporting session is requested
and the last sample is older than ``DB_REPLICA_LAG_CHECK_INTERVAL_SECONDS``, one query runs
on the replica with a statement timeout (``DB_REPLICA_LAG_QUERY_TIMEOUT_MS``, which also
bounds the connection checkout). A failed or timed-out sample routes to the primary until the
next interval. Each sample sets ``rudix_db_replica_lag_seconds``; each decision increments
``rudix_db_replica_routed_total{target,reason}``.

The replica session is read-only (``default_transaction_read_only`` on the connection, or
``SET TRANSACTION READ ONLY`` per transaction in PgBouncer mode) and is bound to the same
tenant as the primary session, so the RLS session-context statement runs on it too. Its
connection is checked out before the handler runs, within the lag query timeout; a replica
that fails between two samples sends the request to the primary (``sample_failed``) and marks
the sample failed for the rest of the interval.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_db_replica import RouteReason, RouteTarget, record_replica_route
from app.core.metrics_infra import set_db_replica_lag_seconds
from app.db.session import (
    READ_ONLY_TRANSACTION_INFO_KEY,
    ReportingSessionLocal,
    get_reporting_engine,
)
from app.db.tenant_context import bind_session_tenant

LAG_QUERY = (
    "SELECT CASE WHEN pg_is_in_recovery() THEN "
    "CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0 "
    "ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp()) END "
    "ELSE 0 END"
)

_logger = get_logger("db.replica")


@dataclass(frozen=True)
class LagSample:
    """One lag measurement; ``lag_seconds`` is None when the sample failed."""

    lag_seconds: float | None
    sampled_at: float


@dataclass(frozen=True)
class RouteDecision:
    target: RouteTarget
    reason: RouteReason


def parse_lag(value: Any) -> float | None:
    """Lag in seconds from the query result; None when it is missing or not a number.

    NULL happens on a standby that has not replayed a transaction yet: the lag is unknown,
    so the caller treats it as a failed sample. Negative values (clock skew) become 0.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        lag = float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None
    if lag != lag or lag in (float("inf"), float("-inf")):
        return None
    return max(0.0, lag)


def decide_route(
    *,
    replica_configured: bool,
    sample: LagSample | None,
    now: float,
    max_lag_seconds: float,
    check_interval_seconds: float,
) -> RouteDecision:
    """Pure routing decision; the replica only with a fresh, successful, small-lag sample."""
    if not replica_configured:
        return RouteDecision("primary", "replica_unset")
    if sample is None or sample.lag_seconds is None:
        return RouteDecision("primary", "sample_failed")
    if now - sample.sampled_at > check_interval_seconds:
        # A stale sample says nothing about the replica now.
        return RouteDecision("primary", "sample_failed")
    if sample.lag_seconds > max_lag_seconds:
        return RouteDecision("primary", "lag_exceeded")
    return RouteDecision("replica", "ok")


class ReplicaLagSampler:
    """Caches the last lag sample; one sample at a time per event loop."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sample: LagSample | None = None
        self._locks: dict[int, asyncio.Lock] = {}

    @property
    def last_sample(self) -> LagSample | None:
        return self._sample

    def now(self) -> float:
        return self._clock()

    def reset(self) -> None:
        self._sample = None
        self._locks.clear()

    def mark_failed(self) -> None:
        """Record a failed sample now, so requests use the primary until the next interval."""
        self._sample = LagSample(lag_seconds=None, sampled_at=self._clock())

    def _is_stale(self, now: float) -> bool:
        if self._sample is None:
            return True
        return now - self._sample.sampled_at > settings.db_replica_lag_check_interval_seconds

    def _lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        lock = self._locks.get(loop_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[loop_id] = lock
        return lock

    async def current(self, engine: AsyncEngine) -> LagSample:
        """The last sample, refreshed first when it is older than the check interval."""
        if not self._is_stale(self._clock()) and self._sample is not None:
            return self._sample
        async with self._lock():
            if self._is_stale(self._clock()) or self._sample is None:
                self._sample = await self._take_sample(engine)
        return self._sample

    async def _take_sample(self, engine: AsyncEngine) -> LagSample:
        timeout_ms = settings.db_replica_lag_query_timeout_ms
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                lag = await query_replica_lag(engine, timeout_ms)
        except Exception as exc:
            lag = None
            _logger.warning("db.replica.lag_sample_failed", error_type=type(exc).__name__)
        else:
            if lag is None:
                _logger.warning("db.replica.lag_sample_failed", error_type="unknown_lag")
        if lag is not None:
            set_db_replica_lag_seconds(lag)
        return LagSample(lag_seconds=lag, sampled_at=self._clock())


async def query_replica_lag(engine: AsyncEngine, timeout_ms: int) -> float | None:
    """Run the lag query on ``engine`` with a transaction-local statement timeout."""
    async with engine.connect() as connection:
        await connection.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        result = await connection.execute(text(LAG_QUERY))
        value = result.scalar()
        await connection.rollback()
    return parse_lag(value)


lag_sampler = ReplicaLagSampler()


async def _decide_reporting_target() -> RouteDecision:
    """Sample lag when needed and decide; the caller counts the final decision."""
    engine = get_reporting_engine()
    sample = await lag_sampler.current(engine) if engine is not None else None
    return decide_route(
        replica_configured=engine is not None,
        sample=sample,
        now=lag_sampler.now(),
        max_lag_seconds=settings.db_replica_max_lag_seconds,
        check_interval_seconds=settings.db_replica_lag_check_interval_seconds,
    )


def _count(decision: RouteDecision) -> None:
    record_replica_route(decision.target, decision.reason)
    if decision.target == "primary" and decision.reason != "replica_unset":
        sample = lag_sampler.last_sample
        _logger.debug(
            "db.replica.fallback",
            reason=decision.reason,
            lag_seconds=sample.lag_seconds if sample is not None else None,
        )


async def choose_reporting_target() -> RouteDecision:
    """Sample lag when needed, decide, and count the decision."""
    decision = await _decide_reporting_target()
    _count(decision)
    return decision


async def _connect_replica(session: AsyncSession) -> bool:
    """Open the replica session's transaction within the lag query timeout.

    The replica can fail between two samples (restart, failover). Checking out the
    connection before the handler runs lets the request fall back to the primary instead of
    failing; the failure also marks the sample failed, so the next requests of the interval
    skip the replica without waiting for the timeout.
    """
    try:
        async with asyncio.timeout(settings.db_replica_lag_query_timeout_ms / 1000):
            await session.connection()
    except Exception as exc:
        _logger.warning("db.replica.connect_failed", error_type=type(exc).__name__)
        lag_sampler.mark_failed()
        return False
    return True


@asynccontextmanager
async def reporting_session(primary: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A read-only replica session bound to ``primary``'s tenant, or ``primary`` itself."""
    decision = await _decide_reporting_target()
    if decision.target == "replica":
        async with ReportingSessionLocal() as replica:
            bind_session_tenant(
                replica,
                primary.info.get("organization_id"),
                enforce_guard=bool(primary.info.get("enforce_tenant_guard", False)),
            )
            if await _connect_replica(replica):
                _count(decision)
                # Opening the transaction ran the after_begin listeners: the tenant's
                # session-context statement (tenant_context) and, in PgBouncer mode,
                # SET TRANSACTION READ ONLY. Later transactions get them the same way.
                yield replica
                return
        decision = RouteDecision("primary", "sample_failed")
    _count(decision)
    yield primary


def _on_after_begin_read_only(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """PgBouncer mode: startup parameters are ignored, so mark each transaction read-only."""
    if not session.info.get(READ_ONLY_TRANSACTION_INFO_KEY, False):
        return
    if transaction.nested or connection.dialect.name != "postgresql":
        return
    connection.execute(text("SET TRANSACTION READ ONLY"))


_READ_ONLY_GUARD_INSTALLED = False


def install_read_only_guard() -> None:
    """Idempotently register the read-only ``after_begin`` listener on ``Session``."""
    global _READ_ONLY_GUARD_INSTALLED
    if _READ_ONLY_GUARD_INSTALLED:
        return
    event.listen(Session, "after_begin", _on_after_begin_read_only)
    _READ_ONLY_GUARD_INSTALLED = True


install_read_only_guard()
