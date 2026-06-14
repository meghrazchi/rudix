"""Neo4j repository for graph relationships (F281).

All relationship types are validated against the schema vocabulary before being
interpolated into Cypher — they are never passed as raw user input.

All Cypher parameters (ids, properties) are fully parameterized.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings
from app.domains.graph.schema import RELATIONSHIP_TYPES

logger = get_logger("graph.repositories.relation")

RelationDirection = Literal["out", "in", "both"]


def _validate_rel_type(rel_type: str) -> str:
    """Raise ValueError if rel_type is not in the schema vocabulary."""
    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"Unknown relationship type '{rel_type}'. "
            f"Valid types: {', '.join(RELATIONSHIP_TYPES)}"
        )
    return rel_type


class RelationRepository:
    """CRUD for typed relationships between Entity/Document/Chunk nodes."""

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

        rel_type must be in the RELATIONSHIP_TYPES schema vocabulary. Raises
        ValueError for unknown types so callers fail fast rather than silently.
        """
        _validate_rel_type(rel_type)
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        now = datetime.now(timezone.utc).isoformat()

        # rel_type is validated against the static schema vocabulary above;
        # it is safe to interpolate into the Cypher template.
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
                await session.execute_write(_tx)
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

    async def get_entity_relations(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        rel_type: str | None = None,
        direction: RelationDirection = "out",
        limit: int = 100,
    ) -> list[dict]:
        """Return relationships for an entity.

        If rel_type is provided it is validated against the schema vocabulary.
        direction controls edge direction: "out", "in", or "both".
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

        cypher = f"""
            MATCH (a:Entity {{organization_id: $organization_id, entity_id: $entity_id}})
            {edge} (b:Entity {{organization_id: $organization_id}})
            RETURN
                a.entity_id AS from_entity_id,
                type(r)     AS rel_type,
                b.entity_id AS to_entity_id,
                r {{.*}}    AS properties
            LIMIT $limit
        """

        try:
            async with driver.session(database=settings.neo4j_database) as session:
                result = await asyncio.wait_for(
                    session.run(
                        cypher,
                        organization_id=str(organization_id),
                        entity_id=str(entity_id),
                        limit=limit,
                    ),
                    timeout=settings.neo4j_query_timeout_seconds,
                )
                records = await result.data()
            return [
                {
                    "from_entity_id": r["from_entity_id"],
                    "rel_type": r["rel_type"],
                    "to_entity_id": r["to_entity_id"],
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
