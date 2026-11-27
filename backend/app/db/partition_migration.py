"""Operator-run conversion of a table to monthly range partitions (R04-09).

Used by ``scripts/partition_table.py``; never applied automatically. Steps:

1. ``create_shadow``: ``<t>_partitioned`` with the same columns, defaults, checks, outbound
   foreign keys, indexes, row-level security policies and grants, primary key
   ``(id, created_at)``, and monthly partitions named ``<t>_pYYYYMM`` covering the existing
   rows through next month. Also builds ``(created_at, id)`` on ``t`` concurrently, as the
   backfill cursor index. The shadow's table comment records when it was created.
2. ``backfill``: copies rows in ``(created_at, id)`` order, one committed batch at a time,
   ``ON CONFLICT DO NOTHING``. It resumes from the newest row already in the shadow.
3. ``swap``: one transaction under ``lock_timeout`` and ``ACCESS EXCLUSIVE`` locks: copies the
   delta (new rows, and rows updated since the shadow was created), checks the row counts,
   renames ``t`` to ``<t>_legacy_<yyyymm>`` and the shadow to ``t``, and moves index and
   constraint names. The legacy table is kept for one release.
4. ``verify``: per-month row counts and checksums of two tables.

Preconditions (checked by ``plan``/``swap``): ``id`` and ``created_at`` columns, no foreign
key referencing ``t`` (a partitioned table can only be referenced through its full primary
key), and retention deletes paused (``RETENTION_ENABLED=false``) for the duration, because
rows deleted from ``t`` after the backfill copied them make the count check fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.partitioning import (
    DEFAULT_LOCK_TIMEOUT,
    MAX_IDENTIFIER_LENGTH,
    add_months,
    create_partition_sql,
    lock_timeout_sql,
    month_start,
    months_between,
    quote_identifier,
)

SHADOW_COMMENT_PREFIX = "rudix:partition-shadow since="
UPDATE_MARGIN = timedelta(hours=1)
_INDEX_DEF = re.compile(r"^CREATE (UNIQUE )?INDEX (\S+) ON (?:ONLY )?(\S+) USING (.+)$")


class PartitionMigrationError(RuntimeError):
    """A precondition of the conversion does not hold; nothing was changed."""


def suffixed(name: str, suffix: str) -> str:
    """``name + suffix`` truncated to the PostgreSQL identifier limit."""
    return name[: MAX_IDENTIFIER_LENGTH - len(suffix)] + suffix


def shadow_name(table: str) -> str:
    return suffixed(table, "_partitioned")


def legacy_name(table: str, now: datetime) -> str:
    return suffixed(table, f"_legacy_{now:%Y%m}")


def cursor_index_name(table: str) -> str:
    return suffixed(table, "_backfill_cursor")


@dataclass(frozen=True)
class IndexInfo:
    name: str
    definition: str
    unique: bool
    primary: bool


@dataclass
class TableInfo:
    table: str
    columns: list[str]
    primary_key: str | None
    indexes: list[IndexInfo] = field(default_factory=list)
    outbound_fks: list[tuple[str, str]] = field(default_factory=list)
    inbound_fks: list[tuple[str, str]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)
    rls_enabled: bool = False
    rls_forced: bool = False
    grants: list[tuple[str, str]] = field(default_factory=list)
    min_created_at: datetime | None = None
    max_created_at: datetime | None = None
    estimated_rows: int = 0

    @property
    def blockers(self) -> list[str]:
        problems: list[str] = []
        for required in ("id", "created_at"):
            if required not in self.columns:
                problems.append(f"missing column {required}")
        for source, name in self.inbound_fks:
            problems.append(f"foreign key {name} on {source} references {self.table}")
        return problems


async def _rows(conn: AsyncConnection, sql: str, **params: Any) -> list[Any]:
    return list((await conn.execute(text(sql), params)).all())


async def inspect_table(conn: AsyncConnection, table: str) -> TableInfo:
    quote_identifier(table)
    columns = await _rows(
        conn,
        "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) "
        "AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
        t=table,
    )
    indexes = await _rows(
        conn,
        "SELECT c.relname, pg_get_indexdef(i.indexrelid), i.indisunique, i.indisprimary "
        "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE i.indrelid = CAST(:t AS regclass) ORDER BY c.relname",
        t=table,
    )
    pk = await _rows(
        conn,
        "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'p'",
        t=table,
    )
    outbound = await _rows(
        conn,
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = CAST(:t AS regclass) AND contype = 'f' ORDER BY conname",
        t=table,
    )
    inbound = await _rows(
        conn,
        "SELECT conrelid::regclass::text, conname FROM pg_constraint "
        "WHERE confrelid = CAST(:t AS regclass) AND contype = 'f' ORDER BY conname",
        t=table,
    )
    policies = await _rows(
        conn,
        "SELECT policyname, permissive, roles, cmd, qual, with_check FROM pg_policies "
        "WHERE schemaname = current_schema() AND tablename = :t ORDER BY policyname",
        t=table,
    )
    rls = await _rows(
        conn,
        "SELECT relrowsecurity, relforcerowsecurity, reltuples::bigint FROM pg_class "
        "WHERE oid = CAST(:t AS regclass)",
        t=table,
    )
    grants = await _rows(
        conn,
        "SELECT grantee, privilege_type FROM information_schema.role_table_grants g "
        "WHERE g.table_schema = current_schema() AND g.table_name = :t AND g.grantee <> "
        "(SELECT tableowner FROM pg_tables WHERE schemaname = current_schema() "
        "AND tablename = :t) ORDER BY grantee, privilege_type",
        t=table,
    )
    info = TableInfo(
        table=table,
        columns=[str(row[0]) for row in columns],
        primary_key=str(pk[0][0]) if pk else None,
        indexes=[IndexInfo(str(r[0]), str(r[1]), bool(r[2]), bool(r[3])) for r in indexes],
        outbound_fks=[(str(r[0]), str(r[1])) for r in outbound],
        inbound_fks=[(str(r[0]), str(r[1])) for r in inbound],
        policies=[dict(r._mapping) for r in policies],
        rls_enabled=bool(rls[0][0]),
        rls_forced=bool(rls[0][1]),
        estimated_rows=max(int(rls[0][2]), 0),
        grants=[(str(r[0]), str(r[1])) for r in grants],
    )
    if "created_at" in info.columns:
        bounds = await _rows(
            conn, f"SELECT min(created_at), max(created_at) FROM {quote_identifier(table)}"
        )
        info.min_created_at, info.max_created_at = bounds[0][0], bounds[0][1]
    return info


def _role_list(roles: Any) -> str:
    names = list(roles) if not isinstance(roles, str) else roles.strip("{}").split(",")
    return ", ".join("PUBLIC" if r.lower() == "public" else quote_identifier(r) for r in names)


def _policy_sql(policy: dict[str, Any], target: str) -> str:
    sql = (
        f"CREATE POLICY {quote_identifier(str(policy['policyname']))} ON "
        f"{quote_identifier(target)} AS {policy['permissive']} FOR {policy['cmd']} "
        f"TO {_role_list(policy['roles'])}"
    )
    if policy.get("qual"):
        sql += f" USING ({policy['qual']})"
    if policy.get("with_check"):
        sql += f" WITH CHECK ({policy['with_check']})"
    return sql


def _index_sql(index: IndexInfo, target: str) -> str | None:
    match = _INDEX_DEF.match(index.definition)
    if match is None:
        return None
    unique = match.group(1) or ""
    return (
        f"CREATE {unique}INDEX {quote_identifier(suffixed(index.name, '_sh'))} "
        f"ON {quote_identifier(target)} USING {match.group(4)}"
    )


def skipped_indexes(info: TableInfo) -> list[str]:
    """Unique indexes without ``created_at`` cannot exist on the partitioned table."""
    return [
        index.name
        for index in info.indexes
        if not index.primary and index.unique and "created_at" not in index.definition
    ]


def partition_months(info: TableInfo, *, now: datetime, months_ahead: int = 1) -> list[date]:
    first = month_start(info.min_created_at or now)
    last = max(month_start(info.max_created_at or now), month_start(now))
    return months_between(first, add_months(last, months_ahead))


def build_create_shadow_sql(
    info: TableInfo, *, now: datetime, months_ahead: int = 1, since: datetime | None = None
) -> list[str]:
    """Transactional DDL for the shadow table (the cursor index is built separately).

    ``since`` (default ``now``) is the database clock at creation; the swap re-copies rows
    whose ``updated_at`` is at or after it (minus a margin).
    """
    if info.blockers:
        raise PartitionMigrationError("; ".join(info.blockers))
    table, shadow = info.table, shadow_name(info.table)
    pk_name = suffixed(info.primary_key or f"pk_{table}", "_sh")
    statements = [
        f"CREATE TABLE {quote_identifier(shadow)} (LIKE {quote_identifier(table)} "
        "INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING GENERATED INCLUDING STORAGE) "
        "PARTITION BY RANGE (created_at)",
        f"ALTER TABLE {quote_identifier(shadow)} ADD CONSTRAINT {quote_identifier(pk_name)} "
        "PRIMARY KEY (id, created_at)",
    ]
    skipped = set(skipped_indexes(info))
    for index in info.indexes:
        if index.primary or index.name in skipped or index.name == cursor_index_name(table):
            continue
        sql = _index_sql(index, shadow)
        if sql is not None:
            statements.append(sql)
    for name, definition in info.outbound_fks:
        statements.append(
            f"ALTER TABLE {quote_identifier(shadow)} ADD CONSTRAINT "
            f"{quote_identifier(suffixed(name, '_sh'))} {definition}"
        )
    if info.rls_enabled:
        statements.append(f"ALTER TABLE {quote_identifier(shadow)} ENABLE ROW LEVEL SECURITY")
    if info.rls_forced:
        statements.append(f"ALTER TABLE {quote_identifier(shadow)} FORCE ROW LEVEL SECURITY")
    statements.extend(_policy_sql(policy, shadow) for policy in info.policies)
    for grantee, privilege in info.grants:
        target = "PUBLIC" if grantee.upper() == "PUBLIC" else quote_identifier(grantee)
        statements.append(f"GRANT {privilege} ON {quote_identifier(shadow)} TO {target}")
    for month in partition_months(info, now=now, months_ahead=months_ahead):
        statements.append(create_partition_sql(table, month, parent=shadow))
    marker = (since or now).astimezone(UTC).isoformat()
    statements.append(
        f"COMMENT ON TABLE {quote_identifier(shadow)} IS '{SHADOW_COMMENT_PREFIX}{marker}'"
    )
    return statements


def cursor_index_sql(table: str) -> str:
    return (
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {quote_identifier(cursor_index_name(table))} "
        f"ON {quote_identifier(table)} (created_at, id)"
    )


async def create_shadow(
    engine: AsyncEngine, table: str, *, now: datetime, months_ahead: int = 1
) -> list[str]:
    """Create the shadow table and the cursor index; return the statements run."""
    async with engine.begin() as conn:
        info = await inspect_table(conn, table)
        db_clock = (await conn.execute(text("SELECT now()"))).scalar_one()
        statements = build_create_shadow_sql(
            info, now=now, months_ahead=months_ahead, since=db_clock
        )
        for statement in statements:
            await conn.execute(text(statement))
    async with engine.connect() as conn:
        autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(cursor_index_sql(table)))
    return [*statements, cursor_index_sql(table)]


def _column_list(columns: list[str]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def backfill_batch_sql(table: str, columns: list[str], *, first: bool) -> str:
    cols = _column_list(columns)
    where = "TRUE" if first else "(created_at, id) > (:last_created_at, :last_id)"
    return (
        f"WITH batch AS (SELECT {cols} FROM {quote_identifier(table)} WHERE {where} "
        "ORDER BY created_at, id LIMIT :batch_size), "
        f"ins AS (INSERT INTO {quote_identifier(shadow_name(table))} ({cols}) "
        f"SELECT {cols} FROM batch ON CONFLICT DO NOTHING) "
        "SELECT created_at, id, (SELECT count(*) FROM batch) FROM batch "
        "ORDER BY created_at DESC, id DESC LIMIT 1"
    )


async def _shadow_cursor(conn: AsyncConnection, table: str) -> tuple[datetime, Any] | None:
    rows = await _rows(
        conn,
        f"SELECT created_at, id FROM {quote_identifier(shadow_name(table))} "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
    )
    return (rows[0][0], rows[0][1]) if rows else None


@dataclass
class BackfillResult:
    rows_copied: int = 0
    batches: int = 0
    complete: bool = False


async def backfill(
    engine: AsyncEngine, table: str, *, batch_size: int, max_batches: int | None = None
) -> BackfillResult:
    """Copy rows into the shadow in committed batches; resumable from the shadow's max."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    result = BackfillResult()
    async with engine.connect() as conn:
        columns = (await inspect_table(conn, table)).columns
        cursor = await _shadow_cursor(conn, table)
        await conn.rollback()
    while max_batches is None or result.batches < max_batches:
        params: dict[str, Any] = {"batch_size": batch_size}
        if cursor is not None:
            params.update(last_created_at=cursor[0], last_id=cursor[1])
        sql = backfill_batch_sql(table, columns, first=cursor is None)
        async with engine.begin() as conn:
            rows = await _rows(conn, sql, **params)
        if not rows:
            result.complete = True
            break
        cursor = (rows[0][0], rows[0][1])
        result.rows_copied += int(rows[0][2])
        result.batches += 1
        if int(rows[0][2]) < batch_size:
            result.complete = True
            break
    return result


