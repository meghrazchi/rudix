"""Neo4j repository for evidence links (F281).

Evidence is the EVIDENCE_FOR relationship from a Chunk node to an Entity node.
It links graph facts back to their source documents/chunks so that every graph
claim is traceable to an authoritative text span.

All Cypher is parameterized. Every method requires organization_id.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings

logger = get_logger("graph.repositories.evidence")


class EvidenceRepository:
    """CRUD for EVIDENCE_FOR relationships between Chunk and Entity nodes."""

    async def link_evidence(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        chunk_id: UUID | str,
        source_document_id: UUID | str,
        confidence: float | None = None,
        evidence_text: str | None = None,
    ) -> None:
        """Create or update an EVIDENCE_FOR link from a Chunk to an Entity.

        Also ensures the Chunk node exists (upserted) before creating the link.
        """
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(timezone.utc).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (c:Chunk {organization_id: $organization_id, chunk_id: $chunk_id})
                ON CREATE SET
                    c.source_document_id = $source_document_id,
                    c.created_at         = $now
                MERGE (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                MERGE (c)-[ev:EVIDENCE_FOR]->(e)
                ON CREATE SET
                    ev.source_document_id = $source_document_id,
                    ev.confidence         = $confidence,
                    ev.evidence_text      = $evidence_text,
                    ev.created_at         = $now
                ON MATCH SET
                    ev.confidence         = $confidence,
                    ev.evidence_text      = $evidence_text,
                    ev.updated_at         = $now
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                chunk_id=str(chunk_id),
                source_document_id=str(source_document_id),
                confidence=confidence,
                evidence_text=evidence_text,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
            logger.debug(
                "graph.evidence.linked",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                chunk_id=str(chunk_id),
            )
        except Exception as exc:
            logger.warning(
                "graph.evidence.link_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                chunk_id=str(chunk_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def get_entity_evidence(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        limit: int = 50,
    ) -> list[dict]:
        """Return all evidence (Chunk→Entity EVIDENCE_FOR links) for an entity."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (c:Chunk {organization_id: $organization_id})
                              -[ev:EVIDENCE_FOR]->
                              (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                        RETURN
                            c.chunk_id            AS chunk_id,
                            c.source_document_id  AS source_document_id,
                            ev.confidence         AS confidence,
                            ev.evidence_text      AS evidence_text,
                            ev.created_at         AS created_at
                        ORDER BY ev.confidence DESC
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        entity_id=str(entity_id),
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.evidence.get_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def delete_evidence_for_chunk(
        self,
        *,
        organization_id: UUID | str,
        chunk_id: UUID | str,
    ) -> int:
        """Remove all EVIDENCE_FOR links originating from a Chunk. Returns count removed."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return 0

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                """
                MATCH (c:Chunk {organization_id: $organization_id, chunk_id: $chunk_id})
                      -[ev:EVIDENCE_FOR]->()
                WITH ev, count(ev) AS cnt
                DELETE ev
                RETURN cnt
                """,
                organization_id=str(organization_id),
                chunk_id=str(chunk_id),
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
            logger.debug(
                "graph.evidence.chunk_deleted",
                organization_id=str(organization_id),
                chunk_id=str(chunk_id),
                count=cnt,
            )
            return cnt
        except Exception as exc:
            logger.warning(
                "graph.evidence.delete_error",
                organization_id=str(organization_id),
                chunk_id=str(chunk_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return 0
