"""Batched EVIDENCE_FOR links and evidence-backed relations (R06-10).

Copies of ``EvidenceRepository.link_evidence`` and
``RelationRepository.create_relation_with_evidence`` Cypher with ``$x`` replaced by
``row.x`` under ``UNWIND``: same MERGE keys, same ON CREATE / ON MATCH rules (provenance
kept unless the new value is set; a relation's provenance is replaced only by higher
confidence). EVIDENCE_FOR also gets ``organization_id``; relations already carry it in
their MERGE key. Inputs are validated for the whole call before anything is written.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.graph.repositories.batch_writes import (
    EvidenceWriteRow,
    RelationWriteRow,
    run_write_batches,
)
from app.domains.graph.schema import RELATIONSHIP_TYPES

LINK_EVIDENCE_CYPHER = """
UNWIND $rows AS row
MERGE (c:Chunk {organization_id: $organization_id, chunk_id: row.chunk_id})
ON CREATE SET
    c.source_document_id  = row.source_document_id,
    c.workspace_id        = row.workspace_id,
    c.source_connector    = row.source_connector,
    c.created_at          = $now
ON MATCH SET
    c.workspace_id        = CASE WHEN row.workspace_id IS NOT NULL
                                 THEN row.workspace_id ELSE c.workspace_id END,
    c.source_connector    = CASE WHEN row.source_connector IS NOT NULL
                                 THEN row.source_connector ELSE c.source_connector END
MERGE (e:Entity {organization_id: $organization_id, entity_id: row.entity_id})
MERGE (c)-[ev:EVIDENCE_FOR]->(e)
ON CREATE SET
    ev.organization_id       = $organization_id,
    ev.source_document_id    = row.source_document_id,
    ev.workspace_id          = row.workspace_id,
    ev.document_version_id   = row.document_version_id,
    ev.page_number           = row.page_number,
    ev.source_connector      = row.source_connector,
    ev.external_url          = row.external_url,
    ev.extraction_run_id     = row.extraction_run_id,
    ev.confidence            = row.confidence,
    ev.evidence_text         = row.evidence_text,
    ev.citation_text         = row.citation_text,
    ev.citation_reference    = row.citation_reference,
    ev.created_at            = $now
ON MATCH SET
    ev.organization_id       = $organization_id,
    ev.workspace_id          = CASE WHEN row.workspace_id IS NOT NULL
                                    THEN row.workspace_id ELSE ev.workspace_id END,
    ev.document_version_id   = CASE WHEN row.document_version_id IS NOT NULL
                                    THEN row.document_version_id
                                    ELSE ev.document_version_id END,
    ev.page_number           = CASE WHEN row.page_number IS NOT NULL
                                    THEN row.page_number ELSE ev.page_number END,
    ev.source_connector      = CASE WHEN row.source_connector IS NOT NULL
                                    THEN row.source_connector ELSE ev.source_connector END,
    ev.external_url          = CASE WHEN row.external_url IS NOT NULL
                                    THEN row.external_url ELSE ev.external_url END,
    ev.extraction_run_id     = CASE WHEN row.extraction_run_id IS NOT NULL
                                    THEN row.extraction_run_id ELSE ev.extraction_run_id END,
    ev.confidence            = row.confidence,
    ev.evidence_text         = CASE WHEN row.evidence_text IS NOT NULL
                                    THEN row.evidence_text ELSE ev.evidence_text END,
    ev.citation_text         = CASE WHEN row.citation_text IS NOT NULL
                                    THEN row.citation_text ELSE ev.citation_text END,
    ev.citation_reference    = CASE WHEN row.citation_reference IS NOT NULL
                                    THEN row.citation_reference
                                    ELSE ev.citation_reference END,
    ev.updated_at            = $now
"""

# ``{rel_type}`` is interpolated only after validation against the schema vocabulary.
_RELATION_CYPHER_TEMPLATE = """
UNWIND $rows AS row
MATCH (a:Entity {{organization_id: $organization_id, entity_id: row.from_entity_id}})
MATCH (b:Entity {{organization_id: $organization_id, entity_id: row.to_entity_id}})
MERGE (a)-[r:{rel_type} {{organization_id: $organization_id,
                          from_entity_id: row.from_entity_id,
                          to_entity_id: row.to_entity_id}}]->(b)