async def _shadow_since(conn: AsyncConnection, table: str) -> datetime:
    rows = await _rows(
        conn,
        "SELECT obj_description(CAST(:t AS regclass), 'pg_class')",
        t=shadow_name(table),
    )
    comment = str(rows[0][0] or "") if rows else ""
    if not comment.startswith(SHADOW_COMMENT_PREFIX):
        raise PartitionMigrationError(f"{shadow_name(table)} has no shadow marker comment")
    return datetime.fromisoformat(comment.removeprefix(SHADOW_COMMENT_PREFIX))


def _rename_index_sql(old: str, new: str) -> str:
    return f"ALTER INDEX {quote_identifier(old)} RENAME TO {quote_identifier(new)}"


def _rename_constraint_sql(table: str, old: str, new: str) -> str:
    return (
        f"ALTER TABLE {quote_identifier(table)} RENAME CONSTRAINT {quote_identifier(old)} "
        f"TO {quote_identifier(new)}"
    )


def build_swap_rename_sql(info: TableInfo, *, now: datetime) -> list[str]:
    table, shadow, legacy = info.table, shadow_name(info.table), legacy_name(info.table, now)
    tag = f"_l{now:%Y%m}"
    statements = [
        f"ALTER TABLE {quote_identifier(table)} RENAME TO {quote_identifier(legacy)}",
        f"ALTER TABLE {quote_identifier(shadow)} RENAME TO {quote_identifier(table)}",
    ]
    skipped = set(skipped_indexes(info))
    for index in info.indexes:
        if index.primary or index.name == cursor_index_name(table):
            continue
        statements.append(_rename_index_sql(index.name, suffixed(index.name, tag)))
        if index.name not in skipped:
            statements.append(_rename_index_sql(suffixed(index.name, "_sh"), index.name))
    if info.primary_key:
        statements.append(
            _rename_constraint_sql(legacy, info.primary_key, suffixed(info.primary_key, tag))
        )
        statements.append(
            _rename_constraint_sql(table, suffixed(info.primary_key, "_sh"), info.primary_key)
        )
    for name, _ in info.outbound_fks:
        statements.append(_rename_constraint_sql(legacy, name, suffixed(name, tag)))
        statements.append(_rename_constraint_sql(table, suffixed(name, "_sh"), name))
    statements.append(f"COMMENT ON TABLE {quote_identifier(table)} IS NULL")
    return statements


