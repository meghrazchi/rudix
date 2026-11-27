"""Monthly range-partition helpers on ``created_at`` (R04-09).

No application table is partitioned today: converting ``usage_events`` and the other
append-only tables needs a rehearsal on staging volume and a maintenance window (see
``docs/06_DATABASE_SCHEMA.md``, "Retention and partitioning"). These helpers only act on
tables that are already partitioned (listed in ``pg_partitioned_table``), so the daily
``maintenance.partitions.ensure`` task is a no-op until an operator converts a table with
``scripts/partition_table.py``.

Conventions:

- Partition ``<table>_pYYYYMM`` holds ``[YYYY-MM-01 00:00 UTC, next month 00:00 UTC)``.
- Partitions whose name does not follow the convention (a default partition, hand-made
  ranges) are listed but never created or dropped here.
- Dropping a partition detaches it first. ``DETACH ... CONCURRENTLY`` cannot run inside a
  transaction block, so the plain ``DETACH`` and the ``DROP`` run in the caller's short
  transaction under ``SET LOCAL lock_timeout``; a busy table makes the call fail fast
  instead of queueing traffic behind the lock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger
from app.core.maintenance_metrics import set_partition_missing

DEFAULT_LOCK_TIMEOUT = "5s"
PARTITION_KEY = "created_at"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_LOCK_TIMEOUT = re.compile(r"^\d+(ms|s)$")
MAX_IDENTIFIER_LENGTH = 63

_logger = get_logger("events.maintenance")


def quote_identifier(name: str) -> str:
    """Double-quote a lower-case SQL identifier; reject anything else."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return f'"{name}"'


def lock_timeout_sql(lock_timeout: str = DEFAULT_LOCK_TIMEOUT) -> str:
    if not _LOCK_TIMEOUT.match(lock_timeout):
        raise ValueError(f"invalid lock_timeout: {lock_timeout!r}")
    return f"SET LOCAL lock_timeout = '{lock_timeout}'"


def _as_utc(value: datetime) -> datetime:
    """Aware datetimes are converted to UTC; naive ones are taken as UTC."""
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def month_start(value: date | datetime) -> date:
    """First day of the (UTC) month containing ``value``."""
    if isinstance(value, datetime):
        value = _as_utc(value)
    return date(value.year, value.month, 1)


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + (month.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def months_between(first: date, last: date) -> list[date]:
    """Month starts from ``first`` to ``last`` inclusive."""
    months: list[date] = []
    current = month_start(first)
    end = month_start(last)
    while current <= end:
        months.append(current)
        current = add_months(current, 1)
    return months


def monthly_partition_name(table: str, month: date) -> str:
    name = f"{table}_p{month.year:04d}{month.month:02d}"
    if len(name) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"partition name too long: {name}")
    quote_identifier(name)
    return name


def parse_partition_month(table: str, partition: str) -> date | None:
    match = re.fullmatch(rf"{re.escape(table)}_p(\d{{4}})(\d{{2}})", partition)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def _bound_literal(month: date) -> str:
    return f"'{month.isoformat()} 00:00:00+00'"


def create_partition_sql(table: str, month: date, *, if_not_exists: bool = True) -> str:
    """``CREATE TABLE <table>_pYYYYMM PARTITION OF <table> FOR VALUES FROM .. TO ..``."""
    partition = monthly_partition_name(table, month)
    guard = "IF NOT EXISTS " if if_not_exists else ""
    return (
        f"CREATE TABLE {guard}{quote_identifier(partition)} "
        f"PARTITION OF {quote_identifier(table)} "
        f"FOR VALUES FROM ({_bound_literal(month)}) TO ({_bound_literal(add_months(month, 1))})"
    )


def detach_partition_sql(table: str, partition: str) -> str:
    return f"ALTER TABLE {quote_identifier(table)} DETACH PARTITION {quote_identifier(partition)}"


def drop_table_sql(table: str) -> str:
    return f"DROP TABLE {quote_identifier(table)}"


def _is_postgresql(conn: AsyncConnection) -> bool:
    return conn.dialect.name == "postgresql"


