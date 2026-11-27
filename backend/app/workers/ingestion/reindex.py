"""Graph re-extraction for an existing document (moved from document_tasks, R06-01)."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.document_errors import details_from_exception
from app.models.enums import DocumentStatus, GraphExtractionStatus
from app.workers.base_task import PermanentTaskError
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import parse_uuid
from app.workers.ingestion.recorder import PipelineRunRecorder


async def _reindex_document_graph_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    deps = current_deps()
    try:
        parsed_document_id = parse_uuid(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc

    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=parsed_document_id
        )
        if document is None:
            raise PermanentTaskError(f"Document not found: {document_id}")
        chunks = await deps.document_repository.list_document_chunks(
            session,
            document_id=document.id,
            index_version=settings.document_index_version,
        )

    if document.status == DocumentStatus.deleted.value:
        raise PermanentTaskError(
            f"Cannot re-run graph extraction for deleted document: {document_id}"
        )
    if document.status == DocumentStatus.deleting.value:
        raise PermanentTaskError(
            f"Cannot re-run graph extraction while deleting document: {document_id}"
        )

    if not chunks:
        await deps.update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.skipped.value,
            run_id=None,
        )
        return {"document_id": document_id, "status": GraphExtractionStatus.skipped.value}

    pipeline_recorder = await PipelineRunRecorder.create(
        document_id=document_id,
        organization_id=organization_id or str(document.organization_id),
        user_id=user_id or str(document.uploaded_by_user_id),
        organization_uuid=document.organization_id,
        document_uuid=document.id,
        pipeline_type="document.graph_reindex",
        inputs={
            "request_id": request_id,
            "document_id": str(document.id),
            "filename": document.filename,
            "file_type": document.file_type,
        },
        config={
            "index_version": settings.document_index_version,
            "entity_extraction_enabled": settings.feature_enable_entity_extraction,
            "relation_extraction_enabled": settings.feature_enable_relation_extraction,
        },
    )

    try:
        result = await deps.run_document_graph_extraction_async(
            document,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="document.graph_reindex",
            chunk_pairs=[(chunk.chunk_index, chunk.text) for chunk in chunks if chunk.text.strip()],
            chunk_id_by_index={chunk.chunk_index: chunk.id for chunk in chunks},
            page_by_index={chunk.chunk_index: chunk.page_number for chunk in chunks},
            pipeline_recorder=pipeline_recorder,
            clear_existing_facts=True,
        )
        await pipeline_recorder.finalize_run(
            status="completed",
            outputs={
                "document_status": DocumentStatus.indexed.value,
                "graph_status": GraphExtractionStatus.completed.value,
                "chunk_count": len(chunks),
                "entity_count": result["entity_count"],
                "relation_count": result["relation_count"],
            },
        )
        return {
            "document_id": document_id,
            "status": GraphExtractionStatus.completed.value,
            "chunk_count": len(chunks),
            "entity_count": result["entity_count"],
            "relation_count": result["relation_count"],
        }
    except Exception as exc:
        details = details_from_exception(exc)
        await pipeline_recorder.fail_stage_if_open(
            stage=details.get("stage", "graph_reindex"),
            error_message=details.get("message", str(exc)),
            error_details=details,
        )
        await pipeline_recorder.finalize_run(
            status="failed",
            error_message=details.get("message", str(exc)),
            error_details=details,
            outputs={"chunk_count": len(chunks)},
        )
        await deps.update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.failed.value,
            run_id=None,
        )
        raise


def run_graph_reindex_task(
    document_id: str,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
) -> dict[str, str | int]:
    """Body of ``documents.graph_reindex``."""
    deps = current_deps()
    try:
        status = deps.get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")
    result: dict[str, str | int] = deps.run(
        deps.reindex_document_graph_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    return result


def run_reindex_task(
    task: Any,
    document_id: str,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    chunking_profile_config: dict | None,
    force: bool,
) -> dict[str, str | int | float]:
    """Body of ``documents.reindex``: the process body in reindex mode."""
    from app.workers.ingestion.process import REINDEX, run_document_task

    return run_document_task(
        task,
        document_id,
        mode=REINDEX,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        force=force,
        chunking_profile_config=chunking_profile_config,
    )