ON CREATE SET
    r.relation_id          = row.relation_id,
    r.status               = row.status,
    r.confidence           = row.confidence,
    r.evidence_text        = row.evidence_text,
    r.citation_text        = row.citation_text,
    r.citation_reference   = row.citation_reference,
    r.chunk_id             = row.chunk_id,
    r.source_document_id   = row.source_document_id,
    r.page_number          = row.page_number,
    r.workspace_id         = row.workspace_id,
    r.source_connector     = row.source_connector,
    r.extraction_run_id    = row.extraction_run_id,
    r.created_at           = $now,
    r.updated_at           = $now
ON MATCH SET
    r.updated_at           = $now,
    r.confidence           = CASE WHEN row.confidence > r.confidence
                                  THEN row.confidence ELSE r.confidence END,
    r.evidence_text        = CASE WHEN row.confidence > r.confidence
                                  THEN row.evidence_text ELSE r.evidence_text END,
    r.citation_text        = CASE WHEN row.confidence > r.confidence
                                  THEN row.citation_text ELSE r.citation_text END,
    r.citation_reference   = CASE WHEN row.confidence > r.confidence
                                  THEN row.citation_reference ELSE r.citation_reference END,
    r.chunk_id             = CASE WHEN row.confidence > r.confidence
                                  THEN row.chunk_id ELSE r.chunk_id END,
    r.source_document_id   = CASE WHEN row.confidence > r.confidence
                                  THEN row.source_document_id ELSE r.source_document_id END,
    r.page_number          = CASE WHEN row.confidence > r.confidence
                                  THEN row.page_number ELSE r.page_number END,
    r.extraction_run_id    = CASE WHEN row.confidence > r.confidence
                                  THEN row.extraction_run_id ELSE r.extraction_run_id END
"""

_RELATION_STATUSES = frozenset({"unverified", "verified", "rejected", "low_confidence"})


def relation_cypher(rel_type: str) -> str:
    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"Unknown relationship type '{rel_type}'. Valid types: {', '.join(RELATIONSHIP_TYPES)}"
        )
    return _RELATION_CYPHER_TEMPLATE.format(rel_type=rel_type)


def _validate_evidence(rows: Sequence[EvidenceWriteRow]) -> None:
    for row in rows:
        if not any([row.evidence_text, row.citation_text, row.citation_reference]):
            raise ValueError(
                "provenance_required: at least one of evidence_text, citation_text, "
                "or citation_reference must be provided"
            )


def _validate_relations(rows: Sequence[RelationWriteRow]) -> None:
    for row in rows:
        relation_cypher(row.rel_type)
        if row.initial_status not in _RELATION_STATUSES:
            raise ValueError(f"Unknown relation status '{row.initial_status}'")
        if not any([row.evidence_text, row.citation_text, row.citation_reference]):
            raise ValueError(
                "create_relations_with_evidence_batch requires at least one of: "
                "evidence_text, citation_text, citation_reference"
            )


class EvidenceBatchWriteMixin:
    """``link_evidence_batch`` for EvidenceRepository."""

    async def link_evidence_batch(
        self, *, organization_id: UUID | str, rows: Sequence[EvidenceWriteRow]
    ) -> int:
        """MERGE every Chunk -EVIDENCE_FOR-> Entity link; ValueError if one lacks text."""
        _validate_evidence(rows)
        org = str(organization_id)
        now = datetime.now(UTC).isoformat()

        async def _work(tx: Any, batch: list[dict[str, Any]]) -> None:
            await tx.run(LINK_EVIDENCE_CYPHER, rows=batch, organization_id=org, now=now)

        return await run_write_batches(
            kind="evidence",
            organization_id=organization_id,
            rows=[row.params() for row in rows],
            work=_work,
        )


class RelationBatchWriteMixin:
    """``create_relations_with_evidence_batch`` for RelationRepository."""

    async def create_relations_with_evidence_batch(
        self, *, organization_id: UUID | str, rows: Sequence[RelationWriteRow]
    ) -> int:
        """MERGE evidence-backed relations; one transaction per batch, one statement per type.

        Raises ValueError (before writing) for an unknown type or status or missing evidence.
        """
        _validate_relations(rows)
        org = str(organization_id)
        now = datetime.now(UTC).isoformat()

        async def _work(tx: Any, batch: list[dict[str, Any]]) -> None:
            by_type: dict[str, list[dict[str, Any]]] = {}
            for row in batch:
                by_type.setdefault(row["rel_type"], []).append(row)
            for rel_type, typed_rows in by_type.items():
                await tx.run(
                    relation_cypher(rel_type), rows=typed_rows, organization_id=org, now=now
                )

        return await run_write_batches(
            kind="relation",
            organization_id=organization_id,
            rows=[row.params() for row in rows],
            work=_work,
        )