async def is_partitioned(conn: AsyncConnection, table: str) -> bool:
    """True when ``table`` (in the current schema) is a partitioned parent table."""
    if not _is_postgresql(conn):
        return False
    result = await conn.execute(
        text(
            "SELECT 1 FROM pg_partitioned_table p "
            "JOIN pg_class c ON c.oid = p.partrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :table AND n.nspname = current_schema()"
        ),
        {"table": table},
    )
    return result.first() is not None


async def list_partitions(conn: AsyncConnection, table: str) -> list[str]:
    """Names of the direct partitions of ``table`` (via ``pg_inherits``), sorted."""
    if not _is_postgresql(conn):
        return []
    result = await conn.execute(
        text(
            "SELECT child.relname FROM pg_inherits i "
            "JOIN pg_class parent ON parent.oid = i.inhparent "
            "JOIN pg_class child ON child.oid = i.inhrelid "
            "JOIN pg_namespace n ON n.oid = parent.relnamespace "
            "WHERE parent.relname = :table AND n.nspname = current_schema() "
            "ORDER BY child.relname"
        ),
        {"table": table},
    )
    return [str(row[0]) for row in result.all()]


async def partition_missing(conn: AsyncConnection, table: str, month: date) -> bool:
    return monthly_partition_name(table, month) not in await list_partitions(conn, table)


@dataclass(frozen=True)
class EnsureResult:
    table: str
    partitioned: bool
    created: tuple[str, ...] = ()
    next_month_missing: bool = False


async def ensure_future_partitions(
    conn: AsyncConnection,
    table: str,
    *,
    now: datetime,
    months_ahead: int = 1,
    lock_timeout: str = DEFAULT_LOCK_TIMEOUT,
) -> EnsureResult:
    """Create this month's and the next ``months_ahead`` monthly partitions if missing.

    No-op (and no metric sample) for a table that is not partitioned. Sets
    ``rudix_partition_missing{table}`` to whether next month's partition exists afterwards.
    """
    if months_ahead < 0:
        raise ValueError("months_ahead must be >= 0")
    if not await is_partitioned(conn, table):
        return EnsureResult(table=table, partitioned=False)
    existing = set(await list_partitions(conn, table))
    current = month_start(now)
    created: list[str] = []
    for offset in range(months_ahead + 1):
        month = add_months(current, offset)
        name = monthly_partition_name(table, month)
        if name in existing:
            continue
        await conn.execute(text(lock_timeout_sql(lock_timeout)))
        await conn.execute(text(create_partition_sql(table, month)))
        created.append(name)
    next_missing = await partition_missing(conn, table, add_months(current, 1))
    set_partition_missing(table, next_missing)
    if created:
        _logger.info("maintenance.partitions.created", table=table, partitions=created)
    return EnsureResult(
        table=table,
        partitioned=True,
        created=tuple(created),
        next_month_missing=next_missing,
    )


async def report_missing_partition(conn: AsyncConnection, table: str, *, now: datetime) -> bool:
    """Set the gauge for a partitioned table without creating anything; return missing."""
    if not await is_partitioned(conn, table):
        return False
    missing = await partition_missing(conn, table, add_months(month_start(now), 1))
    set_partition_missing(table, missing)
    return missing


async def drop_expired_partitions(
    conn: AsyncConnection,
    table: str,
    *,
    cutoff: datetime,
    lock_timeout: str = DEFAULT_LOCK_TIMEOUT,
) -> list[str]:
    """Detach and drop ``<table>_pYYYYMM`` partitions whose upper bound is <= ``cutoff``.

    Runs in the caller's transaction (``SET LOCAL lock_timeout``); the caller commits.
    """
    if not await is_partitioned(conn, table):
        return []
    cutoff_utc = _as_utc(cutoff)
    dropped: list[str] = []
    for partition in await list_partitions(conn, table):
        month = parse_partition_month(table, partition)
        if month is None:
            continue
        upper = add_months(month, 1)
        if datetime(upper.year, upper.month, 1, tzinfo=UTC) > cutoff_utc:
            continue
        await conn.execute(text(lock_timeout_sql(lock_timeout)))
        await conn.execute(text(detach_partition_sql(table, partition)))
        await conn.execute(text(drop_table_sql(partition)))
        dropped.append(partition)
    if dropped:
        _logger.info("maintenance.partitions.dropped", table=table, partitions=dropped)
    return dropped
