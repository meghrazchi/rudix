"""Neo4j repository for Entity nodes (F281).

All Cypher is parameterized. Every public method requires organization_id to
enforce tenant isolation — missing scope causes rejection at the query level.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings
from app.domains.graph.services.entity_resolution_service import normalize_entity_name

logger = get_logger("graph.repositories.entity")


class EntityRepository:
    """CRUD for Entity nodes scoped by organization_id."""

    async def upsert_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        entity_type: str,
        canonical_name: str,
        workspace_id: UUID | str | None = None,
        external_source_id: str | None = None,
        normalized_name: str | None = None,
        resolution_status: str | None = None,
        resolution_confidence: float | None = None,
        properties: dict | None = None,
    ) -> None:
        """Create or update an Entity node. Requires organization_id."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        resolved_normalized_name = (
            normalized_name or extra.get("normalized_name") or normalize_entity_name(canonical_name)
        )
        resolved_status = (
            resolution_status if resolution_status is not None else extra.get("resolution_status")
        )
        resolved_confidence = (
            resolution_confidence
            if resolution_confidence is not None
            else extra.get("resolution_confidence")
        )
        resolved_language = extra.get("language")
        resolved_aliases = extra.get("aliases")
        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                ON CREATE SET
                    e.entity_type        = $entity_type,
                    e.canonical_name     = $canonical_name,
                    e.normalized_name    = $normalized_name,
                    e.workspace_id       = $workspace_id,
                    e.external_source_id = $external_source_id,
                    e.resolution_status  = $resolution_status,
                    e.resolution_confidence = $resolution_confidence,
                    e.aliases            = $aliases,
                    e.alias_count        = size(coalesce($aliases, [])),
                    e.language           = $language,
                    e.extra              = $extra,
                    e.created_at         = $now,
                    e.updated_at         = $now
                ON MATCH SET
                    e.entity_type        = $entity_type,
                    e.canonical_name     = $canonical_name,
                    e.normalized_name    = $normalized_name,
                    e.workspace_id       = $workspace_id,
                    e.external_source_id = $external_source_id,
                    e.resolution_status  = $resolution_status,
                    e.resolution_confidence = $resolution_confidence,
                    e.aliases            = $aliases,
                    e.alias_count        = size(coalesce($aliases, [])),
                    e.language           = $language,
                    e.extra              = $extra,
                    e.updated_at         = $now
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                entity_type=entity_type,
                canonical_name=canonical_name,
                workspace_id=str(workspace_id) if workspace_id else None,
                external_source_id=external_source_id,
                normalized_name=resolved_normalized_name,
                resolution_status=resolved_status,
                resolution_confidence=resolved_confidence,
                aliases=resolved_aliases,
                language=resolved_language,
                extra=extra,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
            logger.debug(
                "graph.entity.upserted",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                entity_type=entity_type,
            )
        except Exception as exc:
            logger.warning(
                "graph.entity.upsert_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def get_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
    ) -> dict | None:
        """Fetch a single Entity by (organization_id, entity_id)."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return None

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                        OPTIONAL MATCH (e)-[:HAS_ALIAS]->(a:EntityAlias {organization_id: $organization_id})
                        RETURN e {
                            .*,
                            aliases: collect(DISTINCT a.alias_name),
                            alias_count: count(DISTINCT a)
                        } AS entity
                        """,
                        organization_id=str(organization_id),
                        entity_id=str(entity_id),
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            if not records:
                return None
            return dict(records[0]["entity"])
        except Exception as exc:
            logger.warning(
                "graph.entity.get_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return None

    async def list_entities(
        self,
        *,
        organization_id: UUID | str,
        workspace_id: UUID | str | None = None,
        entity_type: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """List entities scoped to organization_id with optional filters."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        # Build WHERE clause from constants + parameterized values only.
        # No user-controlled string ever enters the clause text.
        where_parts = ["e.organization_id = $organization_id"]
        params: dict[str, Any] = {
            "organization_id": str(organization_id),
            "skip": skip,
            "limit": limit,
        }
        if workspace_id is not None:
            where_parts.append("e.workspace_id = $workspace_id")
            params["workspace_id"] = str(workspace_id)
        if entity_type is not None:
            where_parts.append("e.entity_type = $entity_type")
            params["entity_type"] = entity_type

        cypher = (
            "MATCH (e:Entity) WHERE "
            + " AND ".join(where_parts)
            + " OPTIONAL MATCH (e)-[:HAS_ALIAS]->(a:EntityAlias {organization_id: $organization_id})"
            + " RETURN e {.*, aliases: collect(DISTINCT a.alias_name), alias_count: count(DISTINCT a)} AS entity"
            + " ORDER BY e.canonical_name SKIP $skip LIMIT $limit"
        )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(cypher, **params),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(r["entity"]) for r in records]
        except Exception as exc:
            logger.warning(
                "graph.entity.list_error",
                organization_id=str(organization_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def delete_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
    ) -> bool:
        """Delete an Entity and its relationships. Returns True if removed."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return False

        async def _tx(tx: Any) -> int:
            result = await tx.run(
                """
                MATCH (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                OPTIONAL MATCH (e)-[:HAS_ALIAS]->(a:EntityAlias {organization_id: $organization_id})
                WITH e, collect(DISTINCT a) AS aliases, count(e) AS cnt
                FOREACH (alias IN aliases | DETACH DELETE alias)
                DETACH DELETE e
                RETURN cnt
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
            )
            records = await result.data()
            return records[0]["cnt"] if records else 0

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                cnt = await session.execute_write(_tx)
            return cnt > 0
        except Exception as exc:
            logger.warning(
                "graph.entity.delete_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return False

    async def upsert_entity_alias(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        alias_id: UUID | str,
        alias_name: str,
        source_document_id: UUID | str | None = None,
        chunk_id: UUID | str | None = None,
        workspace_id: UUID | str | None = None,
        source_external_id: str | None = None,
        source_connector: str | None = None,
        language: str | None = None,
        confidence: float | None = None,
        evidence_text: str | None = None,
        properties: dict | None = None,
    ) -> None:
        """Store a canonical entity alias / source mention with provenance."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        normalized_name = extra.get("normalized_name") or normalize_entity_name(alias_name)
        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MATCH (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                MERGE (a:EntityAlias {organization_id: $organization_id, alias_id: $alias_id})
                ON CREATE SET
                    a.entity_id           = $entity_id,
                    a.alias_name          = $alias_name,
                    a.normalized_name     = $normalized_name,
                    a.source_document_id   = $source_document_id,
                    a.chunk_id            = $chunk_id,
                    a.workspace_id        = $workspace_id,
                    a.source_external_id  = $source_external_id,
                    a.source_connector    = $source_connector,
                    a.language            = $language,
                    a.confidence          = $confidence,
                    a.evidence_text       = $evidence_text,
                    a.created_at          = $now,
                    a.updated_at          = $now
                ON MATCH SET
                    a.entity_id           = $entity_id,
                    a.alias_name          = $alias_name,
                    a.normalized_name     = $normalized_name,
                    a.source_document_id   = $source_document_id,
                    a.chunk_id            = $chunk_id,
                    a.workspace_id        = $workspace_id,
                    a.source_external_id  = $source_external_id,
                    a.source_connector    = $source_connector,
                    a.language            = $language,
                    a.confidence          = $confidence,
                    a.evidence_text       = $evidence_text,
                    a.updated_at          = $now
                MERGE (e)-[:HAS_ALIAS]->(a)
                WITH a
                OPTIONAL MATCH (c:Chunk {organization_id: $organization_id, chunk_id: $chunk_id})
                FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:MENTIONS]->(a))
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                alias_id=str(alias_id),
                alias_name=alias_name,
                normalized_name=normalized_name,
                source_document_id=str(source_document_id) if source_document_id else None,
                chunk_id=str(chunk_id) if chunk_id else None,
                workspace_id=str(workspace_id) if workspace_id else None,
                source_external_id=source_external_id,
                source_connector=source_connector,
                language=language,
                confidence=confidence,
                evidence_text=evidence_text,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
        except Exception as exc:
            logger.warning(
                "graph.entity.alias_upsert_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                alias_id=str(alias_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def find_entity_resolution_candidates(
        self,
        *,
        organization_id: UUID | str,
        entity_type: str | None = None,
        normalized_name: str | None = None,
        aliases: list[str] | None = None,
        source_external_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return possible canonical entity matches within the same org."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        normalized_aliases = [normalize_entity_name(alias) for alias in aliases or []]
        where_parts = ["e.organization_id = $organization_id"]
        signal_parts: list[str] = []
        params: dict[str, Any] = {
            "organization_id": str(organization_id),
            "normalized_name": normalized_name,
            "aliases": normalized_aliases,
            "source_external_id": source_external_id,
            "entity_type": entity_type,
            "limit": limit,
        }

        if entity_type is not None:
            where_parts.append("e.entity_type = $entity_type")
        if normalized_name is not None:
            signal_parts.append(
                "("
                "e.normalized_name = $normalized_name OR "
                "toLower(e.canonical_name) = toLower($normalized_name)"
                ")"
            )
        if source_external_id is not None:
            signal_parts.append("e.external_source_id = $source_external_id")
        if normalized_aliases:
            signal_parts.append("a.normalized_name IN $aliases")

        if signal_parts:
            where_parts.append("(" + " OR ".join(signal_parts) + ")")

        where_clause = " AND ".join(where_parts)
        cypher = f"""
            MATCH (e:Entity {{organization_id: $organization_id}})
            OPTIONAL MATCH (e)-[:HAS_ALIAS]->(a:EntityAlias {{organization_id: $organization_id}})
            WHERE {where_clause}
            WITH
                e,
                collect(DISTINCT a.alias_name) AS alias_names,
                collect(DISTINCT a.normalized_name) AS alias_normalized_names,
                count(DISTINCT a) AS alias_count
            RETURN
                e.entity_id AS entity_id,
                e.entity_type AS entity_type,
                e.canonical_name AS canonical_name,
                coalesce(e.normalized_name, toLower(e.canonical_name)) AS normalized_name,
                e.external_source_id AS external_source_id,
                e.resolution_status AS resolution_status,
                e.resolution_confidence AS resolution_confidence,
                alias_names AS aliases,
                alias_normalized_names AS alias_normalized_names,
                alias_count AS alias_count
            ORDER BY e.resolution_confidence DESC NULLS LAST, alias_count DESC, e.canonical_name
            LIMIT $limit
        """

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(cypher, **params),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(record) for record in records]
        except Exception as exc:
            logger.warning(
                "graph.entity.candidate_search_error",
                organization_id=str(organization_id),
                entity_type=entity_type,
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def list_entity_aliases(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        limit: int = 50,
    ) -> list[dict]:
        """Return alias / mention records for a canonical entity."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return []

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        """
                        MATCH (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                              -[:HAS_ALIAS]->
                              (a:EntityAlias {organization_id: $organization_id})
                        OPTIONAL MATCH (c:Chunk {organization_id: $organization_id, chunk_id: a.chunk_id})
                        RETURN
                            a.alias_id            AS alias_id,
                            a.entity_id           AS entity_id,
                            a.alias_name          AS alias_name,
                            a.normalized_name     AS normalized_name,
                            a.source_document_id   AS source_document_id,
                            a.chunk_id            AS chunk_id,
                            a.workspace_id        AS workspace_id,
                            a.source_external_id  AS source_external_id,
                            a.source_connector    AS source_connector,
                            a.language            AS language,
                            a.confidence          AS confidence,
                            a.evidence_text       AS evidence_text,
                            a.created_at          AS created_at,
                            a.updated_at          AS updated_at,
                            c.page_number         AS page_number
                        ORDER BY a.updated_at DESC, a.alias_name
                        LIMIT $limit
                        """,
                        organization_id=str(organization_id),
                        entity_id=str(entity_id),
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [dict(record) for record in records]
        except Exception as exc:
            logger.warning(
                "graph.entity.alias_list_error",
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
            return []

    async def record_entity_merge_decision(
        self,
        *,
        organization_id: UUID | str,
        decision_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> None:
        """Persist a manual merge decision for later audit and replay."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (d:EntityResolutionDecision {
                    organization_id: $organization_id,
                    decision_id: $decision_id
                })
                ON CREATE SET
                    d.decision_kind      = 'merge',
                    d.target_entity_id    = $target_entity_id,
                    d.source_entity_ids   = $source_entity_ids,
                    d.reason              = $reason,
                    d.reviewer_id         = $reviewer_id,
                    d.created_at          = $now,
                    d.updated_at          = $now
                ON MATCH SET
                    d.decision_kind      = 'merge',
                    d.target_entity_id    = $target_entity_id,
                    d.source_entity_ids   = $source_entity_ids,
                    d.reason              = $reason,
                    d.reviewer_id         = $reviewer_id,
                    d.updated_at          = $now
                """,
                organization_id=str(organization_id),
                decision_id=str(decision_id),
                target_entity_id=str(target_entity_id),
                source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
                reason=reason,
                reviewer_id=reviewer_id,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
        except Exception as exc:
            logger.warning(
                "graph.entity.merge_decision_error",
                organization_id=str(organization_id),
                decision_id=str(decision_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )

    async def record_entity_split_decision(
        self,
        *,
        organization_id: UUID | str,
        decision_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> None:
        """Persist a manual split decision for later audit and replay."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        now = datetime.now(UTC).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (d:EntityResolutionDecision {
                    organization_id: $organization_id,
                    decision_id: $decision_id
                })
                ON CREATE SET
                    d.decision_kind      = 'split',
                    d.target_entity_id    = $target_entity_id,
                    d.source_entity_ids   = $source_entity_ids,
                    d.reason              = $reason,
                    d.reviewer_id         = $reviewer_id,
                    d.created_at          = $now,
                    d.updated_at          = $now
                ON MATCH SET
                    d.decision_kind      = 'split',
                    d.target_entity_id    = $target_entity_id,
                    d.source_entity_ids   = $source_entity_ids,
                    d.reason              = $reason,
                    d.reviewer_id         = $reviewer_id,
                    d.updated_at          = $now
                """,
                organization_id=str(organization_id),
                decision_id=str(decision_id),
                target_entity_id=str(target_entity_id),
                source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
                reason=reason,
                reviewer_id=reviewer_id,
                now=now,
            )

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                await session.execute_write(_tx)
        except Exception as exc:
            logger.warning(
                "graph.entity.split_decision_error",
                organization_id=str(organization_id),
                decision_id=str(decision_id),
                error=exc.__class__.__name__,
                detail=str(exc),
            )
