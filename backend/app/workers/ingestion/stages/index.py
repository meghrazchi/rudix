"""index stage: connector source references for the indexed chunks (R06-01).

The vectors are written by the embed stage batch by batch; this stage records the
``connector_chunk`` source references of connector-backed documents in one short session.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.documents import embeddable_chunks_query, load_document
from app.workers.ingestion.stages.base import StageOutcome


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


async def run(ctx: StageContext) -> StageOutcome:
    document = await load_document(ctx)
    if document.connector_external_item_id is None:
        return StageOutcome(metrics={"source_references": 0})
    async with ctx.deps.SessionLocal() as session, session.begin():
        chunks = list((await session.execute(embeddable_chunks_query(ctx))).scalars())
        await _upsert_connector_chunk_references(session, document=document, chunks=chunks)
    return StageOutcome(metrics={"source_references": len(chunks)})
