"""Batched Entity and EntityAlias upserts (R06-10).

The Cypher is the single-item ``EntityRepository.upsert_entity`` and
``upsert_entity_alias`` statements with ``$x`` replaced by ``row.x`` under ``UNWIND``:
same MERGE keys (deterministic ids), same ON CREATE / ON MATCH properties. The only
addition is ``organization_id`` on the HAS_ALIAS and MENTIONS relationships.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.graph.repositories.batch_writes import (
    AliasWriteRow,
    EntityWriteRow,
    run_write_batches,
)

UPSERT_ENTITIES_CYPHER = """
UNWIND $rows AS row
MERGE (e:Entity {organization_id: $organization_id, entity_id: row.entity_id})
ON CREATE SET
    e.entity_type        = row.entity_type,
    e.canonical_name     = row.canonical_name,
    e.normalized_name    = row.normalized_name,
    e.workspace_id       = row.workspace_id,
    e.external_source_id = row.external_source_id,
    e.resolution_status  = row.resolution_status,
    e.resolution_confidence = row.resolution_confidence,
    e.aliases            = row.aliases,
    e.alias_count        = size(coalesce(row.aliases, [])),
    e.language           = row.language,
    e.extra              = row.extra,
    e.created_at         = $now,
    e.updated_at         = $now
ON MATCH SET
    e.entity_type        = row.entity_type,
    e.canonical_name     = row.canonical_name,
    e.normalized_name    = row.normalized_name,
    e.workspace_id       = row.workspace_id,
    e.external_source_id = row.external_source_id,
    e.resolution_status  = row.resolution_status,
    e.resolution_confidence = row.resolution_confidence,
    e.aliases            = row.aliases,
    e.alias_count        = size(coalesce(row.aliases, [])),
    e.language           = row.language,
    e.extra              = row.extra,
    e.updated_at         = $now
"""

UPSERT_ALIASES_CYPHER = """
UNWIND $rows AS row
MATCH (e:Entity {organization_id: $organization_id, entity_id: row.entity_id})
MERGE (a:EntityAlias {organization_id: $organization_id, alias_id: row.alias_id})
ON CREATE SET
    a.entity_id           = row.entity_id,
    a.alias_name          = row.alias_name,
    a.normalized_name     = row.normalized_name,
    a.source_document_id  = row.source_document_id,
    a.chunk_id            = row.chunk_id,
    a.workspace_id        = row.workspace_id,
    a.source_external_id  = row.source_external_id,
    a.source_connector    = row.source_connector,
    a.language            = row.language,
    a.confidence          = row.confidence,
    a.evidence_text       = row.evidence_text,
    a.created_at          = $now,
    a.updated_at          = $now
ON MATCH SET
    a.entity_id           = row.entity_id,
    a.alias_name          = row.alias_name,
    a.normalized_name     = row.normalized_name,
    a.source_document_id  = row.source_document_id,
    a.chunk_id            = row.chunk_id,
    a.workspace_id        = row.workspace_id,
    a.source_external_id  = row.source_external_id,
    a.source_connector    = row.source_connector,
    a.language            = row.language,
    a.confidence          = row.confidence,
    a.evidence_text       = row.evidence_text,
    a.updated_at          = $now
MERGE (e)-[h:HAS_ALIAS]->(a)
SET h.organization_id = $organization_id
WITH a, row
OPTIONAL MATCH (c:Chunk {organization_id: $organization_id, chunk_id: row.chunk_id})
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
    MERGE (c)-[m:MENTIONS]->(a)
    SET m.organization_id = $organization_id)
"""


class EntityBatchWriteMixin:
    """``upsert_entities_batch`` and ``upsert_entity_aliases_batch`` for EntityRepository."""

    async def upsert_entities_batch(
        self, *, organization_id: UUID | str, rows: Sequence[EntityWriteRow]
    ) -> int:
        """MERGE every Entity row of one organisation; returns write transactions committed."""
        return await _write(
            "entity", UPSERT_ENTITIES_CYPHER, organization_id, [r.params() for r in rows]
        )

    async def upsert_entity_aliases_batch(
        self, *, organization_id: UUID | str, rows: Sequence[AliasWriteRow]
    ) -> int:
        """MERGE every alias (and its HAS_ALIAS / MENTIONS edges) of one organisation."""
        return await _write(
            "alias", UPSERT_ALIASES_CYPHER, organization_id, [r.params() for r in rows]
        )


async def _write(
    kind: str, cypher: str, organization_id: UUID | str, rows: list[dict[str, Any]]
) -> int:
    org = str(organization_id)
    now = datetime.now(UTC).isoformat()

    async def _work(tx: Any, batch: list[dict[str, Any]]) -> None:
        await tx.run(cypher, rows=batch, organization_id=org, now=now)

    return await run_write_batches(
        kind=kind, organization_id=organization_id, rows=rows, work=_work
    )
