"""Document deletion: vectors, storage, graph facts, metadata (moved from document_tasks).

R06-01: the metadata transaction also deletes the document's ingestion stage rows and
stage artifacts (F143 deletion lifecycle). Collaborators come from ``current_deps()``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.document_errors import details_from_exception
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.enums import DocumentStatus
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
    parse_uuid,
)
from app.workers.ingestion.recorder import PipelineRunRecorder
from app.workers.ingestion.storage import _delete_objects_by_prefix, _object_key_prefix


async def delete_stage_state(
    session: AsyncSession, *, organization_id: UUID, document_id: UUID
) -> None:
    """Delete every stage row and artifact of the document, scoped to its organisation."""
    for model in (DocumentStageArtifact, DocumentProcessingStage):
        await session.execute(
            delete(model).where(
                model.organization_id == organization_id, model.document_id == document_id
            )
        )


async def _delete_document_assets_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    pipeline_type: str = "document.delete",
) -> tuple[int, int]:
    deps = current_deps()
    try:
        parsed_document_id = parse_uuid(document_id)
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="resolve_document",
            code="INVALID_DOCUMENT_ID",
            category="validation",
            message=f"Invalid document_id: {document_id}",
        ) from exc

    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=parsed_document_id
        )
        if document is None:
            raise DocumentPipelinePermanentError(
                stage="resolve_document",
                code="DOCUMENT_NOT_FOUND",
                category="validation",
                message=f"Document not found: {document_id}",
            )

        resolved_organization_id = organization_id or str(document.organization_id)
        resolved_user_id = user_id or str(document.uploaded_by_user_id)
        pipeline_recorder = await PipelineRunRecorder.create(
            document_id=document_id,
            organization_id=resolved_organization_id,
            user_id=resolved_user_id,
            organization_uuid=document.organization_id,
            document_uuid=document.id,
            pipeline_type=pipeline_type,
            inputs={
                "request_id": request_id,
                "document_id": str(document.id),
                "filename": document.filename,
                "file_type": document.file_type,
            },
            config={"qdrant_collection": settings.qdrant_collection},
        )

        current_stage = "delete_index"
        deleted_chunks = 0
        deleted_pages = 0
        try:
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_index",
                stage_status="started",
            )
            await pipeline_recorder.emit_stage(stage="delete_index", stage_status="started")
            try:
                await deps.qdrant_service.delete_document_points(
                    organization_id=document.organization_id,
                    document_id=document.id,
                )
            except ValueError as exc:
                raise DocumentPipelinePermanentError(
                    stage="delete_index",
                    code="QDRANT_DELETE_FILTER_INVALID",
                    category="validation",
                    message=str(exc),
                ) from exc
            except Exception as exc:
                raise DocumentPipelineTransientError(
                    stage="delete_index",
                    code="QDRANT_DELETE_FAILED",
                    category="infrastructure",
                    message="qdrant delete failed",
                ) from exc
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_index",
                stage_status="completed",
            )
            await pipeline_recorder.emit_stage(stage="delete_index", stage_status="completed")

            current_stage = "delete_storage"
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_storage",
                stage_status="started",
            )
            await pipeline_recorder.emit_stage(
                stage="delete_storage",
                stage_status="started",
                inputs={
                    "bucket": document.storage_bucket,
                    "object_key": document.storage_object_key,
                },
            )
            object_prefix = _object_key_prefix(document.storage_object_key)
            if not object_prefix:
                raise DocumentPipelinePermanentError(
                    stage="delete_storage",
                    code="SOURCE_OBJECT_KEY_INVALID",
                    category="validation",
                    message="document storage object key is empty",
                )
            try:
                deleted_object_count = _delete_objects_by_prefix(
                    bucket=document.storage_bucket,
                    prefix=object_prefix,
                )
            except TransientTaskError as exc:
                raise DocumentPipelineTransientError(
                    stage="delete_storage",
                    code="SOURCE_OBJECT_DELETE_FAILED",
                    category="infrastructure",
                    message=str(exc),
                ) from exc
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_storage",
                stage_status="completed",
                deleted_object_count=deleted_object_count,
            )
            await pipeline_recorder.emit_stage(
                stage="delete_storage",
                stage_status="completed",
                outputs={"deleted_object_count": deleted_object_count},
            )

            try:
                await deps.graph_service.clear_document_graph_facts(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    delete_document_node=True,
                )
            except Exception as exc:
                deps.log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="delete_graph",
                    stage_status="failed",
                    error=str(exc),
                )

            current_stage = "delete_metadata"
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_metadata",
                stage_status="started",
            )
            await pipeline_recorder.emit_stage(stage="delete_metadata", stage_status="started")
            try:
                deleted_chunks = await deps.document_repository.delete_document_chunks(
                    session,
                    document_id=parsed_document_id,
                    index_version=None,
                )
                deleted_pages = await deps.document_repository.delete_document_pages(
                    session,
                    document_id=parsed_document_id,
                )
                # Stage rows and artifacts (R06-01) hold copies of document text.
                await delete_stage_state(
                    session,
                    organization_id=document.organization_id,
                    document_id=parsed_document_id,
                )
                updated = await deps.document_repository.update_document_status(
                    session,
                    document_id=parsed_document_id,
                    status=DocumentStatus.deleted.value,
                    error_message=None,
                )
                if updated is None:
                    raise DocumentPipelineTransientError(
                        stage="delete_metadata",
                        code="STATUS_DELETED_UPDATE_FAILED",
                        category="infrastructure",
                        message=f"Unable to move document to deleted state: {document_id}",
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_metadata",
                stage_status="completed",
                deleted_chunk_count=deleted_chunks,
                deleted_page_count=deleted_pages,
            )
            await pipeline_recorder.emit_stage(
                stage="delete_metadata",
                stage_status="completed",
                outputs={
                    "deleted_chunk_count": deleted_chunks,
                    "deleted_page_count": deleted_pages,
                },
            )
            await pipeline_recorder.finalize_run(
                status="completed",
                outputs={
                    "document_status": DocumentStatus.deleted.value,
                    "deleted_chunk_count": deleted_chunks,
                    "deleted_page_count": deleted_pages,
                },
            )
            return deleted_chunks, deleted_pages
        except Exception as exc:
            details = details_from_exception(exc)
            failing_stage = details.get("stage", "unknown")
            if failing_stage == "unknown":
                failing_stage = current_stage
            await pipeline_recorder.fail_stage_if_open(
                stage=failing_stage,
                error_message=details.get("message", str(exc)),
                error_details=details,
            )
            await pipeline_recorder.finalize_run(
                status="failed",
                error_message=details.get("message", str(exc)),
                error_details=details,
                outputs={
                    "deleted_chunk_count": deleted_chunks,
                    "deleted_page_count": deleted_pages,
                },
            )
            raise


def run_delete_task(
    document_id: str,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
) -> dict[str, str]:
    """Body of ``documents.delete``."""
    deps = current_deps()
    try:
        status = deps.get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        # Idempotent for hard-delete policies where row may already be removed.
        deps.log_document_event(
            event="document.deletion.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code="not_found",
        )
        return {"document_id": document_id, "status": "skipped"}

    if status == DocumentStatus.deleted.value:
        deps.log_document_event(
            event="document.deletion.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"document_id": document_id, "status": "skipped"}

    if status not in {DocumentStatus.deleting.value, DocumentStatus.delete_requested.value}:
        deleting_updated = deps.set_document_status(document_id, status=DocumentStatus.deleting)
        if not deleting_updated:
            raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")
    elif status == DocumentStatus.delete_requested.value:
        # Transition from delete_requested → deleting as the task begins.
        deleting_updated = deps.set_document_status(document_id, status=DocumentStatus.deleting)
        if not deleting_updated:
            raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")

    deleted_chunks, deleted_pages = deps.run(
        deps.delete_document_assets_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="document.delete",
        )
    )
    deps.log_document_event(
        event="document.deletion.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.deleted.value,
        deleted_chunk_count=deleted_chunks,
        deleted_page_count=deleted_pages,
    )
    deps.record_worker_audit(
        action="document.delete.completed",
        resource_type="document",
        resource_id=document_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={
            "status": DocumentStatus.deleted.value,
            "deleted_chunk_count": deleted_chunks,
            "deleted_page_count": deleted_pages,
        },
    )
    return {"document_id": document_id, "status": DocumentStatus.deleted.value}
