"""Graph write rows for one document's extraction run (R06-10).

The extraction results are turned into entity, alias, evidence and relation rows with the
same values the per-item writes used, then written with the GraphService batch methods
(one Neo4j write transaction per ``GRAPH_WRITE_BATCH_SIZE`` rows of each kind) instead of
one transaction per item. Entity resolution still reads the graph once per entity, before
any of this run's writes land: within one document an entity can no longer resolve
against another entity first seen in the same run (exact duplicates still merge through
their deterministic ids). Resolution is off by default (``FEATURE_ENABLE_ENTITY_RESOLUTION``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.graph.repositories.batch_writes import (
    AliasWriteRow,
    EntityWriteRow,
    EvidenceWriteRow,
    RelationWriteRow,
)
from app.domains.graph.services.entity_resolution_service import EntityResolutionInput


@dataclass
class EntityWrites:
    entities: list[EntityWriteRow] = field(default_factory=list)
    aliases: list[AliasWriteRow] = field(default_factory=list)
    evidence: list[EvidenceWriteRow] = field(default_factory=list)


async def _resolve(deps: Any, document: Any, item: Any) -> tuple[Any, str, float, str]:
    """(entity id, resolution status, confidence, canonical name) for one extracted item."""
    if not settings.feature_enable_entity_resolution:
        return item.entity_id, "new", item.confidence, item.name
    result = await deps.graph_service.resolve_entity(
        organization_id=document.organization_id,
        entity_type=item.type,
        canonical_name=item.name,
        original_name=item.original_name,
        aliases=item.aliases,
        language=item.language,
    )
    return (
        result.canonical_entity_id,
        result.status,
        result.candidate_score,
        result.canonical_name,
    )


async def collect_entity_writes(
    deps: Any,
    document: Any,
    entities: list[Any],
    *,
    chunk_id_by_index: dict[int, UUID | None],
    page_by_index: dict[int, int | None],
    extraction_run_id: UUID,
) -> EntityWrites:
    writes = EntityWrites()
    for item in entities:
        chunk_db_id = chunk_id_by_index.get(item.source_chunk_index)
        entity_id, status, confidence, canonical_name = await _resolve(deps, document, item)
        aliases = list(dict.fromkeys([item.original_name, item.name, *item.aliases]))
        resolution_input = EntityResolutionInput(
            organization_id=str(document.organization_id),
            entity_type=item.type,
            canonical_name=canonical_name,
            original_name=item.original_name,
            aliases=list(item.aliases),
            source_external_id=None,
            source_connector=None,
            language=item.language,
        )
        alias_name = item.original_name or item.name
        alias_id = deps.entity_resolution_service.build_alias_id(
            input_=resolution_input,
            entity_id=entity_id,
            alias_name=alias_name,
            source_document_id=str(document.id),
            chunk_id=str(chunk_db_id) if chunk_db_id is not None else None,
        )
        writes.entities.append(
            EntityWriteRow(
                entity_id=entity_id,
                entity_type=item.type,
                canonical_name=canonical_name,
                normalized_name=canonical_name.lower().strip(),
                resolution_status=status,
                resolution_confidence=confidence,
                language=item.language,
                aliases=aliases,
                extra={
                    "original_name": item.original_name,
                    "aliases": aliases,
                    "language": item.language,
                },
            )
        )
        # The per-item alias write took ``language`` from its own (unset) argument, not
        # from properties; the row keeps that value.
        writes.aliases.append(
            AliasWriteRow(
                entity_id=entity_id,
                alias_id=alias_id,
                alias_name=alias_name,
                normalized_name=item.name.lower().strip(),
                source_document_id=document.id,
                chunk_id=chunk_db_id,
                confidence=item.confidence,
                evidence_text=item.evidence_span,
            )
        )
        if chunk_db_id is not None:
            writes.evidence.append(
                EvidenceWriteRow(
                    entity_id=entity_id,
                    chunk_id=chunk_db_id,
                    source_document_id=document.id,
                    confidence=item.confidence,
                    citation_text=item.evidence_span,
                    citation_reference=f"{document.filename}, chunk {item.source_chunk_index}",
                    extraction_run_id=extraction_run_id,
                    page_number=page_by_index.get(item.source_chunk_index),
                )
            )
    return writes


async def write_entity_rows(deps: Any, organization_id: Any, writes: EntityWrites) -> None:
    """Entities first (aliases MATCH them), then aliases, then evidence links."""
    graph = deps.graph_service
    await graph.upsert_entities_batch(organization_id=organization_id, rows=writes.entities)
    await graph.upsert_entity_aliases_batch(organization_id=organization_id, rows=writes.aliases)
    await graph.link_evidence_batch(organization_id=organization_id, rows=writes.evidence)


def relation_rows(
    deps: Any,
    document: Any,
    relations: list[Any],
    *,
    chunk_id_by_index: dict[int, UUID | None],
    page_by_index: dict[int, int | None],
    extraction_run_id: UUID,
) -> list[RelationWriteRow]:
    rows: list[RelationWriteRow] = []
    for item in relations:
        status = (
            deps.relation_extraction_service.compute_initial_status(item.confidence)
            if not settings.relation_extraction_review_mode
            else "unverified"
        )
        rows.append(
            RelationWriteRow(
                from_entity_id=item.from_entity_id,
                to_entity_id=item.to_entity_id,
                rel_type=item.rel_type,
                relation_id=item.relation_id,
                citation_text=item.evidence_span,
                citation_reference=f"{document.filename}, chunk {item.source_chunk_index}",
                chunk_id=chunk_id_by_index.get(item.source_chunk_index),
                source_document_id=document.id,
                page_number=page_by_index.get(item.source_chunk_index),
                extraction_run_id=extraction_run_id,
                confidence=item.confidence,
                initial_status=status,
            )
        )
    return rows
