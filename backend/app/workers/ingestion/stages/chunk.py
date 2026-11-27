"""chunk stage: document pages, chunk rows, table chunks (R06-01).

Pipeline-explorer stage ``chunk``. Chunking runs without a
session; pages and chunk rows are written in one short transaction. Metrics keep the
inputs of the chunking snapshot that finalize writes on the document.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.documents.chunking.hashing import compute_chunk_hash
from app.domains.documents.services.fts_config import chunk_search_fields
from app.domains.documents.services.table_chunking_service import build_table_chunk
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import load_document
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    safe_duration_ms,
)
from app.workers.ingestion.pages import read_pages, table_from_dict, to_sections
from app.workers.ingestion.stages.base import StageName, StageOutcome
from app.workers.ingestion.stages.chunk_metrics import chunk_metrics, log_chunk_completed


def _chunk_row_values(
    ctx: StageContext, chunk: Any, *, document: Any, is_hierarchical: bool
) -> dict[str, Any]:
    """Keyword arguments of ``create_document_chunk`` for one chunk payload (B1 edits)."""
    is_embeddable = not is_hierarchical or chunk.chunk_level == 1
    point_id = (
        ctx.deps.qdrant_service.build_point_id(
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            index_version=chunk.index_version,
        )
        if is_embeddable
        else None
    )
    section_path = chunk.section_path
    if section_path is None and chunk.page_number is not None:
        section_path = f"page:{chunk.page_number}"
    return {
        "document_id": chunk.document_id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "qdrant_point_id": point_id,
        "embedding_model": chunk.embedding_model,
        "index_version": chunk.index_version,
        "chunk_hash": compute_chunk_hash(chunk.text),
        "section_path": section_path,
        "language": document.language,
        "chunk_level": chunk.chunk_level if is_hierarchical else None,
        "child_count": chunk.child_count,
        # R06-09: tenant column and the document language's text search configuration;
        # the repository writes fts_vector = to_tsvector(fts_config, text) on PostgreSQL.
        **chunk_search_fields(document),
    }


# anchor: A1 index cleanup begin
# R06-06: per-document point cleanup moved to the index stage, after the upserts, so the
# old points stay searchable (and reusable as embeddings) until the new ones are written.
# anchor: A1 index cleanup end


async def _table_payloads(ctx: StageContext, base_index: int) -> list[dict[str, Any]]:
    """Table chunk rows (F298) from the table blocks the extract stage stored."""
    extract = ctx.metrics.get(StageName.extract, {})
    if not (
        settings.feature_enable_table_aware_retrieval
        and extract.get("advanced_extraction")
        and int(extract.get("total_table_blocks", 0)) > 0
    ):
        return []
    index_version = _index_version(ctx)
    rows: list[dict[str, Any]] = []
    offset = 0
    for page in await read_pages(ctx, StageName.extract):
        for table_data in page.get("tables") or []:
            table = table_from_dict(table_data)
            result = build_table_chunk(table, section_context=page.get("table_context"))
            if not result.text.strip():
                offset += 1
                continue
            chunk_index = base_index + offset
            rows.append(
                {
                    "document_id": ctx.document_id,
                    "page_number": table.page_number,
                    "chunk_index": chunk_index,
                    "text": result.text,
                    "token_count": max(1, len(result.text) // 4),
                    "qdrant_point_id": ctx.deps.qdrant_service.build_point_id(
                        document_id=ctx.document_id,
                        chunk_index=chunk_index,
                        index_version=index_version,
                    ),
                    "embedding_model": settings.openai_embedding_model,
                    "index_version": index_version,
                    "chunk_hash": compute_chunk_hash(result.text),
                    "section_path": f"page:{table.page_number}:table:{table.table_index}",
                    "chunk_type": "table",
                    "table_metadata": result.table_metadata,
                }
            )
            offset += 1
    return rows


def _index_version(ctx: StageContext) -> str:
    svc = ctx.options.chunking_service
    return str(getattr(svc, "index_version", settings.document_index_version))


async def run(ctx: StageContext) -> StageOutcome:
    document = await load_document(ctx)
    svc = ctx.options.chunking_service
    index_version = _index_version(ctx)

    ctx.current_stage = "chunk"
    profile = getattr(svc, "_profile", None)
    strategy = getattr(profile, "strategy", settings.chunking_strategy)
    ctx.log_stage("chunk", "started")
    await ctx.recorder.emit_stage(
        stage="chunk",
        stage_status="started",
        config={
            "strategy": strategy,
            "chunk_size_tokens": getattr(svc, "chunk_size_tokens", settings.chunk_size_tokens),
            "chunk_overlap_tokens": getattr(
                svc, "chunk_overlap_tokens", settings.chunk_overlap_tokens
            ),
            "index_version": index_version,
            "profile_source": ctx.options.profile_source,
        },
    )
    sections = to_sections(await read_pages(ctx, StageName.clean_detect))
    ctx.deps.log_chunking_event(
        event="document.chunking.started",
        document_id=str(document.id),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        strategy=strategy,
        profile_source=ctx.options.profile_source,
        index_version=index_version,
    )
    started_at = datetime.now(UTC)
    chunks = await svc.chunk(
        document_id=ctx.document_id,
        pages=sections,
        document_context={
            "file_type": document.file_type,
            "ocr_applied": bool(ctx.metrics.get(StageName.extract, {}).get("ocr_applied")),
        },
    )
    if not chunks:
        raise DocumentPipelinePermanentError(
            stage="chunk",
            code="EMPTY_CHUNK_SET",
            category="validation",
            message="cleaned document produced no chunks",
        )
    duration_ms = safe_duration_ms(started_at=started_at, ended_at=datetime.now(UTC))
    metrics = chunk_metrics(ctx, svc, chunks, sections, strategy, index_version)
    await log_chunk_completed(ctx, svc, chunks, sections, metrics, duration_ms)

    tables = await _table_payloads(ctx, len(chunks))
    embeddable = await _write_rows(ctx, document, sections, chunks, tables)
    if tables:
        ctx.log_stage("table_chunk", "completed", table_chunk_count=len(tables))
    metrics.update(table_chunk_count=len(tables), embeddable_count=embeddable)
    return StageOutcome(metrics=metrics)


async def _write_rows(
    ctx: StageContext,
    document: Any,
    sections: list[Any],
    chunks: list[Any],
    tables: list[dict[str, Any]],
) -> int:
    """Replace pages and chunk rows in one transaction; returns the embeddable row count."""
    deps = ctx.deps
    repository = deps.document_repository
    is_hierarchical = any(c.chunk_level == 1 for c in chunks)
    async with deps.SessionLocal() as session, session.begin():
        if ctx.options.persist_document_pages:
            await repository.delete_document_pages(session, document_id=ctx.document_id)
            for section in sections:
                await repository.create_document_page(
                    session,
                    document_id=ctx.document_id,
                    page_number=section.page_number,
                    text=section.text,
                    char_count=section.char_count,
                )
        await repository.delete_document_chunks(
            session, document_id=ctx.document_id, index_version=_index_version(ctx)
        )
        created = [
            await repository.create_document_chunk(
                session,
                **_chunk_row_values(ctx, chunk, document=document, is_hierarchical=is_hierarchical),
            )
            for chunk in chunks
        ]
        if is_hierarchical:
            by_index: dict[int, UUID] = {
                p.chunk_index: c.id for p, c in zip(chunks, created, strict=True)
            }
            for payload, row in zip(chunks, created, strict=True):
                if payload.chunk_level == 1 and payload.parent_chunk_index is not None:
                    parent_id = by_index.get(payload.parent_chunk_index)
                    if parent_id is not None:
                        row.parent_chunk_id = parent_id
            await session.flush()
        for values in tables:
            await repository.create_document_chunk(
                session, language=document.language, **chunk_search_fields(document), **values
            )
    embeddable = sum(1 for c in chunks if not is_hierarchical or c.chunk_level == 1)
    return embeddable + len(tables)
