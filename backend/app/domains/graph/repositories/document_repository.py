"""Neo4j repository for Document graph nodes (F281).

Document nodes in Neo4j are derived projections of PostgreSQL document records.
PostgreSQL remains the source of truth; these nodes enable graph traversal only.

All Cypher is parameterized. Every method requires organization_id.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings

logger = get_logger("graph.repositories.document")


class DocumentGraphRepository:
    """CRUD for Document nodes in the Enterprise Graph.

    These are NOT replacements for the PostgreSQL document records — they are
    graph projections used for traversal and GraphRAG relationship discovery.
    """

    async def upsert_document_node(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        workspace_id: UUID | str | None = None,
        title: str | None = None,
        source_chunk_id: UUID | str | None = None,
        properties: dict | None = None,
    ) -> None:
        """Create or update a Document node. Requires organization_id."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (d:Document {organization_id: $organization_id, document_id: $document_id})
                ON CREATE SET
                    d.workspace_id    = $workspace_id,
                    d.title           = $title,
                    d.source_chunk_id = $source_chunk_id,
                    d.extra           = $extra,
                    d.created_at      = $now,
                    d.updated_at      = $now
                ON MATCH SET
                    d.workspace_id    = $workspace_id,
                    d.title           = $title,
                    d.source_chunk_id = $source_chunk_id,
                    d.extra           = $extra,
                    d.updated_at      = $now
                """,
                organization_id=str(organization_id),
                document_id=str(document_id),
                workspace_id=str(workspace_id) if workspace_id else None,
                title=title,
                source_chunk_id=str(source_chunk_id) if source_chunk_id else None,
                extra=extra,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
            logger.debug(
                "graph.document.upserted",
                organization_id=str(organization_id),
                document_id=str(document_id),
            )
        except Exception as exc:
            logger.warning(
                "graph.document.upsert_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def get_document_node(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> dict | None:
        """Fetch a Document node by (organization_id, document_id)."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return None

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (d:Document {organization_id: $organization_id, document_id: $document_id})
                        RETURN d {.*} AS doc
                        """,
                        organization_id=str(organization_id),
                        document_id=str(document_id),
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            if not records:
                return None
            return dict(records[0]["doc"])
        except Exception as exc:
            logger.warning(
                "graph.document.get_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return None

    async def delete_document_node(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> bool:
        """Remove a Document node and its graph relationships. Returns True if removed."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return False

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                """
                MATCH (d:Document {organization_id: $organization_id, document_id: $document_id})
                WITH d, count(d) AS cnt
                DETACH DELETE d
                RETURN cnt
                """,
                organization_id=str(organization_id),
                document_id=str(document_id),
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
            return cnt > 0
        except Exception as exc:
            logger.warning(
                "graph.document.delete_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return False
