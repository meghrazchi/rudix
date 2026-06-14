"""Neo4j repository for graph relationships (F281/F284).

All relationship types are validated against the schema vocabulary before being
interpolated into Cypher — they are never passed as raw user input.

All Cypher parameters (ids, properties) are fully parameterized.

F284 additions:
- create_relation_with_evidence: evidence-backed relation creation with status
  and confidence. Evidence text/citation is required. Deduplication by
  (from_entity_id, rel_type, to_entity_id) per org via MERGE; on re-extraction
  the edge is updated only when new confidence is higher.
- list_relations: list relations filterable by status, rel_type, and workspace.
- get_relation: fetch a single relation by its stable relation_id property.
- update_relation_status: transition a relation to verified/rejected/low_confidence.
- delete_relation_by_id: delete by stable relation_id (does not require callers
  to know from/to entity ids).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings
from app.domains.graph.schema import RELATIONSHIP_TYPES

logger = get_logger("graph.repositories.relation")

RelationDirection = Literal["out", "in", "both"]
RelationStatus = Literal["unverified", "verified", "rejected", "low_confidence"]

RELATION_STATUSES: frozenset[str] = frozenset(
    {"unverified", "verified", "rejected", "low_confidence"}
)


def _validate_rel_type(rel_type: str) -> str:
    """Raise ValueError if rel_type is not in the schema vocabulary."""
    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"Unknown relationship type '{rel_type}'. Valid types: {', '.join(RELATIONSHIP_TYPES)}"
        )
    return rel_type


def _validate_status(status: str) -> str:
    if status not in RELATION_STATUSES:
        raise ValueError(
            f"Unknown relation status '{status}'. "
            f"Valid statuses: {', '.join(sorted(RELATION_STATUSES))}"
        )
    return status


class RelationRepository:
    """CRUD for typed relationships between Entity/Document/Chunk nodes."""

    # ------------------------------------------------------------------
    # Legacy create_relation (kept for compatibility with F281 callers)
    # ------------------------------------------------------------------

    async def create_relation(
        self,
        *,
        organization_id: UUID | str,
        from_entity_id: UUID | str,
        to_entity_id: UUID | str,
        rel_type: str,
        properties: dict | None = None,
    ) -> None:
        """Create or merge a relationship between two entities.

        rel_type must be in the RELATIONSHIP_TYPES schema vocabulary.
        Prefer create_relation_with_evidence for new callers (F284).
        """
        _validate_rel_type(rel_type)
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        now = datetime.now(UTC).isoformat()

        cypher = f"""
            MATCH (a:Entity {{organization_id: $organization_id, entity_id: $from_entity_id}})
            MATCH (b:Entity {{organization_id: $organization_id, entity_id: $to_entity_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            ON CREATE SET r.extra = $extra, r.created_at = $now
            ON MATCH  SET r.extra = $extra, r.updated_at = $now
        """

        async def _tx(tx: Any) -> None:
            await tx.run(
                cypher,
                organization_id=str(organization_id),
                from_entity_id=str(from_entity_id),
                to_entity_id=str(to_entity_id),
                extra=extra,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await session.execute_write(_tx)
                if asyncio.iscoroutine(result):
                    await result
            logger.debug(
                "graph.relation.created",
                organization_id=str(organization_id),
                from_entity_id=str(from_entity_id),
                rel_type=rel_type,
                to_entity_id=str(to_entity_id),
            )
        except Exception as exc:
            logger.warning(
                "graph.relation.create_error",
                organization_id=str(organization_id),
                rel_type=rel_type,
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    # ------------------------------------------------------------------
    # F284: evidence-backed relation creation
    # ------------------------------------------------------------------

    async def create_relation_with_evidence(
        self,
        *,
        organization_id: UUID | str,
        from_entity_id: UUID | str,
        to_entity_id: UUID | str,
        rel_type: str,
        relation_id: UUID | str,
        # Evidence — at least one of the three is required
        evidence_text: str | None = None,
        citation_text: str | None = None,
        citation_reference: str | None = None,
        # Provenance
        chunk_id: UUID | str | None = None,
        source_document_id: UUID | str | None = None,
        page_number: int | None = None,
        workspace_id: UUID | str | None = None,
        source_connector: str | None = None,
        extraction_run_id: UUID | str | None = None,
        # Scoring and state
        confidence: float = 0.5,
        initial_status: RelationStatus = "unverified",
    ) -> None:
        """Create or merge an evidence-backed relation edge.

        Deduplication: MERGE on (organization_id, from_entity_id, rel_type,
        to_entity_id). On re-extraction the edge's confidence and provenance
        are updated only when the incoming confidence is higher, preserving
        the best-quality evidence.

        Raises:
            ValueError: if rel_type is unknown, status is invalid, or no
                evidence field is provided.
        """
        _validate_rel_type(rel_type)
        _validate_status(initial_status)
        if not any([evidence_text, citation_text, citation_reference]):
            raise ValueError(
                "create_relation_with_evidence requires at least one of: "
                "evidence_text, citation_text, citation_reference"
            )

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(UTC).isoformat()

        # rel_type is validated against the schema vocabulary; safe to interpolate.
        cypher = f"""
            MATCH (a:Entity {{organization_id: $org, entity_id: $from_id}})
            MATCH (b:Entity {{organization_id: $org, entity_id: $to_id}})
            MERGE (a)-[r:{rel_type} {{organization_id: $org,
                                       from_entity_id: $from_id,
                                       to_entity_id: $to_id}}]->(b)
            ON CREATE SET
                r.relation_id          = $relation_id,
                r.status               = $status,
                r.confidence           = $confidence,
                r.evidence_text        = $evidence_text,
                r.citation_text        = $citation_text,
                r.citation_reference   = $citation_reference,
                r.chunk_id             = $chunk_id,
                r.source_document_id   = $source_document_id,
                r.page_number          = $page_number,
                r.workspace_id         = $workspace_id,
                r.source_connector     = $source_connector,
                r.extraction_run_id    = $extraction_run_id,
                r.created_at           = $now,
                r.updated_at           = $now
            ON MATCH SET
                r.updated_at           = $now,
                r.confidence           = CASE WHEN $confidence > r.confidence
                                              THEN $confidence ELSE r.confidence END,
                r.evidence_text        = CASE WHEN $confidence > r.confidence
                                              THEN $evidence_text ELSE r.evidence_text END,
                r.citation_text        = CASE WHEN $confidence > r.confidence
                                              THEN $citation_text ELSE r.citation_text END,
                r.citation_reference   = CASE WHEN $confidence > r.confidence
                                              THEN $citation_reference ELSE r.citation_reference END,
                r.chunk_id             = CASE WHEN $confidence > r.confidence
                                              THEN $chunk_id ELSE r.chunk_id END,
                r.source_document_id   = CASE WHEN $confidence > r.confidence
                                              THEN $source_document_id ELSE r.source_document_id END,
                r.page_number          = CASE WHEN $confidence > r.confidence
                                              THEN $page_number ELSE r.page_number END,
                r.extraction_run_id    = CASE WHEN $confidence > r.confidence
                                              THEN $extraction_run_id ELSE r.extraction_run_id END
        """

        async def _tx(tx: Any) -> None:
            await tx.run(
                cypher,
                org=str(organization_id),
                from_id=str(from_entity_id),
                to_id=str(to_entity_id),
                relation_id=str(relation_id),
                status=initial_status,
                confidence=confidence,
                evidence_text=evidence_text,
                citation_text=citation_text,
                citation_reference=citation_reference,
                chunk_id=str(chunk_id) if chunk_id is not None else None,
                source_document_id=str(source_document_id)
                if source_document_id is not None
                else None,
                page_number=page_number,
                workspace_id=str(workspace_id) if workspace_id is not None else None,
                source_connector=source_connector,
                extraction_run_id=str(extraction_run_id) if extraction_run_id is not None else None,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await session.execute_write(_tx)
                if asyncio.iscoroutine(result):
                    await result
            logger.debug(
                "graph.relation.upserted",
                organization_id=str(organization_id),
                from_entity_id=str(from_entity_id),
                rel_type=rel_type,
                to_entity_id=str(to_entity_id),
                relation_id=str(relation_id),
                status=initial_status,
                confidence=confidence,
            )
        except Exception as exc:
            logger.warning(
                "graph.relation.upsert_error",
                organization_id=str(organization_id),
                rel_type=rel_type,
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    # ------------------------------------------------------------------
    # F284: list relations with status/type filter
    # ------------------------------------------------------------------

    async def list_relations(
        self,
        *,
        organization_id: UUID | str,
        status: RelationStatus | None = None,
        rel_type: str | None = None,
        workspace_id: UUID | str | None = None,
        min_confidence: float | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List relations for an org with optional filters.

        Scans across all typed edges that carry an organization_id property,
        which is set by create_relation_with_evidence. Legacy edges created by
        create_relation (no organization_id on edge) are excluded.
        """
        if rel_type is not None:
            _validate_rel_type(rel_type)
        if status is not None:
            _validate_status(status)

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        rel_pattern = f":{rel_type}" if rel_type else ""
        where_clauses = ["r.organization_id = $org"]
        params: dict[str, Any] = {
            "org": str(organization_id),
            "skip": skip,
            "limit": limit,
        }
        if status is not None:
            where_clauses.append("r.status = $status")
            params["status"] = status
        if workspace_id is not None:
            where_clauses.append("r.workspace_id = $workspace_id")
            params["workspace_id"] = str(workspace_id)
        if min_confidence is not None:
            where_clauses.append("r.confidence >= $min_confidence")
            params["min_confidence"] = min_confidence

        where_str = " AND ".join(where_clauses)

        cypher = f"""
            MATCH (a:Entity)-[r{rel_pattern}]->(b:Entity)
            WHERE {where_str}
            RETURN
                r.relation_id        AS relation_id,
                r.organization_id    AS organization_id,
                r.from_entity_id     AS from_entity_id,
                type(r)              AS rel_type,
                r.to_entity_id       AS to_entity_id,
                r.status             AS status,
                r.confidence         AS confidence,
                r.evidence_text      AS evidence_text,
                r.citation_text      AS citation_text,
                r.citation_reference AS citation_reference,
                r.chunk_id           AS chunk_id,
                r.source_document_id AS source_document_id,
                r.page_number        AS page_number,
                r.workspace_id       AS workspace_id,
                r.extraction_run_id  AS extraction_run_id,
                r.created_at         AS created_at,
                r.updated_at         AS updated_at
            ORDER BY r.confidence DESC
            SKIP $skip
            LIMIT $limit
        """

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(cypher, **params),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.relation.list_error",
                organization_id=str(organization_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    # ------------------------------------------------------------------
    # F284: get relation by stable relation_id
    # ------------------------------------------------------------------

    async def get_relation(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
    ) -> dict | None:
        """Fetch a single relation edge by its stable relation_id property."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return None

        cypher = """
            MATCH ()-[r {organization_id: $org, relation_id: $relation_id}]->()
            RETURN
                r.relation_id        AS relation_id,
                r.organization_id    AS organization_id,
                r.from_entity_id     AS from_entity_id,
                type(r)              AS rel_type,
                r.to_entity_id       AS to_entity_id,
                r.status             AS status,
                r.confidence         AS confidence,
                r.evidence_text      AS evidence_text,
                r.citation_text      AS citation_text,
                r.citation_reference AS citation_reference,
                r.chunk_id           AS chunk_id,
                r.source_document_id AS source_document_id,
                r.page_number        AS page_number,
                r.workspace_id       AS workspace_id,
                r.extraction_run_id  AS extraction_run_id,
                r.created_at         AS created_at,
                r.updated_at         AS updated_at
            LIMIT 1
        """

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        cypher,
                        org=str(organization_id),
                        relation_id=str(relation_id),
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return dict(records[0]) if records else None
        except Exception as exc:
            logger.warning(
                "graph.relation.get_error",
                organization_id=str(organization_id),
                relation_id=str(relation_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # F284: update relation status
    # ------------------------------------------------------------------

    async def update_relation_status(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
        status: RelationStatus,
    ) -> bool:
        """Set the status of a relation identified by its stable relation_id.

        Returns True if the relation was found and updated, False otherwise.
        """
        _validate_status(status)
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return False

        now = datetime.now(UTC).isoformat()

        cypher = """
            MATCH ()-[r {organization_id: $org, relation_id: $relation_id}]->()
            SET r.status = $status, r.updated_at = $now
            RETURN count(r) AS cnt
        """

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                cypher,
                org=str(organization_id),
                relation_id=str(relation_id),
                status=status,
                now=now,
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
                if asyncio.iscoroutine(cnt):
                    cnt = await cnt
            if cnt > 0:
                logger.debug(
                    "graph.relation.status_updated",
                    organization_id=str(organization_id),
                    relation_id=str(relation_id),
                    status=status,
                )
            return cnt > 0
        except Exception as exc:
            logger.warning(
                "graph.relation.update_status_error",
                organization_id=str(organization_id),
                relation_id=str(relation_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # F284: delete relation by stable relation_id
    # ------------------------------------------------------------------

    async def delete_relation_by_id(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
    ) -> bool:
        """Delete a relation by its stable relation_id. Returns True if removed."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return False

        cypher = """
            MATCH ()-[r {organization_id: $org, relation_id: $relation_id}]->()
            WITH r, count(r) AS cnt
            DELETE r
            RETURN cnt
        """

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                cypher,
                org=str(organization_id),
                relation_id=str(relation_id),
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
                if asyncio.iscoroutine(cnt):
                    cnt = await cnt
            return cnt > 0
        except Exception as exc:
            logger.warning(
                "graph.relation.delete_by_id_error",
                organization_id=str(organization_id),
                relation_id=str(relation_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Legacy get/delete by entity pair (F281 — kept for compatibility)
    # ------------------------------------------------------------------

    async def get_entity_relations(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        rel_type: str | None = None,
        direction: RelationDirection = "out",
        limit: int = 100,
        exclude_statuses: list[str] | None = None,
        min_confidence: float | None = None,
    ) -> list[dict]:
        """Return relationships for an entity.

        F284 additions: exclude_statuses and min_confidence allow GraphRAG to
        filter out rejected/low_confidence relations without a separate query.
        """
        if rel_type is not None:
            _validate_rel_type(rel_type)

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        rel_pattern = f":{rel_type}" if rel_type else ""
        if direction == "out":
            edge = f"-[r{rel_pattern}]->"
        elif direction == "in":
            edge = f"<-[r{rel_pattern}]-"
        else:
            edge = f"-[r{rel_pattern}]-"

        where_clauses = [
            "a.organization_id = $organization_id",
            "b.organization_id = $organization_id",
        ]
        params: dict[str, Any] = {
            "organization_id": str(organization_id),
            "entity_id": str(entity_id),
            "limit": limit,
        }

        if exclude_statuses:
            where_clauses.append("NOT r.status IN $exclude_statuses")
            params["exclude_statuses"] = exclude_statuses
        if min_confidence is not None:
            where_clauses.append("(r.confidence IS NULL OR r.confidence >= $min_confidence)")
            params["min_confidence"] = min_confidence

        where_str = " AND ".join(where_clauses)

        cypher = f"""
            MATCH (a:Entity {{entity_id: $entity_id}}){edge}(b:Entity)
            WHERE {where_str}
            RETURN
                a.entity_id          AS from_entity_id,
                type(r)              AS rel_type,
                b.entity_id          AS to_entity_id,
                r.relation_id        AS relation_id,
                r.status             AS status,
                r.confidence         AS confidence,
                r {{.*}}             AS properties
            LIMIT $limit
        """

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(cypher, **params),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [
                {
                    "from_entity_id": r["from_entity_id"],
                    "rel_type": r["rel_type"],
                    "to_entity_id": r["to_entity_id"],
                    "relation_id": r.get("relation_id"),
                    "status": r.get("status"),
                    "confidence": r.get("confidence"),
                    "properties": dict(r["properties"]) if r["properties"] else {},
                }
                for r in records
            ]
        except Exception as exc:
            logger.warning(
                "graph.relation.list_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def delete_relation(
        self,
        *,
        organization_id: UUID | str,
        from_entity_id: UUID | str,
        to_entity_id: UUID | str,
        rel_type: str,
    ) -> bool:
        """Delete a specific relationship between two entities. Returns True if removed."""
        _validate_rel_type(rel_type)
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return False

        cypher = f"""
            MATCH (a:Entity {{organization_id: $organization_id, entity_id: $from_entity_id}})
                  -[r:{rel_type}]->
                  (b:Entity {{organization_id: $organization_id, entity_id: $to_entity_id}})
            WITH r, count(r) AS cnt
            DELETE r
            RETURN cnt
        """

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                cypher,
                organization_id=str(organization_id),
                from_entity_id=str(from_entity_id),
                to_entity_id=str(to_entity_id),
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
            return cnt > 0
        except Exception as exc:
            logger.warning(
                "graph.relation.delete_error",
                organization_id=str(organization_id),
                rel_type=rel_type,
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return False