async def swap(
    engine: AsyncEngine,
    table: str,
    *,
    now: datetime,
    lock_timeout: str = DEFAULT_LOCK_TIMEOUT,
) -> str:
    """Copy the delta and swap names in one transaction; return the legacy table name."""
    shadow = shadow_name(table)
    async with engine.begin() as conn:
        info = await inspect_table(conn, table)
        if info.blockers:
            raise PartitionMigrationError("; ".join(info.blockers))
        since = await _shadow_since(conn, table) - UPDATE_MARGIN
        await conn.execute(text(lock_timeout_sql(lock_timeout)))
        await conn.execute(text(f"LOCK TABLE {quote_identifier(table)} IN ACCESS EXCLUSIVE MODE"))
        await conn.execute(text(f"LOCK TABLE {quote_identifier(shadow)} IN ACCESS EXCLUSIVE MODE"))
        cursor = await _shadow_cursor(conn, table)
        if cursor is not None:
            await conn.execute(
                text(backfill_batch_sql(table, info.columns, first=False)),
                {"last_created_at": cursor[0], "last_id": cursor[1], "batch_size": None},
            )
        else:
            await conn.execute(
                text(backfill_batch_sql(table, info.columns, first=True)), {"batch_size": None}
            )
        if "updated_at" in info.columns:
            cols = _column_list(info.columns)
            updates = ", ".join(
                f"{quote_identifier(c)} = EXCLUDED.{quote_identifier(c)}"
                for c in info.columns
                if c not in {"id", "created_at"}
            )
            await conn.execute(
                text(
                    f"INSERT INTO {quote_identifier(shadow)} ({cols}) SELECT {cols} FROM "
                    f"{quote_identifier(table)} WHERE updated_at >= :since "
                    f"ON CONFLICT (id, created_at) DO UPDATE SET {updates}"
                ),
                {"since": since},
            )
        counts = await _rows(
            conn,
            f"SELECT (SELECT count(*) FROM {quote_identifier(table)}), "
            f"(SELECT count(*) FROM {quote_identifier(shadow)})",
        )
        if counts[0][0] != counts[0][1]:
            raise PartitionMigrationError(
                f"row counts differ ({table}={counts[0][0]}, {shadow}={counts[0][1]}); "
                "were rows deleted during the backfill? Nothing was swapped."
            )
        for statement in build_swap_rename_sql(info, now=now):
            await conn.execute(text(statement))
    return legacy_name(table, now)


def month_checksum_sql(table: str) -> str:
    return (
        "SELECT to_char(date_trunc('month', created_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS m, "
        "count(*), md5(string_agg(md5(x::text), '' ORDER BY id)) "
        f"FROM {quote_identifier(table)} x GROUP BY 1 ORDER BY 1"
    )


async def month_checksums(conn: AsyncConnection, table: str) -> dict[str, tuple[int, str]]:
    rows = await _rows(conn, month_checksum_sql(table))
    return {str(r[0]): (int(r[1]), str(r[2])) for r in rows}


async def verify(engine: AsyncEngine, table: str, other: str) -> list[str]:
    """Months whose row count or checksum differs between two tables (empty = identical)."""
    async with engine.connect() as conn:
        left = await month_checksums(conn, table)
        right = await month_checksums(conn, other)
    return sorted(m for m in set(left) | set(right) if left.get(m) != right.get(m))
