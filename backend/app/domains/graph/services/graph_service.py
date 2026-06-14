"""High-level graph service abstraction (F281).

GraphService is the single entry point used by document lifecycle, chat/RAG,
and admin UI code to interact with the Enterprise Graph. It composes the five
repository classes and enforces:

  1. organization_id is always required — no cross-tenant reads/writes.
  2. Graceful fallback — every method checks is_available() and returns safe
     empty results when Neo4j is disabled or unreachable.
  3. No Cypher in callers — all queries live in the repository layer.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.clients.neo4j_client import get_driver
from app.core.logging import get_logger
from app.domains.graph.repositories.document_repository import DocumentGraphRepository
from app.domains.graph.repositories.entity_repository import EntityRepository
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.graph.repositories.extraction_run_repository import (
    ExtractionRunRepository,
    ExtractionRunStatus,
)
from app.domains.graph.repositories.graphrag_repository import GraphRAGRepository
from app.domains.graph.repositories.relation_repository import (
    RelationDirection,
    RelationRepository,
)

logger = get_logger("graph.service")


class GraphService:
    """Service boundary for all Enterprise Graph (Neo4j) operations.

    Instantiate once per request or as a module-level singleton — all state
    lives in the driver/session, not in this object.
    """

    def __init__(self) -> None:
        self._entities = EntityRepository()
        self._documents = DocumentGraphRepository()
        self._relations = RelationRepository()
        self._evidence = EvidenceRepository()
        self._extraction_runs = ExtractionRunRepository()
        self._graphrag = GraphRAGRepository()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when Enterprise Graph is enabled and the driver is active."""
        from app.core.config import settings

        return settings.enterprise_graph_enabled and get_driver() is not None

    # ------------------------------------------------------------------
    # Entity operations
    # ------------------------------------------------------------------

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
        """Create or update an Entity node. No-op when graph is unavailable."""
        await self._entities.upsert_entity(
            organization_id=organization_id,
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            workspace_id=workspace_id,
            external_source_id=external_source_id,
            properties=properties,
        )

    async def get_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
    ) -> dict | None:
        return await self._entities.get_entity(
            organization_id=organization_id,
            entity_id=entity_id,
        )

    async def list_entities(
        self,
        *,
        organization_id: UUID | str,
        workspace_id: UUID | str | None = None,
        entity_type: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        return await self._entities.list_entities(
            organization_id=organization_id,
            workspace_id=workspace_id,
            entity_type=entity_type,
            skip=skip,
            limit=limit,
        )

    async def delete_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
    ) -> bool:
        return await self._entities.delete_entity(
            organization_id=organization_id,
            entity_id=entity_id,
        )

    # ------------------------------------------------------------------
    # Document graph node operations
    # ------------------------------------------------------------------

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
        """Project a PostgreSQL document into the graph. No-op when unavailable."""
        await self._documents.upsert_document_node(
            organization_id=organization_id,
            document_id=document_id,
            workspace_id=workspace_id,
            title=title,
            source_chunk_id=source_chunk_id,
            properties=properties,
        )

    async def get_document_node(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> dict | None:
        return await self._documents.get_document_node(
            organization_id=organization_id,
            document_id=document_id,
        )

    async def delete_document_node(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> bool:
        return await self._documents.delete_document_node(
            organization_id=organization_id,
            document_id=document_id,
        )

    # ------------------------------------------------------------------
    # Relationship operations
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
        """Create or merge a relationship. Raises ValueError for unknown rel_type."""
        await self._relations.create_relation(
            organization_id=organization_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            rel_type=rel_type,
            properties=properties,
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
        return await self._relations.get_entity_relations(
            organization_id=organization_id,
            entity_id=entity_id,
            rel_type=rel_type,
            direction=direction,
            limit=limit,
        )

    async def delete_relation(
        self,
        *,
        organization_id: UUID | str,
        from_entity_id: UUID | str,
        to_entity_id: UUID | str,
        rel_type: str,
    ) -> bool:
        return await self._relations.delete_relation(
            organization_id=organization_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            rel_type=rel_type,
        )

    # ------------------------------------------------------------------
    # Evidence operations
    # ------------------------------------------------------------------

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
        """Link a Chunk to an Entity as evidence. No-op when graph is unavailable."""
        await self._evidence.link_evidence(
            organization_id=organization_id,
            entity_id=entity_id,
            chunk_id=chunk_id,
            source_document_id=source_document_id,
            confidence=confidence,
            evidence_text=evidence_text,
        )

    async def get_entity_evidence(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        limit: int = 50,
    ) -> list[dict]:
        return await self._evidence.get_entity_evidence(
            organization_id=organization_id,
            entity_id=entity_id,
            limit=limit,
        )

    async def remove_chunk_evidence(
        self,
        *,
        organization_id: UUID | str,
        chunk_id: UUID | str,
    ) -> int:
        """Delete all evidence links from a chunk. Returns count removed."""
        return await self._evidence.delete_evidence_for_chunk(
            organization_id=organization_id,
            chunk_id=chunk_id,
        )

    # ------------------------------------------------------------------
    # Extraction run operations
    # ------------------------------------------------------------------

    async def start_extraction_run(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        run_id: UUID | str,
        strategy: str,
    ) -> None:
        """Record the start of a graph extraction job. No-op when unavailable."""
        await self._extraction_runs.create_extraction_run(
            organization_id=organization_id,
            document_id=document_id,
            run_id=run_id,
            strategy=strategy,
            status="running",
        )

    async def finish_extraction_run(
        self,
        *,
        organization_id: UUID | str,
        run_id: UUID | str,
        status: ExtractionRunStatus,
        entity_count: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update the final status of an extraction run."""
        await self._extraction_runs.update_extraction_run(
            organization_id=organization_id,
            run_id=run_id,
            status=status,
            entity_count=entity_count,
            error=error,
        )

    async def get_document_extraction_runs(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        limit: int = 20,
    ) -> list[dict]:
        return await self._extraction_runs.get_extraction_runs(
            organization_id=organization_id,
            document_id=document_id,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # GraphRAG queries
    # ------------------------------------------------------------------

    async def find_related_entities(
        self,
        *,
        organization_id: UUID | str,
        entity_ids: list[UUID | str],
        depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """Multi-hop entity traversal for GraphRAG context expansion."""
        return await self._graphrag.find_related_entities(
            organization_id=organization_id,
            entity_ids=entity_ids,
            depth=depth,
            limit=limit,
        )

    async def find_entities_by_name(
        self,
        *,
        organization_id: UUID | str,
        name_query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Case-insensitive entity lookup by canonical_name."""
        return await self._graphrag.find_entities_by_name(
            organization_id=organization_id,
            name_query=name_query,
            entity_type=entity_type,
            limit=limit,
        )

    async def get_evidence_for_entities(
        self,
        *,
        organization_id: UUID | str,
        entity_ids: list[UUID | str],
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve evidence links for a set of entities (GraphRAG citation support)."""
        return await self._graphrag.get_evidence_for_entities(
            organization_id=organization_id,
            entity_ids=entity_ids,
            limit=limit,
        )
