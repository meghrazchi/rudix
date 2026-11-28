"""Verify a restored PostgreSQL database (R08-04, contract 5.2.10).

Checks, in order, against any PostgreSQL URL (a scratch restore, a PITR clone, a replica):

1. ``alembic_version`` equals the expected head (default: the single head of the migration
   scripts shipped with this code).
2. The required tables exist: every table of the RLS lists in ``app/db/rls.py``, the
   identity and pending tables, and a few core tables.
3. Row-level security is enabled and ``tenant_isolation_policy`` exists on every table of
   ``TENANT_RLS_TABLES``, ``RLS_LOOKUP_TABLES``, and ``RLS_STRICT_TABLES``.
4. Every required table has a primary key, and the key indexes exist and are valid.
5. Optional manifest row-count floors (``{"row_count_floors": {"documents": 100}}``).

Output names tables and counts only: never row data, the URL, or credentials. Connect as a
role that is not subject to RLS (the table owner or ``rudix_maintenance``) or the row
counts read zero.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import asyncpg  # type: ignore[import-untyped]

from app.db import rls

BACKEND_DIR: Final[Path] = Path(__file__).resolve().parents[2]

CORE_TABLES: Final[tuple[str, ...]] = (
    "organizations",
    "chat_messages",
    "document_chunks",
    "vector_index_generations",
)
KEY_INDEXES: Final[tuple[str, ...]] = (
    "uq_users_email",
    "uq_api_keys_key_hash",
    "idx_organization_members_user",
    "idx_documents_org_status",
    "idx_chunks_document_id",
    "idx_chunks_org_document",
    "idx_chunks_fts_vector",
    "uq_document_chunks_qdrant_point_id",
    "idx_chat_messages_session",
    "idx_outbox_pending",
    "uq_outbox_messages_dedupe_key",
)
# Floors written by ``write_manifest`` when no table list is given.
MANIFEST_TABLES: Final[tuple[str, ...]] = (
    "organizations",
    "users",
    "documents",
    "document_chunks",
    "chat_sessions",
    "chat_messages",
)
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def policy_tables() -> list[str]:
    return sorted(
        set(rls.TENANT_RLS_TABLES) | set(rls.RLS_LOOKUP_TABLES) | set(rls.RLS_STRICT_TABLES)
    )


def required_tables() -> list[str]:
    return sorted(
        set(policy_tables())
        | set(rls.RLS_IDENTITY_TABLES)
        | set(rls.RLS_PENDING_TABLES)
        | set(CORE_TABLES)
    )


def expected_head(backend_dir: Path = BACKEND_DIR) -> str:
    """The single head revision of the migration scripts."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise ValueError(f"expected one alembic head, found {len(heads)}")
    return str(heads[0])


def libpq_url(url: str) -> str:
    """asyncpg takes ``postgresql://``; SQLAlchemy URLs carry ``+asyncpg``."""
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("database URL must be a postgresql:// URL")
    return url


def load_manifest(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text())
    floors = data.get("row_count_floors") if isinstance(data, dict) else None
    if not isinstance(floors, dict):
        raise ValueError("manifest needs a row_count_floors object")
    parsed: dict[str, int] = {}
    for table, floor in floors.items():
        if not isinstance(table, str) or not _IDENTIFIER.match(table):
            raise ValueError("manifest table names must be plain identifiers")
        if isinstance(floor, bool) or not isinstance(floor, int) or floor < 0:
            raise ValueError(f"row count floor for {table} must be a non-negative integer")
        parsed[table] = floor
    return parsed


@dataclass(slots=True)
class VerifyReport:
    lines: list[str] = field(default_factory=list)
    failures: int = 0

    def ok(self, text: str) -> None:
        self.lines.append(f"ok      {text}")

    def fail(self, text: str) -> None:
        self.failures += 1
        self.lines.append(f"FAILED  {text}")

    @property
    def passed(self) -> bool:
        return self.failures == 0


