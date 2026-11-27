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
from app.domains.graph.services.entity_resolution_service import EntityResolutionInput
from app.models.enums import GraphExtractionStatus
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import DocumentPipelineTransientError
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
        for _item in _entity_result.entities:
            _chunk_db_id = chunk_id_by_index.get(_item.source_chunk_index)
            _resolved_entity_id = _item.entity_id
            _resolution_status = "new"
            _resolution_confidence = _item.confidence
            _entity_aliases = list(
                dict.fromkeys(
                    [
                        _item.original_name,
                        _item.name,
                        *_item.aliases,
                    ]
                )
            )
            if settings.feature_enable_entity_resolution:
                _resolution_result = await deps.graph_service.resolve_entity(
                    organization_id=document.organization_id,
                    entity_type=_item.type,
                    canonical_name=_item.name,
                    original_name=_item.original_name,
                    aliases=_item.aliases,
                    language=_item.language,
                )
                _resolved_entity_id = _resolution_result.canonical_entity_id
                _resolution_status = _resolution_result.status
                _resolution_confidence = _resolution_result.candidate_score
                _canonical_name = _resolution_result.canonical_name
            else:
                _canonical_name = _item.name
            resolution_input = EntityResolutionInput(
                organization_id=str(document.organization_id),
                entity_type=_item.type,
                canonical_name=_canonical_name,
                original_name=_item.original_name,
                aliases=list(_item.aliases),
                source_external_id=None,
                source_connector=None,
                language=_item.language,
            )
            alias_name = _item.original_name or _item.name
            alias_id = deps.entity_resolution_service.build_alias_id(
                input_=resolution_input,
                entity_id=_resolved_entity_id,
                alias_name=alias_name,
                source_document_id=str(document.id),
                chunk_id=str(_chunk_db_id) if _chunk_db_id is not None else None,
            )
            await deps.graph_service.upsert_entity(
                organization_id=document.organization_id,
                entity_id=_resolved_entity_id,
                entity_type=_item.type,
                canonical_name=_canonical_name,
                normalized_name=_canonical_name.lower().strip(),
                resolution_status=_resolution_status,
                resolution_confidence=_resolution_confidence,
                properties={
                    "original_name": _item.original_name,
                    "aliases": _entity_aliases,
                    "language": _item.language,
                },
            )
            await deps.graph_service.upsert_entity_alias(
                organization_id=document.organization_id,
                entity_id=_resolved_entity_id,
                alias_id=alias_id,
                alias_name=alias_name,
                source_document_id=document.id,
                chunk_id=_chunk_db_id,
                confidence=_item.confidence,
                evidence_text=_item.evidence_span,
                properties={
                    "normalized_name": _item.name.lower().strip(),
                    "language": _item.language,
                },
            )
            if _chunk_db_id is not None:
                await deps.graph_service.link_evidence(
                    organization_id=document.organization_id,
                    entity_id=_resolved_entity_id,
                    chunk_id=_chunk_db_id,
                    source_document_id=document.id,
                    confidence=_item.confidence,
                    citation_text=_item.evidence_span,
                    citation_reference=f"{document.filename}, chunk {_item.source_chunk_index}",
                    extraction_run_id=_extraction_run_id,
                    page_number=_page_by_index.get(_item.source_chunk_index),
                )
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
            for _rel_item in _rel_result.relations:
                _rel_chunk_db_id = chunk_id_by_index.get(_rel_item.source_chunk_index)
                _initial_status = (
                    deps.relation_extraction_service.compute_initial_status(_rel_item.confidence)
                    if not settings.relation_extraction_review_mode
                    else "unverified"
                )
                await deps.graph_service.create_relation_with_evidence(
                    organization_id=document.organization_id,
                    from_entity_id=_rel_item.from_entity_id,
                    to_entity_id=_rel_item.to_entity_id,
                    rel_type=_rel_item.rel_type,
                    relation_id=_rel_item.relation_id,
                    citation_text=_rel_item.evidence_span,
                    citation_reference=f"{document.filename}, chunk {_rel_item.source_chunk_index}",
                    chunk_id=_rel_chunk_db_id,
                    source_document_id=document.id,
                    page_number=_page_by_index.get(_rel_item.source_chunk_index),
                    extraction_run_id=_rel_run_id,
                    confidence=_rel_item.confidence,
                    initial_status=_initial_status,
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
