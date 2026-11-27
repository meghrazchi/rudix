"""Chunking-target corpus: eval re-ingest, corpus statistics, eval index cleanup."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.workers import document_tasks
from app.workers.evaluation import facade
from app.workers.evaluation.collection import (
    ensure_evaluation_collection,
    evaluation_collection,
)
from app.workers.evaluation.config import ChunkingComparisonTarget
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pipeline import extract_and_store


@dataclass(frozen=True)
class ChunkingCorpusStats:
    chunk_count_total: int
    chunk_tokens_average: float | None
    chunk_tokens_variance: float | None
    chunk_tokens_min: int | None
    chunk_tokens_max: int | None
    document_type_breakdown: dict[str, int]
    language_breakdown: dict[str, int]
    ocr_breakdown: dict[str, int]


def _build_target_index_version(*, evaluation_run_id: UUID, target_index: int) -> str:
    return f"eval-{evaluation_run_id.hex[:10]}-{target_index + 1}"


async def _cleanup_target_index_async(
    *,
    organization_id: UUID,
    document_ids: list[UUID],
    index_version: str,
    evaluation_run_id: str,
    request_id: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Deletes a target's eval chunks and vectors. Never raises: cleanup must not fail a run."""
    try:
        result = await facade().cleanup_eval_index_version_async(
            organization_id=organization_id,
            document_ids=document_ids,
            index_version=index_version,
        )
    except Exception as exc:
        entry: dict[str, Any] = {
            "index_version": index_version,
            "error": exc.__class__.__name__,
        }
    else:
        entry = result.as_dict()
    log_evaluation_event(
        event="evaluation.index_cleanup.completed",
        organization_id=str(organization_id),
        user_id=user_id,
        job_id=evaluation_run_id,
        request_id=request_id,
        index_version=index_version,
        documents_attempted=entry.get("documents_attempted"),
        chunks_deleted=entry.get("chunks_deleted"),
        qdrant_failures=entry.get("qdrant_failures"),
        chunk_failures=entry.get("chunk_failures"),
        error=entry.get("error"),
    )
    return entry


def _ocr_bucket(snapshot: object) -> str:
    values = snapshot if isinstance(snapshot, dict) else {}
    if values.get("ocr_applied") is True:
        return "ocr_applied"
    if values.get("ocr_applied") is False:
        return "native_text"
    return "unknown"


async def _collect_chunking_corpus_stats_async(
    *,
    session: AsyncSession,
    document_ids: list[UUID],
    index_version: str,
) -> ChunkingCorpusStats:
    token_counts: list[int] = []
    document_type_counter: Counter[str] = Counter()
    language_counter: Counter[str] = Counter()
    ocr_counter: Counter[str] = Counter()
    repository = facade()._document_repository

    for document_id in document_ids:
        document = await repository.get_document_by_id(session, document_id=document_id)
        if document is not None:
            document_type_counter[document.file_type or "unknown"] += 1
            language_counter[document.language or "unknown"] += 1
            ocr_counter[_ocr_bucket(document.chunking_config_snapshot)] += 1

        chunks = await repository.list_document_chunks(
            session,
            document_id=document_id,
            index_version=index_version,
        )
        token_counts.extend(chunk.token_count for chunk in chunks)

    if not token_counts:
        return ChunkingCorpusStats(
            chunk_count_total=0,
            chunk_tokens_average=None,
            chunk_tokens_variance=None,
            chunk_tokens_min=None,
            chunk_tokens_max=None,
            document_type_breakdown=dict(document_type_counter),
            language_breakdown=dict(language_counter),
            ocr_breakdown=dict(ocr_counter),
        )

    average = sum(token_counts) / len(token_counts)
    variance = sum((count - average) ** 2 for count in token_counts) / len(token_counts)
    return ChunkingCorpusStats(
        chunk_count_total=len(token_counts),
        chunk_tokens_average=round(average, 2),
        chunk_tokens_variance=round(variance, 2),
        chunk_tokens_min=min(token_counts),
        chunk_tokens_max=max(token_counts),
        document_type_breakdown=dict(document_type_counter),
        language_breakdown=dict(language_counter),
        ocr_breakdown=dict(ocr_counter),
    )


async def _reingest_document_async(
    document_id: UUID,
    *,
    chunking_service: Any,
    profile_source: str,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    vector_collection: str | None,
) -> None:
    """Re-ingest one document under the eval index version; nothing on the document changes.

    Without an evaluation collection this is the facade call used since R02-05. With one,
    the same stages run with ``IngestionOptions.vector_collection`` (the S1 seam), so the
    vectors are written to the evaluation collection only.
    """
    if vector_collection is None:
        await document_tasks._extract_and_store_document_pages_async(
            str(document_id),
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="evaluation.run",
            chunking_service=chunking_service,
            profile_source=profile_source,
            persist_document_state=False,
            persist_document_pages=False,
            record_usage_event=False,
        )
        return
    await extract_and_store(
        str(document_id),
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        options=IngestionOptions(
            pipeline_type="evaluation.run",
            chunking_service=chunking_service,
            profile_source=profile_source,
            persist_document_state=False,
            persist_document_pages=False,
            record_usage_event=False,
            vector_collection=vector_collection,
        ),
    )


async def _prepare_chunking_target_corpus_async(
    *,
    evaluation_run_id: UUID,
    target_index: int,
    target: ChunkingComparisonTarget,
    document_ids: list[UUID],
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
) -> tuple[str, ChunkingCorpusStats]:
    session_factory = facade().SessionLocal
    if target.chunking_profile_config is None:
        # Baseline targets read the production collection and index version.
        async with session_factory() as session:
            stats = await _collect_chunking_corpus_stats_async(
                session=session,
                document_ids=document_ids,
                index_version=settings.document_index_version,
            )
        return settings.document_index_version, stats

    index_version = _build_target_index_version(
        evaluation_run_id=evaluation_run_id,
        target_index=target_index,
    )
    vector_collection = evaluation_collection()
    if vector_collection is not None:
        await ensure_evaluation_collection(vector_collection)
    chunking_service = document_tasks._make_chunking_service(
        target.chunking_profile_config,
        index_version=index_version,
    )
    for document_id in document_ids:
        await _reingest_document_async(
            document_id,
            chunking_service=chunking_service,
            profile_source=target.profile_source,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            vector_collection=vector_collection,
        )

    async with session_factory() as session:
        stats = await _collect_chunking_corpus_stats_async(
            session=session,
            document_ids=document_ids,
            index_version=index_version,
        )
    return index_version, stats
