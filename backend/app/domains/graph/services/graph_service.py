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

from collections import defaultdict
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
    RelationStatus,
)
from app.domains.graph.services.entity_resolution_service import (
    EntityResolutionInput,
    EntityResolutionResult,
    EntityResolutionService,
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
        self._entity_resolution = EntityResolutionService()

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
        normalized_name: str | None = None,
        resolution_status: str | None = None,
        resolution_confidence: float | None = None,
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
            normalized_name=normalized_name,
            resolution_status=resolution_status,
            resolution_confidence=resolution_confidence,
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
        await self._entities.upsert_entity_alias(
            organization_id=organization_id,
            entity_id=entity_id,
            alias_id=alias_id,
            alias_name=alias_name,
            source_document_id=source_document_id,
            chunk_id=chunk_id,
            workspace_id=workspace_id,
            source_external_id=source_external_id,
            source_connector=source_connector,
            language=language,
            confidence=confidence,
            evidence_text=evidence_text,
            properties=properties,
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
        return await self._entities.find_entity_resolution_candidates(
            organization_id=organization_id,
            entity_type=entity_type,
            normalized_name=normalized_name,
            aliases=aliases,
            source_external_id=source_external_id,
            limit=limit,
        )

    async def list_entity_aliases(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        limit: int = 50,
    ) -> list[dict]:
        return await self._entities.list_entity_aliases(
            organization_id=organization_id,
            entity_id=entity_id,
            limit=limit,
        )

    async def resolve_entity(
        self,
        *,
        organization_id: UUID | str,
        entity_type: str,
        canonical_name: str,
        original_name: str | None = None,
        aliases: list[str] | None = None,
        source_external_id: str | None = None,
        source_connector: str | None = None,
        language: str | None = None,
        embedding_similarity: float | None = None,
    ) -> EntityResolutionResult:
        input_ = EntityResolutionInput(
            organization_id=str(organization_id),
            entity_type=entity_type,
            canonical_name=canonical_name,
            original_name=original_name,
            aliases=aliases or [],
            source_external_id=source_external_id,
            source_connector=source_connector,
            language=language,
            embedding_similarity=embedding_similarity,
        )
        return await self._entity_resolution.resolve_entity(
            repository=self._entities,
            input_=input_,
        )

    async def record_entity_merge_decision(
        self,
        *,
        organization_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> None:
        await self._entities.record_entity_merge_decision(
            organization_id=organization_id,
            decision_id=self._entity_resolution.build_merge_decision_id(
                organization_id=str(organization_id),
                target_entity_id=str(target_entity_id),
                source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
            ),
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
            reason=reason,
            reviewer_id=reviewer_id,
        )

    def build_entity_merge_decision_id(
        self,
        *,
        organization_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
    ) -> UUID:
        return self._entity_resolution.build_merge_decision_id(
            organization_id=str(organization_id),
            target_entity_id=str(target_entity_id),
            source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
        )

    async def record_entity_split_decision(
        self,
        *,
        organization_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> None:
        await self._entities.record_entity_split_decision(
            organization_id=organization_id,
            decision_id=self._entity_resolution.build_split_decision_id(
                organization_id=str(organization_id),
                target_entity_id=str(target_entity_id),
                source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
            ),
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
            reason=reason,
            reviewer_id=reviewer_id,
        )

    def build_entity_split_decision_id(
        self,
        *,
        organization_id: UUID | str,
        target_entity_id: UUID | str,
        source_entity_ids: list[UUID | str],
    ) -> UUID:
        return self._entity_resolution.build_split_decision_id(
            organization_id=str(organization_id),
            target_entity_id=str(target_entity_id),
            source_entity_ids=[str(entity_id) for entity_id in source_entity_ids],
        )

    # ------------------------------------------------------------------
    # Graph explorer
    # ------------------------------------------------------------------

    async def search_entities(
        self,
        *,
        organization_id: UUID | str,
        query: str | None = None,
        entity_type: str | None = None,
        min_confidence: float | None = None,
        source_document_id: UUID | str | None = None,
        source_connector: str | None = None,
        rel_type: str | None = None,
        relationship_direction: RelationDirection = "both",
        skip: int = 0,
        limit: int = 25,
    ) -> dict[str, object]:
        """Search graph entities and apply evidence/relationship filters.

        The implementation intentionally uses the existing read repositories so
        the UI can query a member-scoped explorer without needing admin APIs.
        """
        search_limit = max(limit, skip + limit * 4)
        search_limit = min(max(search_limit, 100), 500)
        normalized_query = query.strip() if query else None
        normalized_source_connector = source_connector.strip() if source_connector else None

        if normalized_query:
            candidates = await self._graphrag.find_entities_by_name(
                organization_id=organization_id,
                name_query=normalized_query,
                entity_type=entity_type,
                limit=search_limit,
            )
        else:
            candidates = await self._entities.list_entities(
                organization_id=organization_id,
                entity_type=entity_type,
                skip=0,
                limit=search_limit,
            )

        if not candidates:
            return {
                "items": [],
                "total": 0,
                "skip": skip,
                "limit": limit,
                "query": normalized_query,
                "entity_type": entity_type,
                "min_confidence": min_confidence,
                "source_document_id": str(source_document_id)
                if source_document_id is not None
                else None,
                "source_connector": normalized_source_connector,
                "rel_type": rel_type,
                "relationship_direction": relationship_direction,
            }

        candidate_ids = [candidate.get("entity_id") for candidate in candidates]
        evidence_rows = await self._graphrag.get_evidence_for_entities(
            organization_id=organization_id,
            entity_ids=[entity_id for entity_id in candidate_ids if entity_id],
            limit=max(search_limit * 3, search_limit),
            document_ids=[source_document_id] if source_document_id else None,
            confidence_threshold=min_confidence,
        )
        evidence_by_entity: dict[str, list[dict]] = defaultdict(list)
        for row in evidence_rows:
            entity_key = str(row.get("entity_id"))
            evidence_by_entity[entity_key].append(row)

        relation_entity_ids: set[str] | None = None
        if rel_type is not None or relationship_direction != "both":
            relation_rows = await self._relations.list_relations(
                organization_id=organization_id,
                rel_type=rel_type,
                min_confidence=min_confidence,
                skip=0,
                limit=search_limit * 4,
            )
            relation_entity_ids = set()
            for row in relation_rows:
                from_id = str(row.get("from_entity_id"))
                to_id = str(row.get("to_entity_id"))
                if relationship_direction == "out":
                    relation_entity_ids.add(from_id)
                elif relationship_direction == "in":
                    relation_entity_ids.add(to_id)
                else:
                    relation_entity_ids.update({from_id, to_id})

        filtered_items: list[dict[str, object]] = []
        for candidate in candidates:
            entity_id = str(candidate.get("entity_id") or "")
            if not entity_id:
                continue

            candidate_evidence = evidence_by_entity.get(entity_id, [])
            if source_document_id is not None and not candidate_evidence:
                continue
            if normalized_source_connector is not None and not any(
                (row.get("source_connector") or "").strip() == normalized_source_connector
                for row in candidate_evidence
            ):
                continue

            relation_confidence = candidate.get("resolution_confidence")
            evidence_confidence = max(
                (float(row.get("confidence") or 0.0) for row in candidate_evidence),
                default=0.0,
            )
            confidence = (
                max(
                    float(relation_confidence or 0.0),
                    evidence_confidence,
                )
                if relation_confidence is not None or candidate_evidence
                else None
            )
            if min_confidence is not None:
                if confidence is None or confidence < min_confidence:
                    continue

            if relation_entity_ids is not None and entity_id not in relation_entity_ids:
                continue

            item = {
                "entity_id": entity_id,
                "entity_type": candidate.get("entity_type"),
                "canonical_name": candidate.get("canonical_name"),
                "normalized_name": candidate.get("normalized_name"),
                "aliases": list(candidate.get("aliases") or []),
                "alias_count": int(candidate.get("alias_count") or 0),
                "workspace_id": candidate.get("workspace_id"),
                "external_source_id": candidate.get("external_source_id"),
                "resolution_status": candidate.get("resolution_status"),
                "resolution_confidence": candidate.get("resolution_confidence"),
                "confidence": confidence,
                "last_updated_at": candidate.get("updated_at"),
                "evidence_count": len(candidate_evidence),
                "related_document_count": len(
                    {
                        str(row.get("source_document_id"))
                        for row in candidate_evidence
                        if row.get("source_document_id")
                    }
                ),
            }
            filtered_items.append(item)

        total = len(filtered_items)
        page_items = filtered_items[skip : skip + limit]
        return {
            "items": page_items,
            "total": total,
            "skip": skip,
            "limit": limit,
            "query": normalized_query,
            "entity_type": entity_type,
            "min_confidence": min_confidence,
            "source_document_id": str(source_document_id)
            if source_document_id is not None
            else None,
            "source_connector": normalized_source_connector,
            "rel_type": rel_type,
            "relationship_direction": relationship_direction,
        }

    async def get_entity_detail(
        self,
        *,
        organization_id: UUID | str,
        entity_id: UUID | str,
        rel_type: str | None = None,
        relationship_direction: RelationDirection = "both",
        limit: int = 50,
    ) -> dict[str, object] | None:
        """Return entity summary plus aliases, evidence, documents, and relations."""
        entity = await self.get_entity(
            organization_id=organization_id,
            entity_id=entity_id,
        )
        if entity is None:
            return None

        aliases = await self.list_entity_aliases(
            organization_id=organization_id,
            entity_id=entity_id,
            limit=limit,
        )
        evidence = await self.get_entity_evidence(
            organization_id=organization_id,
            entity_id=entity_id,
            limit=limit,
        )
        relations = await self.get_entity_relations(
            organization_id=organization_id,
            entity_id=entity_id,
            rel_type=rel_type,
            direction=relationship_direction,
            limit=max(limit * 2, limit),
        )

        related_entity_ids: set[str] = set()
        for relation in relations:
            from_entity_id = str(relation.get("from_entity_id") or "")
            to_entity_id = str(relation.get("to_entity_id") or "")
            if from_entity_id and from_entity_id != str(entity_id):
                related_entity_ids.add(from_entity_id)
            if to_entity_id and to_entity_id != str(entity_id):
                related_entity_ids.add(to_entity_id)

        related_entity_rows: list[dict[str, object]] = []
        for related_entity_id in sorted(related_entity_ids):
            related_entity = await self.get_entity(
                organization_id=organization_id,
                entity_id=related_entity_id,
            )
            if related_entity is None:
                continue
            related_entity_rows.append(
                {
                    "entity_id": related_entity_id,
                    "entity_type": related_entity.get("entity_type"),
                    "canonical_name": related_entity.get("canonical_name"),
                    "normalized_name": related_entity.get("normalized_name"),
                    "relation_count": sum(
                        1
                        for relation in relations
                        if str(relation.get("from_entity_id")) == related_entity_id
                        or str(relation.get("to_entity_id")) == related_entity_id
                    ),
                }
            )

        documents_by_id: dict[str, dict[str, object]] = {}
        for row in evidence:
            document_id = str(row.get("source_document_id") or "")
            if not document_id:
                continue
            document = documents_by_id.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "page_numbers": set(),
                    "evidence_count": 0,
                    "max_confidence": 0.0,
                    "source_connectors": set(),
                },
            )
            page_number = row.get("page_number")
            if page_number is not None:
                document["page_numbers"].add(int(page_number))
            document["evidence_count"] = int(document["evidence_count"]) + 1
            confidence = float(row.get("confidence") or 0.0)
            document["max_confidence"] = max(
                float(document["max_confidence"]),
                confidence,
            )
            connector = row.get("source_connector")
            if connector:
                document["source_connectors"].add(str(connector))

        connected_documents = [
            {
                "document_id": document_id,
                "page_numbers": sorted(document["page_numbers"]),
                "evidence_count": document["evidence_count"],
                "max_confidence": document["max_confidence"],
                "source_connectors": sorted(document["source_connectors"]),
            }
            for document_id, document in sorted(
                documents_by_id.items(),
                key=lambda item: (
                    -int(item[1]["evidence_count"]),
                    item[0],
                ),
            )
        ]

        return {
            "entity": entity,
            "aliases": aliases,
            "evidence": evidence,
            "relationships": relations,
            "connected_documents": connected_documents,
            "connected_entities": related_entity_rows,
            "summary": {
                "alias_count": len(aliases),
                "evidence_count": len(evidence),
                "relationship_count": len(relations),
                "connected_document_count": len(connected_documents),
                "connected_entity_count": len(related_entity_rows),
            },
        }

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

    async def clear_document_graph_facts(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        extraction_run_id: UUID | str | None = None,
        delete_document_node: bool = False,
    ) -> dict[str, int | bool]:
        """Remove graph facts derived from a document and prune orphaned graph nodes."""
        evidence_deleted = await self._evidence.delete_evidence_for_document(
            organization_id=organization_id,
            document_id=document_id,
            extraction_run_id=extraction_run_id,
        )
        relation_deleted = await self._relations.delete_relations_for_document(
            organization_id=organization_id,
            document_id=document_id,
            extraction_run_id=extraction_run_id,
        )
        alias_deleted = await self._entities.delete_aliases_for_document(
            organization_id=organization_id,
            document_id=document_id,
            extraction_run_id=extraction_run_id,
        )
        chunk_deleted = await self._evidence.delete_orphan_chunks_for_document(
            organization_id=organization_id,
            document_id=document_id,
        )
        orphan_entities_deleted = await self._entities.delete_orphan_entities(
            organization_id=organization_id,
        )
        document_node_deleted = False
        if delete_document_node:
            document_node_deleted = await self._documents.delete_document_node(
                organization_id=organization_id,
                document_id=document_id,
            )
        return {
            "evidence_deleted": evidence_deleted,
            "relations_deleted": relation_deleted,
            "aliases_deleted": alias_deleted,
            "chunks_deleted": chunk_deleted,
            "orphan_entities_deleted": orphan_entities_deleted,
            "document_node_deleted": document_node_deleted,
        }

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

    async def create_relation_with_evidence(
        self,
        *,
        organization_id: UUID | str,
        from_entity_id: UUID | str,
        to_entity_id: UUID | str,
        rel_type: str,
        relation_id: UUID | str,
        evidence_text: str | None = None,
        citation_text: str | None = None,
        citation_reference: str | None = None,
        chunk_id: UUID | str | None = None,
        source_document_id: UUID | str | None = None,
        page_number: int | None = None,
        workspace_id: UUID | str | None = None,
        source_connector: str | None = None,
        extraction_run_id: UUID | str | None = None,
        confidence: float = 0.5,
        initial_status: RelationStatus = "unverified",
    ) -> None:
        """Create or merge an evidence-backed relation. No-op when graph unavailable."""
        await self._relations.create_relation_with_evidence(
            organization_id=organization_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            rel_type=rel_type,
            relation_id=relation_id,
            evidence_text=evidence_text,
            citation_text=citation_text,
            citation_reference=citation_reference,
            chunk_id=chunk_id,
            source_document_id=source_document_id,
            page_number=page_number,
            workspace_id=workspace_id,
            source_connector=source_connector,
            extraction_run_id=extraction_run_id,
            confidence=confidence,
            initial_status=initial_status,
        )

    async def count_document_relations(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
    ) -> int:
        """Count evidence-backed relation edges sourced from a document."""
        return await self._relations.count_relations_for_document(
            organization_id=organization_id,
            document_id=document_id,
        )

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
        """List relations with optional filters. Returns [] when unavailable."""
        return await self._relations.list_relations(
            organization_id=organization_id,
            status=status,
            rel_type=rel_type,
            workspace_id=workspace_id,
            min_confidence=min_confidence,
            skip=skip,
            limit=limit,
        )

    async def get_relation(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
    ) -> dict | None:
        """Fetch a single relation by stable relation_id. Returns None if not found."""
        return await self._relations.get_relation(
            organization_id=organization_id,
            relation_id=relation_id,
        )

    async def update_relation_status(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
        status: RelationStatus,
    ) -> bool:
        """Transition relation status. Returns True if relation was found and updated."""
        return await self._relations.update_relation_status(
            organization_id=organization_id,
            relation_id=relation_id,
            status=status,
        )

    async def delete_relation_by_id(
        self,
        *,
        organization_id: UUID | str,
        relation_id: UUID | str,
    ) -> bool:
        """Delete a relation by its stable relation_id. Returns True if removed."""
        return await self._relations.delete_relation_by_id(
            organization_id=organization_id,
            relation_id=relation_id,
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
        """Link a Chunk to an Entity as evidence with full provenance (F282).

        Requires at least one of evidence_text, citation_text, or citation_reference.
        No-op when graph is unavailable.
        """
        await self._evidence.link_evidence(
            organization_id=organization_id,
            entity_id=entity_id,
            chunk_id=chunk_id,
            source_document_id=source_document_id,
            confidence=confidence,
            evidence_text=evidence_text,
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            page_number=page_number,
            source_connector=source_connector,
            external_url=external_url,
            extraction_run_id=extraction_run_id,
            citation_text=citation_text,
            citation_reference=citation_reference,
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

    async def get_document_provenance(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        limit: int = 100,
    ) -> list[dict]:
        """Return all evidence links for all entities extracted from a document (F282)."""
        return await self._evidence.get_document_provenance(
            organization_id=organization_id,
            document_id=document_id,
            limit=limit,
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

    async def get_document_insights(
        self,
        *,
        organization_id: UUID | str,
        document_id: UUID | str,
        entity_limit: int = 50,
        evidence_limit: int = 20,
        run_limit: int = 5,
    ) -> dict[str, object]:
        """Return graph facts extracted from a document for the Insights panel (F289).

        Aggregates:
          - entities extracted from this document, grouped by type
          - evidence snippets with chunk/page provenance for deep-links
          - relation count (edges carrying source_document_id)
          - extraction run history with status and entity counts

        Returns safe empty data when Neo4j is unavailable so the document
        details page continues to work without the graph.
        """
        entity_result = await self.search_entities(
            organization_id=organization_id,
            source_document_id=document_id,
            limit=entity_limit,
        )
        entities: list[dict] = list(entity_result.get("items") or [])
        entity_count: int = int(entity_result.get("total") or 0)

        confidences = [
            float(e["confidence"])
            for e in entities
            if e.get("confidence") is not None
        ]
        avg_confidence: float | None = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )

        entities_by_type: dict[str, int] = {}
        for entity in entities:
            entity_type = str(entity.get("entity_type") or "Unknown")
            entities_by_type[entity_type] = entities_by_type.get(entity_type, 0) + 1

        evidence: list[dict] = await self.get_document_provenance(
            organization_id=organization_id,
            document_id=document_id,
            limit=evidence_limit,
        )

        relation_count: int = await self.count_document_relations(
            organization_id=organization_id,
            document_id=document_id,
        )

        extraction_runs: list[dict] = await self.get_document_extraction_runs(
            organization_id=organization_id,
            document_id=document_id,
            limit=run_limit,
        )

        last_run_at: str | None = None
        if extraction_runs:
            last_run_at = str(extraction_runs[0].get("updated_at") or extraction_runs[0].get("created_at") or "")

        return {
            "entity_count": entity_count,
            "relation_count": relation_count,
            "avg_confidence": avg_confidence,
            "entities_by_type": entities_by_type,
            "top_entities": entities[:entity_limit],
            "recent_evidence": evidence,
            "extraction_runs": extraction_runs,
            "last_run_at": last_run_at or None,
        }

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
        relationship_types: list[str] | None = None,
    ) -> list[dict]:
        """Multi-hop entity traversal for GraphRAG context expansion."""
        return await self._graphrag.find_related_entities(
            organization_id=organization_id,
            entity_ids=entity_ids,
            depth=depth,
            limit=limit,
            relationship_types=relationship_types,
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
        document_ids: list[UUID | str] | None = None,
        confidence_threshold: float | None = None,
    ) -> list[dict]:
        """Retrieve evidence links for a set of entities (GraphRAG citation support)."""
        return await self._graphrag.get_evidence_for_entities(
            organization_id=organization_id,
            entity_ids=entity_ids,
            limit=limit,
            document_ids=document_ids,
            confidence_threshold=confidence_threshold,
        )
