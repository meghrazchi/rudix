"""Neo4j repository for GraphRAG traversal queries (F281).

These are read-only queries used by the chat/RAG pipeline to augment retrieval
with graph context: related entities, multi-hop paths, and evidence links.

All Cypher is parameterized. All queries require organization_id.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings
from app.domains.graph.services.entity_resolution_service import normalize_entity_name

logger = get_logger("graph.repositories.graphrag")


class GraphRAGRepository:
    """Read-only graph traversal queries for the RAG pipeline."""

    async def find_related_entities(
        self,
        *,
        organization_id: UUID | str,
        entity_ids: list[UUID | str],
        depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """Return entities reachable within *depth* hops from the seed entity_ids.

        Results are scoped to organization_id and ordered by hop count.
        """
        if not entity_ids:
            return []

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        # depth is a Python int from trusted internal callers; max-clamped for safety.
        safe_depth = max(1, min(depth, 5))
        seed_ids = [str(eid) for eid in entity_ids]

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        f"""
                        MATCH (seed:Entity {{organization_id: $organization_id}})
                        WHERE seed.entity_id IN $entity_ids
                        MATCH p = (seed)-[*1..{safe_depth}]-(related:Entity {{organization_id: $organization_id}})
                        WHERE NOT related.entity_id IN $entity_ids
                        WITH related, min(length(p)) AS hops
                        RETURN
                            related.entity_id    AS entity_id,
                            related.entity_type  AS entity_type,
                            related.canonical_name AS canonical_name,
                            hops
                        ORDER BY hops, related.canonical_name
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        entity_ids=seed_ids,
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.graphrag.related_error",
                organization_id=str(organization_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def find_entities_by_name(
        self,
        *,
        organization_id: UUID | str,
        name_query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text-style case-insensitive entity lookup by canonical_name prefix.

        Uses CONTAINS on canonical_name (indexed). For production scale a full-text
        index query should be substituted, but this parameterized form is safe and
        avoids index-key injection.
        """
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        where_parts = [
            "e.organization_id = $organization_id",
            "("
            "toLower(e.canonical_name) CONTAINS toLower($name_query) OR "
            "toLower(e.normalized_name) CONTAINS toLower($normalized_query) OR "
            "toLower(a.alias_name) CONTAINS toLower($name_query) OR "
            "toLower(a.normalized_name) CONTAINS toLower($normalized_query)"
            ")",
        ]
        params: dict[str, Any] = {
            "organization_id": str(organization_id),
            "name_query": name_query,
            "normalized_query": normalize_entity_name(name_query),
            "limit": limit,
        }
        if entity_type is not None:
            where_parts.append("e.entity_type = $entity_type")
            params["entity_type"] = entity_type

        cypher = (
            "MATCH (e:Entity) OPTIONAL MATCH (e)-[:HAS_ALIAS]->(a:EntityAlias {organization_id: $organization_id}) WHERE "
            + " AND ".join(where_parts)
            + " RETURN e.entity_id AS entity_id,"
            "        e.entity_type AS entity_type,"
            "        e.canonical_name AS canonical_name,"
            "        e.workspace_id AS workspace_id,"
            "        e.normalized_name AS normalized_name,"
            "        collect(DISTINCT a.alias_name) AS aliases"
            " ORDER BY e.canonical_name LIMIT $limit"
        )

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
                "graph.graphrag.name_search_error",
                organization_id=str(organization_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def get_evidence_for_entities(
        self,
        *,
        organization_id: UUID | str,
        entity_ids: list[UUID | str],
        limit: int = 50,
    ) -> list[dict]:
        """Return EVIDENCE_FOR links for a set of entities.

        Used by the RAG pipeline to augment answers with source citations from
        the graph without re-running semantic search.
        """
        if not entity_ids:
            return []

        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        seed_ids = [str(eid) for eid in entity_ids]

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (c:Chunk {organization_id: $organization_id})
                              -[ev:EVIDENCE_FOR]->
                              (e:Entity {organization_id: $organization_id})
                        WHERE e.entity_id IN $entity_ids
                        RETURN
                            e.entity_id              AS entity_id,
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
                            ev.citation_reference    AS citation_reference
                        ORDER BY ev.confidence DESC NULLS LAST
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        entity_ids=seed_ids,
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.graphrag.evidence_error",
                organization_id=str(organization_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []
