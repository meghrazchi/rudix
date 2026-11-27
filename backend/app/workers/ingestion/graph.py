"""Inline graph extraction and graph status helpers (moved from document_tasks, R06-01).

Behaviour is unchanged. Collaborators (graph service, extraction services, session
factory, the status helper itself) are read from the facade through ``current_deps()``
at call time, so rebinding them on ``app.workers.document_tasks`` still takes effect.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.config import settings
from app.models.enums import GraphExtractionStatus
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import DocumentPipelineTransientError
from app.workers.ingestion.graph_rows import (
    collect_entity_writes,
    relation_rows,
    write_entity_rows,
)
from app.workers.ingestion.recorder import PipelineRunRecorder


async def _update_document_graph_status_async(
    document_id: UUID,
    *,
    status: str,
    run_id: UUID | None = None,
) -> None:
    deps = current_deps()
    if deps.SessionLocal.kw.get("bind") is not None:
        bind = deps.SessionLocal.kw["bind"]
        dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
        if dialect_name == "sqlite":
            return
    # Use a short lock_timeout so this never blocks indefinitely when the outer
    # pipeline session holds the documents row lock (e.g. during graph extraction).
    # If the lock can't be acquired, skip the status update rather than deadlocking.
    try:
        async with deps.SessionLocal() as session:
            await session.execute(text("SET LOCAL lock_timeout = '3s'"))
            await deps.document_repository.update_document_graph_status(
                session,
                document_id=document_id,
                graph_extraction_status=status,
                graph_extraction_run_id=run_id,
            )
            await session.commit()
    except Exception:
        deps.log_document_event(
            event="document.graph_status.lock_skipped",
            document_id=str(document_id),
            status_code=status,
        )


async def _run_document_graph_extraction_async(
    document: Any,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    pipeline_type: str,
    chunk_pairs: list[tuple[int, str]],
    chunk_id_by_index: dict[int, UUID | None],
    page_by_index: dict[int, int | None],
    pipeline_recorder: PipelineRunRecorder | None = None,
    clear_existing_facts: bool = False,
) -> dict[str, int]:
    deps = current_deps()
    graph_run_id = uuid4()
    previous_graph_run_id = getattr(document, "graph_extraction_run_id", None)
    resolved_organization_id = organization_id or str(document.organization_id)
    resolved_user_id = user_id or str(document.uploaded_by_user_id)

    if not settings.enterprise_graph_enabled or not settings.feature_enable_entity_extraction:
        await deps.update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.skipped.value,
            run_id=None,
        )
        return {"entity_count": 0, "relation_count": 0}

    await deps.update_document_graph_status_async(
        document.id,
        status=GraphExtractionStatus.extracting.value,
        run_id=graph_run_id,
    )
    if clear_existing_facts:
        cleanup_kwargs: dict[str, UUID | str] = {
            "organization_id": document.organization_id,
            "document_id": document.id,
        }
        if previous_graph_run_id is not None:
            cleanup_kwargs["extraction_run_id"] = previous_graph_run_id
        await deps.graph_service.clear_document_graph_facts(
            **cleanup_kwargs,
        )

    entity_count = 0
    relation_count = 0
    _entity_result = None
    _rel_result = None
    _chunk_pairs = [(index, text) for index, text in chunk_pairs if text.strip()]
    _page_by_index = page_by_index

    _extraction_run_id = uuid4()
    if pipeline_recorder is not None:
        await pipeline_recorder.emit_stage(
            stage="extract_entities",
            stage_status="started",
            config={
                "batch_size": settings.entity_extraction_batch_size,
                "strict_mode": settings.entity_extraction_strict_mode,
                "run_id": str(_extraction_run_id),
            },
        )
    try:
        await deps.graph_service.start_extraction_run(
            organization_id=document.organization_id,
            document_id=document.id,
            run_id=_extraction_run_id,
            strategy="llm_extraction_v1",
        )
        _entity_result = await deps.entity_extraction_service.extract_from_chunks(
            chunks=_chunk_pairs,
            document_language=document.language,
            organization_id=str(document.organization_id),
        )
        # R06-10: resolution reads per entity, then one write transaction per batch.
        _entity_writes = await collect_entity_writes(
            deps,
            document,
            _entity_result.entities,
            chunk_id_by_index=chunk_id_by_index,
            page_by_index=_page_by_index,
            extraction_run_id=_extraction_run_id,
        )
        await write_entity_rows(deps, document.organization_id, _entity_writes)
        entity_count = len(_entity_result.entities)
        await deps.graph_service.finish_extraction_run(
            organization_id=document.organization_id,
            run_id=_extraction_run_id,
            status="completed",
            entity_count=entity_count,
        )
        if pipeline_recorder is not None:
            await pipeline_recorder.emit_stage(
                stage="extract_entities",
                stage_status="completed",
                outputs={
                    "entity_count": entity_count,
                    "batch_count": _entity_result.batch_count,
                    "validation_errors": _entity_result.validation_errors,
                    "llm_errors": _entity_result.llm_errors,
                    "total_chunks": _entity_result.total_chunks,
                },
            )
        deps.log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=resolved_organization_id,
            user_id=resolved_user_id,
            stage="extract_entities",
            stage_status="completed",
            entity_count=entity_count,
            batch_count=_entity_result.batch_count,
            validation_errors=_entity_result.validation_errors,
            llm_errors=_entity_result.llm_errors,
        )
    except Exception as _entity_exc:
        deps.log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=resolved_organization_id,
            user_id=resolved_user_id,
            stage="extract_entities",
            stage_status="failed",
            error=str(_entity_exc),
        )
        try:
            await deps.graph_service.finish_extraction_run(
                organization_id=document.organization_id,
                run_id=_extraction_run_id,
                status="failed",
                error=str(_entity_exc),
            )
        except Exception:
            pass
        if settings.entity_extraction_strict_mode:
            await deps.update_document_graph_status_async(
                document.id,
                status=GraphExtractionStatus.failed.value,
                run_id=graph_run_id,
            )
            raise DocumentPipelineTransientError(
                stage="extract_entities",
                code="ENTITY_EXTRACTION_FAILED",
                category="processing",
                message=f"Entity extraction failed: {_entity_exc}",
            ) from _entity_exc
        if pipeline_recorder is not None:
            await pipeline_recorder.emit_stage(
                stage="extract_entities",
                stage_status="failed",
                error_message=str(_entity_exc),
            )

    if (
        settings.feature_enable_relation_extraction
        and _entity_result is not None
        and _entity_result.entities
    ):
        _rel_run_id = uuid4()
        if pipeline_recorder is not None:
            await pipeline_recorder.emit_stage(
                stage="extract_relations",
                stage_status="started",
                config={
                    "batch_size": settings.relation_extraction_batch_size,
                    "strict_mode": settings.relation_extraction_strict_mode,
                    "confidence_threshold": settings.relation_confidence_threshold,
                    "review_mode": settings.relation_extraction_review_mode,
                    "run_id": str(_rel_run_id),
                },
            )
        try:
            _entity_name_to_id = {
                _item.name.lower().strip(): _item.entity_id for _item in _entity_result.entities
            }
            _entity_names_by_chunk: dict[int, list[str]] = {}
            for _item in _entity_result.entities:
                _entity_names_by_chunk.setdefault(_item.source_chunk_index, []).append(_item.name)

            _rel_result = await deps.relation_extraction_service.extract_from_chunks(
                chunks=_chunk_pairs,
                entity_name_to_id=_entity_name_to_id,
                entity_names_by_chunk=_entity_names_by_chunk,
                organization_id=str(document.organization_id),
            )
            await deps.graph_service.create_relations_with_evidence_batch(
                organization_id=document.organization_id,
                rows=relation_rows(
                    deps,
                    document,
                    _rel_result.relations,
                    chunk_id_by_index=chunk_id_by_index,
                    page_by_index=_page_by_index,
                    extraction_run_id=_rel_run_id,
                ),
            )
            relation_count = len(_rel_result.relations)
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="extract_relations",
                stage_status="completed",
                relation_count=relation_count,
                batch_count=_rel_result.batch_count,
                validation_errors=_rel_result.validation_errors,
                llm_errors=_rel_result.llm_errors,
                skipped_unknown_entity=_rel_result.skipped_unknown_entity,
            )
            if pipeline_recorder is not None:
                await pipeline_recorder.emit_stage(
                    stage="extract_relations",
                    stage_status="completed",
                    outputs={
                        "relation_count": relation_count,
                        "batch_count": _rel_result.batch_count,
                        "validation_errors": _rel_result.validation_errors,
                        "llm_errors": _rel_result.llm_errors,
                        "skipped_unknown_entity": _rel_result.skipped_unknown_entity,
                    },
                )
        except Exception as _rel_exc:
            deps.log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="extract_relations",
                stage_status="failed",
                error=str(_rel_exc),
            )
            if settings.relation_extraction_strict_mode:
                await deps.update_document_graph_status_async(
                    document.id,
                    status=GraphExtractionStatus.failed.value,
                    run_id=graph_run_id,
                )
                raise DocumentPipelineTransientError(
                    stage="extract_relations",
                    code="RELATION_EXTRACTION_FAILED",
                    category="processing",
                    message=f"Relation extraction failed: {_rel_exc}",
                ) from _rel_exc
            if pipeline_recorder is not None:
                await pipeline_recorder.emit_stage(
                    stage="extract_relations",
                    stage_status="failed",
                    error_message=str(_rel_exc),
                )

    await deps.update_document_graph_status_async(
        document.id,
        status=GraphExtractionStatus.completed.value,
        run_id=graph_run_id,
    )
    return {"entity_count": entity_count, "relation_count": relation_count}
