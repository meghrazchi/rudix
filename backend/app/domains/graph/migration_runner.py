"""Repeatable Neo4j graph migration runner (F280).

Design principles
-----------------
- Idempotent: every DDL statement uses IF NOT EXISTS; re-running is safe.
- Non-fatal: if Enterprise Graph is disabled or the driver is unavailable, the
  runner returns an empty result so that non-graph Rudix features are unaffected.
- Schema commands (CREATE CONSTRAINT / CREATE INDEX) run in auto-commit mode
  because Neo4j does not allow schema DDL inside explicit write transactions.
- Migration records are stored as __GraphMigration nodes so operators can audit
  which schema version is active without querying external state.
- Duck-typed driver: no direct import of neo4j types so the module loads even
  when the neo4j package is not installed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.clients.neo4j_client import get_driver
from app.core.logging import get_logger
from app.domains.graph.schema import MIGRATIONS, GraphMigration

logger = get_logger("graph.migration_runner")


@dataclass
class MigrationResult:
    applied: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)
    failed: str | None = None

    @property
    def success(self) -> bool:
        return self.failed is None


async def run_graph_migrations() -> MigrationResult:
    """Apply all pending graph schema migrations idempotently.

    Safe to call on every startup: already-applied migrations are skipped.
    Returns an empty result (no error) when Enterprise Graph is disabled.
    """
    from app.core.config import settings

    result = MigrationResult()

    if not settings.enterprise_graph_enabled:
        logger.info("graph.migration.skipped", reason="enterprise_graph_disabled")
        return result

    driver = get_driver()
    if driver is None:
        logger.warning("graph.migration.skipped", reason="driver_not_initialized")
        return result

    database = settings.neo4j_database
    timeout = settings.neo4j_query_timeout_seconds

    try:
        applied_versions = await _get_applied_versions(driver, database, timeout)
        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                result.already_applied.append(migration.version)
                logger.debug(
                    "graph.migration.skip",
                    version=migration.version,
                    reason="already_applied",
                )
                continue
            await _apply_migration(driver, database, migration, timeout)
            result.applied.append(migration.version)
            logger.info(
                "graph.migration.applied",
                version=migration.version,
                description=migration.description,
                statement_count=len(migration.statements),
            )
    except Exception as exc:
        result.failed = f"{exc.__class__.__name__}: {exc}"
        logger.error(
            "graph.migration.error",
            error=exc.__class__.__name__,
            detail=str(exc),
        )

    return result


async def get_migration_status() -> list[dict[str, str]]:
    """Return applied __GraphMigration records from the graph, or [] if unavailable."""
    from app.core.config import settings

    if not settings.enterprise_graph_enabled:
        return []
    driver = get_driver()
    if driver is None:
        return []
    try:
        return await _get_migration_records(driver, settings.neo4j_database, settings.neo4j_query_timeout_seconds)
    except Exception as exc:
        logger.warning("graph.migration.status_error", error=str(exc))
        return []


async def _get_applied_versions(driver: Any, database: str, timeout: float) -> set[str]:
    async with driver.session(database=database) as session:
        result = await asyncio.wait_for(
            session.run("MATCH (m:__GraphMigration) RETURN m.version AS version ORDER BY m.version"),
            timeout=timeout,
        )
        records = await result.data()
    return {r["version"] for r in records if r.get("version")}


async def _get_migration_records(driver: Any, database: str, timeout: float) -> list[dict[str, str]]:
    async with driver.session(database=database) as session:
        result = await asyncio.wait_for(
            session.run(
                "MATCH (m:__GraphMigration) RETURN m.version AS version, "
                "m.description AS description, m.applied_at AS applied_at "
                "ORDER BY m.version"
            ),
            timeout=timeout,
        )
        records = await result.data()
    return [
        {
            "version": r.get("version", ""),
            "description": r.get("description", ""),
            "applied_at": r.get("applied_at", ""),
        }
        for r in records
    ]


async def _apply_migration(
    driver: Any,
    database: str,
    migration: GraphMigration,
    timeout: float,
) -> None:
    # Schema DDL must run in auto-commit mode (not inside a managed transaction).
    async with driver.session(database=database) as schema_session:
        for stmt in migration.statements:
            result = await asyncio.wait_for(
                schema_session.run(stmt.strip()),
                timeout=timeout,
            )
            await result.consume()

    # Record the migration as applied in a write transaction.
    async def _mark_applied(tx: Any) -> None:
        await tx.run(
            """
            MERGE (m:__GraphMigration {version: $version})
            ON CREATE SET m.description = $description,
                          m.applied_at  = $applied_at
            """,
            version=migration.version,
            description=migration.description,
            applied_at=datetime.now(timezone.utc).isoformat(),
        )

    async with driver.session(database=database) as data_session:
        await data_session.execute_write(_mark_applied)