def _missing(report: VerifyReport, label: str, wanted: Iterable[str], present: set[str]) -> None:
    missing = sorted(set(wanted) - present)
    for name in missing:
        report.fail(f"{label} {name}")
    if not missing:
        report.ok(f"{label}: {len(set(wanted))}")


async def _names(conn: Any, query: str, *args: Any) -> set[str]:
    return {str(row[0]) for row in await conn.fetch(query, *args)}


async def _check_revision(conn: Any, report: VerifyReport, expected: str) -> None:
    try:
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
    except asyncpg.UndefinedTableError:
        report.fail("alembic_version table missing")
        return
    versions = sorted(str(row[0]) for row in rows)
    if versions == [expected]:
        report.ok(f"alembic_version {expected}")
    else:
        report.fail(f"alembic_version {','.join(versions) or 'empty'} (expected {expected})")


async def _check_schema(conn: Any, report: VerifyReport) -> set[str]:
    tables = await _names(
        conn,
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')",
    )
    _missing(report, "table", required_tables(), tables)
    wanted_policies = [name for name in policy_tables() if name in tables]
    enabled = await _names(
        conn,
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relrowsecurity",
    )
    _missing(report, "rls_enabled", wanted_policies, enabled)
    policies = await _names(
        conn,
        "SELECT tablename FROM pg_policies WHERE schemaname = current_schema() AND policyname = $1",
        rls.TENANT_RLS_POLICY_NAME,
    )
    _missing(report, "rls_policy", wanted_policies, policies)
    with_pk = await _names(
        conn,
        "SELECT c.relname FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND k.contype = 'p'",
    )
    _missing(report, "primary_key", [name for name in required_tables() if name in tables], with_pk)
    valid_indexes = await _names(
        conn,
        "SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
        "JOIN pg_namespace n ON n.oid = i.relnamespace "
        "WHERE n.nspname = current_schema() AND x.indisvalid",
    )
    _missing(report, "index", KEY_INDEXES, valid_indexes)
    return tables


async def _check_floors(
    conn: Any, report: VerifyReport, floors: Mapping[str, int], tables: set[str]
) -> None:
    for table, floor in sorted(floors.items()):
        if table not in tables:
            report.fail(f"rows {table}: table missing")
            continue
        count = int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
        if count >= floor:
            report.ok(f"rows {table} {count} >= {floor}")
        else:
            report.fail(f"rows {table} {count} < {floor}")


Connector = Callable[[str], Any]


async def verify_restore(
    database_url: str,
    *,
    expected_revision: str,
    floors: Mapping[str, int] | None = None,
    connect: Connector | None = None,
) -> VerifyReport:
    report = VerifyReport()
    opener = connect or asyncpg.connect
    try:
        conn = await opener(libpq_url(database_url))
    except Exception as exc:  # never echo the URL or the server's message
        report.fail(f"connect ({type(exc).__name__})")
        return report
    try:
        await _check_revision(conn, report, expected_revision)
        tables = await _check_schema(conn, report)
        await _check_floors(conn, report, floors or {}, tables)
    finally:
        await conn.close()
    return report


async def write_manifest(
    database_url: str,
    path: Path,
    *,
    tables: Iterable[str] = MANIFEST_TABLES,
    connect: Connector | None = None,
) -> dict[str, int]:
    """Record current row counts as floors (run on the source before a drill)."""
    names = list(tables)
    for name in names:
        if not _IDENTIFIER.match(name):
            raise ValueError("table names must be plain identifiers")
    conn = await (connect or asyncpg.connect)(libpq_url(database_url))
    try:
        counts = {
            name: int(await conn.fetchval(f'SELECT count(*) FROM "{name}"')) for name in names
        }
    finally:
        await conn.close()
    path.write_text(json.dumps({"row_count_floors": counts}, indent=2, sort_keys=True) + "\n")
    return counts
