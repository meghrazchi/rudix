"""Collaborators of the ingestion stages, read from the ``document_tasks`` facade (R06-01).

Tests and callers rebind module globals of ``app.workers.document_tasks`` (``SessionLocal``,
``_qdrant_service``, ``_embedding_service``, ...). ``current_deps()`` reads those names from
the module object at call time, so a rebinding on the facade reaches every stage. The
facade is imported lazily because it imports this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionDeps:
    SessionLocal: Any
    document_repository: Any
    connector_repository: Any
    pipeline_repository: Any
    usage_repository: Any
    audit_log_service: Any
    chunking_service: Any
    source_provenance_service: Any
    graph_service: Any
    entity_resolution_service: Any
    entity_extraction_service: Any
    relation_extraction_service: Any
    embedding_service: Any
    qdrant_service: Any
    ocr_quality_service: Any
    claim_document_for_processing: Any
    set_document_status: Any
    mark_document_failed: Any
    get_document_status: Any
    log_document_event: Any
    log_chunking_event: Any
    record_worker_audit: Any
    record_worker_audit_async: Any
    update_document_graph_status_async: Any
    run_document_graph_extraction_async: Any
    reindex_document_graph_async: Any
    extract_and_store_document_pages_async: Any
    delete_document_assets_async: Any
    backfill_dispatch_async: Any
    make_chunking_service: Any
    run: Any


# Dataclass field -> attribute name on the facade module.
_FACADE_NAMES: dict[str, str] = {
    "SessionLocal": "SessionLocal",
    "document_repository": "_document_repository",
    "connector_repository": "_connector_repository",
    "pipeline_repository": "_pipeline_repository",
    "usage_repository": "_usage_repository",
    "audit_log_service": "_audit_log_service",
    "chunking_service": "_chunking_service",
    "source_provenance_service": "_source_provenance_service",
    "graph_service": "_graph_service",
    "entity_resolution_service": "_entity_resolution_service",
    "entity_extraction_service": "_entity_extraction_service",
    "relation_extraction_service": "_relation_extraction_service",
    "embedding_service": "_embedding_service",
    "qdrant_service": "_qdrant_service",
    "ocr_quality_service": "_ocr_quality_service",
    "claim_document_for_processing": "claim_document_for_processing",
    "set_document_status": "set_document_status",
    "mark_document_failed": "mark_document_failed",
    "get_document_status": "get_document_status",
    "log_document_event": "log_document_event",
    "log_chunking_event": "log_chunking_event",
    "record_worker_audit": "_record_worker_audit",
    "record_worker_audit_async": "_record_worker_audit_async",
    "update_document_graph_status_async": "_update_document_graph_status_async",
    "run_document_graph_extraction_async": "_run_document_graph_extraction_async",
    "reindex_document_graph_async": "_reindex_document_graph_async",
    "extract_and_store_document_pages_async": "_extract_and_store_document_pages_async",
    "delete_document_assets_async": "_delete_document_assets_async",
    "backfill_dispatch_async": "_backfill_dispatch_async",
    "make_chunking_service": "_make_chunking_service",
    "run": "_run",
}

REBINDABLE_FACADE_NAMES: tuple[str, ...] = tuple(_FACADE_NAMES.values())


def current_deps() -> IngestionDeps:
    """Snapshot the facade's current bindings."""
    from app.workers import document_tasks as facade

    return IngestionDeps(**{field: getattr(facade, name) for field, name in _FACADE_NAMES.items()})
