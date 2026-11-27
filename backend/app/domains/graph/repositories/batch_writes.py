"""Batched Neo4j writes: row types and the per-batch transaction runner (R06-10).

Ingestion writes entities, aliases, evidence links and relations with ``UNWIND $rows``
statements, one ``session.execute_write`` transaction per ``GRAPH_WRITE_BATCH_SIZE`` rows,
instead of one transaction per item. Every statement binds a single ``$organization_id``
that is set on every node and relationship it writes, so a batch can never mix tenants.
Like the single-item methods, a failed batch is logged and skipped (graph outages never
fail ingestion); the caller gets the number of batches written.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.core.metrics_workers import record_graph_write_batch
from app.domains.graph.repositories._base import _get_driver_and_settings

logger = get_logger("graph.repositories.batch")

BatchWork = Callable[[Any, list[dict[str, Any]]], Awaitable[None]]


def _str_or_none(value: UUID | str | None) -> str | None:
    return str(value) if value is not None and value != "" else None


@dataclass(frozen=True)
class EntityWriteRow:
    entity_id: UUID | str
    entity_type: str
    canonical_name: str
    normalized_name: str
    resolution_status: str | None = None
    resolution_confidence: float | None = None
    language: str | None = None
    aliases: list[str] | None = None
    workspace_id: UUID | str | None = None
    external_source_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def params(self) -> dict[str, Any]:
        values = asdict(self)
        values["entity_id"] = str(self.entity_id)
        values["workspace_id"] = _str_or_none(self.workspace_id)
        return values


@dataclass(frozen=True)
class AliasWriteRow:
    entity_id: UUID | str
    alias_id: UUID | str
    alias_name: str
    normalized_name: str
    source_document_id: UUID | str | None = None
    chunk_id: UUID | str | None = None
    workspace_id: UUID | str | None = None
    source_external_id: str | None = None
    source_connector: str | None = None
    language: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None

    def params(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("entity_id", "alias_id"):
            values[key] = str(values[key])
        for key in ("source_document_id", "chunk_id", "workspace_id"):
            values[key] = _str_or_none(values[key])
        return values


@dataclass(frozen=True)
class EvidenceWriteRow:
    entity_id: UUID | str
    chunk_id: UUID | str
    source_document_id: UUID | str
    confidence: float | None = None
    evidence_text: str | None = None
    workspace_id: UUID | str | None = None
    document_version_id: str | None = None
    page_number: int | None = None
    source_connector: str | None = None
    external_url: str | None = None
    extraction_run_id: UUID | str | None = None
    citation_text: str | None = None
    citation_reference: str | None = None

    def params(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("entity_id", "chunk_id", "source_document_id"):
            values[key] = str(values[key])
        for key in ("workspace_id", "extraction_run_id"):
            values[key] = _str_or_none(values[key])
        return values


@dataclass(frozen=True)
class RelationWriteRow:
    from_entity_id: UUID | str
    to_entity_id: UUID | str
    rel_type: str
    relation_id: UUID | str
    evidence_text: str | None = None
    citation_text: str | None = None
    citation_reference: str | None = None
    chunk_id: UUID | str | None = None
    source_document_id: UUID | str | None = None
    page_number: int | None = None
    workspace_id: UUID | str | None = None
    source_connector: str | None = None
    extraction_run_id: UUID | str | None = None
    confidence: float = 0.5
    initial_status: str = "unverified"

    def params(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("from_entity_id", "to_entity_id", "relation_id"):
            values[key] = str(values[key])
        for key in ("chunk_id", "source_document_id", "workspace_id", "extraction_run_id"):
            values[key] = _str_or_none(values[key])
        values["status"] = values.pop("initial_status")
        return values


def batch_size() -> int:
    from app.core.config import settings

    return max(1, int(settings.graph_write_batch_size))


def split_rows(rows: Sequence[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [list(rows[start : start + size]) for start in range(0, len(rows), size)]


def _log_failure(
    kind: str, organization_id: UUID | str, exc: Exception, *, batch_index: int, rows: int
) -> None:
    record_graph_write_batch(kind, "failed")
    logger.warning(
        "graph.batch_write.failed",
        kind=kind,
        organization_id=str(organization_id),
        batch_index=batch_index,
        batch_rows=rows,
        error=exc.__class__.__name__,
    )


async def run_write_batches(
    *,
    kind: str,
    organization_id: UUID | str,
    rows: Sequence[dict[str, Any]],
    work: BatchWork,
) -> int:
    """Write ``rows`` in batches, one write transaction each; returns batches written."""
    if not rows:
        return 0
    driver, settings = _get_driver_and_settings()
    if driver is None:
        return 0
    written = 0
    batches = split_rows(rows, batch_size())
    try:
        async with driver.session(database=settings.neo4j_database) as session:
            for index, batch in enumerate(batches):

                async def _tx(tx: Any, batch: list[dict[str, Any]] = batch) -> None:
                    await work(tx, batch)

                try:
                    await session.execute_write(_tx)
                except Exception as exc:
                    _log_failure(kind, organization_id, exc, batch_index=index, rows=len(batch))
                    continue
                written += 1
                record_graph_write_batch(kind, "written")
    except Exception as exc:  # the session itself could not be opened or closed
        _log_failure(kind, organization_id, exc, batch_index=written, rows=len(rows))
    logger.debug(
        "graph.batch_write.completed",
        kind=kind,
        organization_id=str(organization_id),
        rows=len(rows),
        batches=len(batches),
        written=written,
    )
    return written
