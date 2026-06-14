"""Neo4j repository for Entity nodes (F281).

All Cypher is parameterized. Every public method requires organization_id to
enforce tenant isolation — missing scope causes rejection at the query level.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings

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
        properties: dict | None = None,
    ) -> None:
        """Create or update an Entity node. Requires organization_id."""
        driver, settings = _get_driver_and_settings()
        if driver is None:
            return

        extra = properties or {}
        now = datetime.now(timezone.utc).isoformat()

        async def _tx(tx: Any) -> None:
            await tx.run(
                """
                MERGE (e:Entity {organization_id: $organization_id, entity_id: $entity_id})
                ON CREATE SET
                    e.entity_type        = $entity_type,
                    e.canonical_name     = $canonical_name,
                    e.workspace_id       = $workspace_id,
                    e.external_source_id = $external_source_id,
                    e.extra              = $extra,
                    e.created_at         = $now,
                    e.updated_at         = $now
                ON MATCH SET
                    e.entity_type        = $entity_type,
                    e.canonical_name     = $canonical_name,
                    e.workspace_id       = $workspace_id,
                    e.external_source_id = $external_source_id,
                    e.extra              = $extra,
                    e.updated_at         = $now
                """,
                organization_id=str(organization_id),
                entity_id=str(entity_id),
                entity_type=entity_type,
                canonical_name=canonical_name,
                workspace_id=str(workspace_id) if workspace_id else None,
                external_source_id=external_source_id,
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
                        RETURN e {.*} AS entity
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
            + " RETURN e {.*} AS entity ORDER BY e.canonical_name SKIP $skip LIMIT $limit"
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
                WITH e, count(e) AS cnt
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
