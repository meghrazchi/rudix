"""Neo4j repository for evidence links (F281) with full provenance contract (F282).

Evidence is the EVIDENCE_FOR relationship from a Chunk node to an Entity node.
It links every graph fact back to its source document/chunk so that claims are
traceable to an authoritative text span.

F282 extends evidence with:
  - workspace_id, document_version_id, page_number, source_connector, external_url
  - extraction_run_id — ties a graph fact to a specific extraction pipeline run
  - citation_text — the verbatim quoted span
  - citation_reference — formatted reference string (e.g. "Privacy Policy v2, p. 4")

Validation contract (F282): at least one of evidence_text, citation_text, or
citation_reference must be provided. A bare evidence link with no textual backing
is rejected with ValueError so graph facts remain evidence-first.

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


def _require_citation(
    evidence_text: str | None,
    citation_text: str | None,
    citation_reference: str | None,
) -> None:
    """Raise ValueError when no textual backing is provided."""
    if not any([evidence_text, citation_text, citation_reference]):
        raise ValueError(
            "provenance_required: at least one of evidence_text, citation_text, "
            "or citation_reference must be provided"
        )


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
        # F282 full provenance
        workspace_id: UUID | str | None = None,
        document_version_id: str | None = None,
        page_number: int | None = None,
        source_connector: str | None = None,
        external_url: str | None = None,
        extraction_run_id: UUID | str | None = None,
        citation_text: str | None = None,
        citation_reference: str | None = None,
    ) -> None:
        """Create or update an EVIDENCE_FOR link from a Chunk to an Entity.

        F282: Requires at least one of evidence_text, citation_text, or
        citation_reference — graph facts must have textual provenance.
        """
        _require_citation(evidence_text, citation_text, citation_reference)

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(timezone.utc).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (c:Chunk {organization_id: $organization_id, chunk_id: $chunk_id})
                ON CREATE SET
                    c.source_document_id  = $source_document_id,
                    c.workspace_id        = $workspace_id,
                    c.source_connector    = $source_connector,
                    c.created_at          = $now
                ON MATCH SET
                    c.workspace_id        = CASE WHEN $workspace_id IS NOT NULL
                                                 THEN $workspace_id ELSE c.workspace_id END,
                    c.source_connector    = CASE WHEN $source_connector IS NOT NULL
                                                 THEN $source_connector ELSE c.source_connector END
                MERGE (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                MERGE (c)-[ev:EVIDENCE_FOR]->(e)
                ON CREATE SET
                    ev.source_document_id    = $source_document_id,
                    ev.workspace_id          = $workspace_id,
                    ev.document_version_id   = $document_version_id,
                    ev.page_number           = $page_number,
                    ev.source_connector      = $source_connector,
                    ev.external_url          = $external_url,
                    ev.extraction_run_id     = $extraction_run_id,
                    ev.confidence            = $confidence,
                    ev.evidence_text         = $evidence_text,
                    ev.citation_text         = $citation_text,
                    ev.citation_reference    = $citation_reference,
                    ev.created_at            = $now
                ON MATCH SET
                    ev.workspace_id          = CASE WHEN $workspace_id IS NOT NULL
                                                    THEN $workspace_id ELSE ev.workspace_id END,
                    ev.document_version_id   = CASE WHEN $document_version_id IS NOT NULL
                                                    THEN $document_version_id ELSE ev.document_version_id END,
                    ev.page_number           = CASE WHEN $page_number IS NOT NULL
                                                    THEN $page_number ELSE ev.page_number END,
                    ev.source_connector      = CASE WHEN $source_connector IS NOT NULL
                                                    THEN $source_connector ELSE ev.source_connector END,
                    ev.external_url          = CASE WHEN $external_url IS NOT NULL
                                                    THEN $external_url ELSE ev.external_url END,
                    ev.extraction_run_id     = CASE WHEN $extraction_run_id IS NOT NULL
                                                    THEN $extraction_run_id ELSE ev.extraction_run_id END,
                    ev.confidence            = $confidence,
                    ev.evidence_text         = CASE WHEN $evidence_text IS NOT NULL
                                                    THEN $evidence_text ELSE ev.evidence_text END,
                    ev.citation_text         = CASE WHEN $citation_text IS NOT NULL
                                                    THEN $citation_text ELSE ev.citation_text END,
                    ev.citation_reference    = CASE WHEN $citation_reference IS NOT NULL
                                                    THEN $citation_reference ELSE ev.citation_reference END,
                    ev.updated_at            = $now
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                chunk_id=str(chunk_id),
                source_document_id=str(source_document_id),
                workspace_id=str(workspace_id) if workspace_id else None,
                document_version_id=document_version_id,
                page_number=page_number,
                source_connector=source_connector,
                external_url=external_url,
                extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
                confidence=confidence,
                evidence_text=evidence_text,
                citation_text=citation_text,
                citation_reference=citation_reference,
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
                extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
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
        """Return all evidence (Chunk→Entity EVIDENCE_FOR links) for an entity.

        Returns full F282 provenance: chunk location, connector source, extraction
        run, and citation text/reference fields.
        """
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
                            c.chunk_id               AS chunk_id,
                            c.source_document_id     AS source_document_id,
                            c.workspace_id           AS workspace_id,
                            c.source_connector       AS source_connector,
                            ev.document_version_id   AS document_version_id,
                            ev.page_number           AS page_number,
                            ev.external_url          AS external_url,
                            ev.extraction_run_id     AS extraction_run_id,
                            ev.confidence            AS confidence,
                            ev.evidence_text         AS evidence_text,
                            ev.citation_text         AS citation_text,
                            ev.citation_reference    AS citation_reference,
                            ev.created_at            AS created_at
                        ORDER BY ev.confidence DESC NULLS LAST
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

    async def get_document_provenance(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        limit: int = 100,
    ) -> list[dict]:
        """Return all evidence links for all entities extracted from a document.

        Allows callers to reconstruct which graph facts came from which
        document, which chunks, and which extraction run.
        """
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (c:Chunk {organization_id: $organization_id,
                                        source_document_id: $document_id})
                              -[ev:EVIDENCE_FOR]->
                              (e:Entity {organization_id: $organization_id})
                        RETURN
                            e.entity_id              AS entity_id,
                            e.entity_type            AS entity_type,
                            e.canonical_name         AS canonical_name,
                            c.chunk_id               AS chunk_id,
                            c.source_document_id     AS source_document_id,
                            c.workspace_id           AS workspace_id,
                            c.source_connector       AS source_connector,
                            ev.document_version_id   AS document_version_id,
                            ev.page_number           AS page_number,
                            ev.external_url          AS external_url,
                            ev.extraction_run_id     AS extraction_run_id,
                            ev.confidence            AS confidence,
                            ev.evidence_text         AS evidence_text,
                            ev.citation_text         AS citation_text,
                            ev.citation_reference    AS citation_reference,
                            ev.created_at            AS created_at
                        ORDER BY ev.confidence DESC NULLS LAST, e.canonical_name
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        document_id=str(document_id),
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.evidence.document_provenance_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
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

    async def delete_evidence_for_document(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        extraction_run_id: UUID | str | None = None,
    ) -> int:
        """Remove all EVIDENCE_FOR links for a document. Returns count removed."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return 0

        where_run = "AND ev.extraction_run_id = $extraction_run_id" if extraction_run_id else ""
        cypher = f"""
            MATCH (c:Chunk {{organization_id: $organization_id,
                             source_document_id: $document_id}})
                  -[ev:EVIDENCE_FOR]->()
            WHERE 1 = 1 {where_run}
            WITH ev, count(ev) AS cnt
            DELETE ev
            RETURN cnt
        """

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                cypher,
                organization_id=str(organization_id),
                document_id=str(document_id),
                extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
            logger.debug(
                "graph.evidence.document_deleted",
                organization_id=str(organization_id),
                document_id=str(document_id),
                extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
                count=cnt,
            )
            return cnt
        except Exception as exc:
            logger.warning(
                "graph.evidence.document_delete_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                extraction_run_id=str(extraction_run_id) if extraction_run_id else None,
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return 0

    async def delete_orphan_chunks_for_document(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> int:
        """Delete Chunk nodes that no longer have any graph relationships."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return 0

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                """
                MATCH (c:Chunk {organization_id: $organization_id,
                                source_document_id: $document_id})
                WHERE NOT (c)--()
                WITH c, count(c) AS cnt
                DELETE c
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
            logger.debug(
                "graph.evidence.orphan_chunks_deleted",
                organization_id=str(organization_id),
                document_id=str(document_id),
                count=cnt,
            )
            return cnt
        except Exception as exc:
            logger.warning(
                "graph.evidence.orphan_chunks_delete_error",
                organization_id=str(organization_id),
                document_id=str(document_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return 0
