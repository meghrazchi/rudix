"""index stage: stale vector cleanup and connector source references (R06-01, R06-06).

The vectors are written by the embed stage batch by batch; this stage records the
``connector_chunk`` source references of connector-backed documents in one short session.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.documents import (
    embeddable_chunks_query,
    index_version,
    load_document,
)
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.stages.base import StageName, StageOutcome


async def _upsert_connector_chunk_references(
    session: Any,
    *,
    document: Any,
    chunks: list[Any],
) -> None:
    if document.connector_external_item_id is None or not chunks:
        return
    deps = current_deps()
    source_document = await deps.connector_repository.get_source_document_for_document(
        session,
        organization_id=document.organization_id,
        document_id=document.id,
    )
    if source_document is None:
        return

    result = await session.execute(
        select(
            ExternalItem.id,
            ExternalItem.provider_item_id,
            ExternalItem.title,
            ExternalItem.source_url,
            ExternalItem.item_type,
            ExternalItem.permissions_json,
            ExternalItem.content_hash,
            ExternalItem.sync_version,
            ExternalItem.deleted_at,
            ConnectorConnection.status,
            ConnectorProvider.key,
            ConnectorProvider.display_name,
        )
        .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
        .join(ConnectorProvider, ConnectorProvider.id == ConnectorConnection.provider_id)
        .where(
            ExternalItem.id == document.connector_external_item_id,
            ExternalItem.organization_id == document.organization_id,
        )
    )
    row = result.first()
    if row is None:
        return

    (
        _external_item_id,
        provider_item_id,
        source_title,
        source_url,
        item_type,
        permissions_json,
        content_hash,
        sync_version,
        deleted_at,
        connection_status,
        provider_key,
        provider_label,
    ) = row

    source_ref_status = "deleted"
    if deleted_at is None and connection_status == "active":
        source_ref_status = "trusted"

    provider_meta = {
        "provider_key": provider_key,
        "provider_label": provider_label,
        "source_title": source_title,
        "source_key": provider_item_id,
        "source_url": source_url,
        "source_section": None,
        "content_hash": source_document.content_hash,
        "source_item_content_hash": content_hash,
        "sync_version": source_document.sync_version,
        "source_item_sync_version": sync_version,
        "last_synced_at": source_document.updated_at.isoformat()
        if source_document.updated_at
        else None,
        "trust_status": source_ref_status,
        "acl_snapshot": permissions_json or {},
    }

    for chunk in chunks:
        locator = deps.source_provenance_service.build_locator_snapshot(
            provider_key=provider_meta["provider_key"] or "connector",
            item_type=str(item_type),
            provider_item_id=provider_item_id,
            source_url=source_url,
            section_label=(
                chunk.section_path
                or (f"Page {chunk.page_number}" if chunk.page_number is not None else None)
            ),
            page_number=chunk.page_number,
        )
        metadata = {
            **provider_meta,
            "source_section": locator.get("source_section"),
        }
        await deps.connector_repository.upsert_source_reference(
            session,
            organization_id=document.organization_id,
            source_document_id=source_document.id,
            external_item_id=document.connector_external_item_id,
            document_id=document.id,
            reference_type="connector_chunk",
            source_url=source_url,
            chunk_id=chunk.id,
            title=source_title,
            locator=locator,
            metadata=metadata,
        )


async def _vector_cleanup(ctx: StageContext, document: Any) -> int:
    """Delete the document's points of other runs, then verify the point count (R06-06).

    Pipeline-explorer stage ``index_cleanup``. One delete (organisation, document, index
    version, ``ingest_run_id`` not this run) removes stale points such as the higher chunk
    indexes of a longer previous version; one exact count must then equal the embeddable
    chunk rows, otherwise the stage fails as transient ``QDRANT_POINT_COUNT_MISMATCH``.
    """
    ctx.current_stage = "index_cleanup"
    version = index_version(ctx)
    expected = int(ctx.metrics[StageName.chunk]["embeddable_count"])
    ctx.log_stage("index_cleanup", "started", index_version=version)
    await ctx.recorder.emit_stage(
        stage="index_cleanup", stage_status="started", config={"index_version": version}
    )
    kwargs: dict[str, Any] = {
        "organization_id": document.organization_id,
        "document_id": document.id,
        "index_version": version,
    }
    if ctx.options.vector_collection is not None:
        kwargs["collection_name"] = ctx.options.vector_collection
    qdrant = ctx.deps.qdrant_service
    try:
        await qdrant.delete_stale_document_points(**kwargs, ingest_run_id=ctx.run_id)
        count = int(await qdrant.count_document_points(**kwargs))
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="index_cleanup",
            code="QDRANT_CLEANUP_FILTER_INVALID",
            category="validation",
            message=str(exc),
        ) from exc
    except Exception as exc:
        raise DocumentPipelineTransientError(
            stage="index_cleanup",
            code="QDRANT_CLEANUP_FAILED",
            category="infrastructure",
            message="qdrant cleanup failed",
        ) from exc
    if count != expected:
        raise DocumentPipelineTransientError(
            stage="index_cleanup",
            code="QDRANT_POINT_COUNT_MISMATCH",
            category="infrastructure",
            message=f"vector index holds {count} points for the document, expected {expected}",
        )
    ctx.log_stage("index_cleanup", "completed", index_version=version, point_count=count)
    await ctx.recorder.emit_stage(
        stage="index_cleanup",
        stage_status="completed",
        outputs={"index_version": version, "point_count": count},
    )
    return count


async def run(ctx: StageContext) -> StageOutcome:
    document = await load_document(ctx)
    point_count = await _vector_cleanup(ctx, document)
    if document.connector_external_item_id is None:
        return StageOutcome(metrics={"source_references": 0, "point_count": point_count})
    async with ctx.deps.SessionLocal() as session, session.begin():
        chunks = list((await session.execute(embeddable_chunks_query(ctx))).scalars())
        await _upsert_connector_chunk_references(session, document=document, chunks=chunks)
    return StageOutcome(metrics={"source_references": len(chunks), "point_count": point_count})
