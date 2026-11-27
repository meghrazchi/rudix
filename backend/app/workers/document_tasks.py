"""Document Celery tasks: a compatibility facade over ``app.workers.ingestion`` (R06-01).

Task names, signatures, and return values are unchanged (``documents.process``,
``.reindex``, ``.delete``, ``.graph_reindex``, ``.backfill``). The module keeps the
collaborator singletons and helper names callers and tests rebind; the stages read them
from this module at call time through ``app.workers.ingestion.deps.current_deps()``.

Ingestion runs as stages (``extract, clean_detect, dlp, chunk, graph_extract, embed,
index, finalize``) recorded in ``document_processing_stages`` with intermediate artifacts in
``document_stage_artifacts``. The run id is the claim's task id, so a Celery retry or an
``acks_late`` redelivery of the same task resumes after its last completed stage.
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from app.core.config import settings
from app.core.logging import log_chunking_event, log_document_event
from app.db.session import SessionLocal
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.embedding_service import EmbeddingResult, EmbeddingService
from app.domains.documents.services.ocr_quality_service import OcrQualityService
from app.domains.documents.services.qdrant_service import QdrantService
from app.domains.documents.services.text_normalization import TextCleaningStats
from app.domains.graph.services.entity_extraction_service import EntityExtractionService
from app.domains.graph.services.entity_resolution_service import EntityResolutionService
from app.domains.graph.services.graph_service import GraphService
from app.domains.graph.services.relation_extraction_service import RelationExtractionService
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.ingestion.audit import _record_worker_audit, _record_worker_audit_async
from app.workers.ingestion.backfill import _backfill_dispatch_async, run_backfill_task
from app.workers.ingestion.deletion import _delete_document_assets_async, run_delete_task
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.errors import parse_optional_uuid as _parse_optional_uuid
from app.workers.ingestion.errors import parse_uuid as _parse_uuid
from app.workers.ingestion.errors import safe_duration_ms as _safe_duration_ms
from app.workers.ingestion.graph import (
    _run_document_graph_extraction_async,
    _update_document_graph_status_async,
)
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pipeline import extract_and_store
from app.workers.ingestion.process import PROCESS, run_document_task
from app.workers.ingestion.recorder import PipelineRunRecorder
from app.workers.ingestion.reindex import (
    _reindex_document_graph_async,
    run_graph_reindex_task,
    run_reindex_task,
)
from app.workers.ingestion.stages.index import _upsert_connector_chunk_references
from app.workers.ingestion.storage import (
    _delete_objects_by_prefix,
    _object_key_prefix,
    _read_object_bytes,
)
from app.workers.ingestion.task_base import DocumentDeleteTask, DocumentTask
from app.workers.status_tracking import (
    claim_document_for_processing,
    get_document_status,
    mark_document_failed,
    set_document_status,
)

__all__ = [
    "DocumentDeleteTask",
    "DocumentPipelinePermanentError",
    "DocumentPipelineTransientError",
    "DocumentTask",
    "PermanentTaskError",
    "PipelineRunRecorder",
    "TransientTaskError",
    "_delete_objects_by_prefix",
    "_object_key_prefix",
    "_parse_optional_uuid",
    "_parse_uuid",
    "_read_object_bytes",
    "_safe_duration_ms",
    "_upsert_connector_chunk_references",
    "backfill_documents",
    "celery_app",
    "delete_document",
    "process_document",
    "reindex_document",
    "reindex_document_graph",
]

_document_repository = DocumentRepository()
_connector_repository = ConnectorRepository()
_pipeline_repository = PipelineRepository()
_usage_repository = UsageRepository()
_audit_log_service = AuditLogService()
_chunking_service = ChunkingService(strategy=settings.chunking_strategy)
_source_provenance_service = SourceProvenanceService()
_graph_service = GraphService()
_entity_resolution_service = EntityResolutionService()
_entity_extraction_service = EntityExtractionService(
    batch_size=settings.entity_extraction_batch_size,
    timeout_seconds=settings.entity_extraction_timeout_seconds,
    max_retries=settings.entity_extraction_max_retries,
)
_relation_extraction_service = RelationExtractionService(
    batch_size=settings.relation_extraction_batch_size,
    timeout_seconds=settings.relation_extraction_timeout_seconds,
    max_retries=settings.relation_extraction_max_retries,
    confidence_threshold=settings.relation_confidence_threshold,
)
_embedding_service = EmbeddingService()
_qdrant_service = QdrantService()
_ocr_quality_service = OcrQualityService()

# Re-exported names other modules and tests patch on this module.
_REEXPORTED = (
    SessionLocal,
    log_chunking_event,
    log_document_event,
    claim_document_for_processing,
    get_document_status,
    mark_document_failed,
    set_document_status,
    _record_worker_audit,
    _record_worker_audit_async,
    _delete_document_assets_async,
    _backfill_dispatch_async,
    _run_document_graph_extraction_async,
    _update_document_graph_status_async,
    _reindex_document_graph_async,
)


def _make_chunking_service(
    profile_config: dict | None = None,
    *,
    index_version: str | None = None,
) -> ChunkingService:
    """Return a ChunkingService for the given inline profile config, or the system default.

    Accepted profile_config keys: strategy, chunk_size_tokens, chunk_overlap_tokens.
    Unknown keys are ignored.  Raises ValueError for invalid combinations
    (e.g. overlap >= size); callers should convert this to PermanentTaskError.
    """
    if not profile_config and index_version is None:
        return _chunking_service
    return ChunkingService(
        strategy=profile_config.get("strategy") if profile_config else settings.chunking_strategy,
        chunk_size_tokens=(
            profile_config.get("chunk_size_tokens")
            if profile_config
            else settings.chunk_size_tokens
        ),
        chunk_overlap_tokens=(
            profile_config.get("chunk_overlap_tokens")
            if profile_config
            else settings.chunk_overlap_tokens
        ),
        index_version=index_version,
    )


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


async def _extract_and_store_document_pages_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    pipeline_type: str = "document.process",
    chunking_service: ChunkingService | None = None,
    profile_source: str = "system_default",
    persist_document_state: bool = True,
    persist_document_pages: bool = True,
    record_usage_event: bool = True,
    run_id: str | None = None,
    claim_token: str | None = None,
) -> tuple[int, int, TextCleaningStats, EmbeddingResult]:
    """Run the ingestion stages for one document.

    Returns ``(page_count, chunk_count, cleaning_stats, embedding_result)``; the embedding
    result is aggregated from the embed batches and carries no vectors. ``run_id`` and
    ``claim_token`` are the claiming task's id (a new ``adhoc-`` run when omitted, and no
    claim check). With ``persist_document_state=False`` (evaluation re-ingest) stage state
    stays in memory and the document's status, graph facts, and usage are not touched.
    """
    return await extract_and_store(
        document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        options=IngestionOptions(
            pipeline_type=pipeline_type,
            chunking_service=chunking_service,
            profile_source=profile_source,
            persist_document_state=persist_document_state,
            persist_document_pages=persist_document_pages,
            record_usage_event=record_usage_event,
        ),
        run_id=run_id,
        claim_token=claim_token,
    )


@celery_app.task(name="documents.graph_reindex", bind=True, base=RudixTask, ignore_result=True)
def reindex_document_graph(
    self: RudixTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    """Re-run graph extraction for an existing document."""
    return run_graph_reindex_task(
        document_id, request_id=request_id, organization_id=organization_id, user_id=user_id
    )


@celery_app.task(name="documents.process", bind=True, base=DocumentTask, ignore_result=True)
def process_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
    chunking_profile_config: dict | None = None,
) -> dict[str, str | int | float]:
    """Extract text and persist document_pages before marking a document as indexed."""
    return run_document_task(
        self,
        document_id,
        mode=PROCESS,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        force=force,
        chunking_profile_config=chunking_profile_config,
    )


@celery_app.task(name="documents.delete", bind=True, base=DocumentDeleteTask, ignore_result=True)
def delete_document(
    self: DocumentDeleteTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str]:
    """Delete document vectors/storage assets and mark metadata as deleted."""
    return run_delete_task(
        document_id, request_id=request_id, organization_id=organization_id, user_id=user_id
    )


@celery_app.task(name="documents.reindex", bind=True, base=DocumentTask, ignore_result=True)
def reindex_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    chunking_profile_config: dict | None = None,
    force: bool = False,
) -> dict[str, str | int | float]:
    """Re-index a document idempotently for the active index/model version."""
    return run_reindex_task(
        self,
        document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        chunking_profile_config=chunking_profile_config,
        force=force,
    )


@celery_app.task(name="documents.backfill", bind=True, base=DocumentTask, ignore_result=True)
def backfill_documents(
    self: DocumentTask,
    *,
    organization_id: str,
    chunking_profile_config: dict | None = None,
    request_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    """Queue reindex tasks for all indexed documents in the given organization.

    Uses chunking_profile_config when provided; falls back to the system default.
    Safe to re-run: each dispatched reindex task is itself idempotent.
    """
    return run_backfill_task(
        organization_id=organization_id,
        chunking_profile_config=chunking_profile_config,
        request_id=request_id,
        user_id=user_id,
    )
