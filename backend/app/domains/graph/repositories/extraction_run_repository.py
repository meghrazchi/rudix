"""Neo4j repository for ExtractionRun nodes (F281).

ExtractionRun nodes track graph extraction jobs — one per document per run.
They store run metadata (strategy, status, counts, errors) and link to the
Document node so operators can audit what graph data was derived from what job.

All Cypher is parameterized. Every method requires organization_id.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings

logger = get_logger("graph.repositories.extraction_run")

ExtractionRunStatus = Literal["running", "completed", "failed", "cancelled"]


class ExtractionRunRepository:
    """CRUD for ExtractionRun nodes linked to Document nodes."""

    async def create_extraction_run(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        run_id: UUID | str,
        strategy: str,
        status: ExtractionRunStatus = "running",
    ) -> None:
        """Create an ExtractionRun node and link it to its Document node."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (d:Document {organization_id: $organization_id, document_id: $document_id})
                ON CREATE SET d.created_at = $now
                CREATE (r:ExtractionRun {
                    organization_id: $organization_id,
                    run_id:          $run_id,
                    document_id:     $document_id,
                    strategy:        $strategy,
                    status:          $status,
                    created_at:      $now,
                    updated_at:      $now
                })
                MERGE (d)-[:HAS_EXTRACTION_RUN]->(r)
                """,
                organization_id=str(organization_id),
                document_id=str(document_id),
                run_id=str(run_id),
                strategy=strategy,
                status=status,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
            logger.info(
                "graph.extraction_run.created",
                organization_id=str(organization_id),
                document_id=str(document_id),
                run_id=str(run_id),
                strategy=strategy,
            )
        except Exception as exc:
            logger.warning(
                "graph.extraction_run.create_error",
                organization_id=str(organization_id),
                run_id=str(run_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def update_extraction_run(
        self,
        *,
        organization_id: UUID | str,
        run_id: UUID | str,
        status: ExtractionRunStatus,
        entity_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update status, entity_count, and optional error on an ExtractionRun."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MATCH (r:ExtractionRun {organization_id: $organization_id, run_id: $run_id})
                SET r.status       = $status,
                    r.entity_count = $entity_count,
                    r.error        = $error,
                    r.updated_at   = $now
                """,
                organization_id=str(organization_id),
                run_id=str(run_id),
                status=status,
                entity_count=entity_count,
                error=error,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
            logger.info(
                "graph.extraction_run.updated",
                organization_id=str(organization_id),
                run_id=str(run_id),
                status=status,
                entity_count=entity_count,
            )
        except Exception as exc:
            logger.warning(
                "graph.extraction_run.update_error",
                organization_id=str(organization_id),
                run_id=str(run_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def get_extraction_runs(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        limit: int = 20,
    ) -> list[dict]:
        """Return extraction runs for a document, newest first."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (d:Document {organization_id: $organization_id, document_id: $document_id})
                              -[:HAS_EXTRACTION_RUN]->(r:ExtractionRun)
                        RETURN r {.*} AS run
                        ORDER BY r.created_at DESC
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        document_id=str(document_id),
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r["run"]) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.extraction_run.list_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []
