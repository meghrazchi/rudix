"""GraphService wrappers for the batched ingestion writes (R06-10).

Each wrapper is a no-op returning 0 when the graph is unavailable, like every other
GraphService method, and otherwise returns the number of write transactions committed.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domains.graph.repositories.batch_writes import (
    AliasWriteRow,
    EntityWriteRow,
    EvidenceWriteRow,
    RelationWriteRow,
)
from app.domains.graph.repositories.entity_repository import EntityRepository
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.graph.repositories.relation_repository import RelationRepository


class GraphBatchWritesMixin:
    _entities: EntityRepository
    _evidence: EvidenceRepository
    _relations: RelationRepository

    def is_available(self) -> bool:  # pragma: no cover - provided by GraphService
        raise NotImplementedError

    async def upsert_entities_batch(
        self, *, organization_id: UUID | str, rows: Sequence[EntityWriteRow]
    ) -> int:
        if not rows or not self.is_available():
            return 0
        return await self._entities.upsert_entities_batch(
            organization_id=organization_id, rows=rows
        )

    async def upsert_entity_aliases_batch(
        self, *, organization_id: UUID | str, rows: Sequence[AliasWriteRow]
    ) -> int:
        if not rows or not self.is_available():
            return 0
        return await self._entities.upsert_entity_aliases_batch(
            organization_id=organization_id, rows=rows
        )

    async def link_evidence_batch(
        self, *, organization_id: UUID | str, rows: Sequence[EvidenceWriteRow]
    ) -> int:
        if not rows or not self.is_available():
            return 0
        return await self._evidence.link_evidence_batch(organization_id=organization_id, rows=rows)

    async def create_relations_with_evidence_batch(
        self, *, organization_id: UUID | str, rows: Sequence[RelationWriteRow]
    ) -> int:
        if not rows or not self.is_available():
            return 0
        return await self._relations.create_relations_with_evidence_batch(
            organization_id=organization_id, rows=rows
        )
