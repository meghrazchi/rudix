from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.logging import log_document_event
from app.db.session import SessionLocal
from app.models.enums import DocumentStatus
from app.repositories.documents import DocumentRepository
from app.repositories.usage import UsageRepository
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingResult, EmbeddingService
from app.services.text_extraction import extract_text_sections
from app.services.text_normalization import TextCleaningStats, clean_extracted_sections
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_document_status, set_document_status

_document_repository = DocumentRepository()
_usage_repository = UsageRepository()
_chunking_service = ChunkingService()
_embedding_service = EmbeddingService()
_worker_loop: asyncio.AbstractEventLoop | None = None


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


def _read_object_bytes(*, bucket: str, object_key: str) -> bytes:
    minio = minio_module.minio_client
    if minio is None:
        raise TransientTaskError("Object storage is unavailable")

    try:
        response = minio.get_object(Bucket=bucket, Key=object_key)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            raise PermanentTaskError("Stored file was not found in object storage") from exc
        raise TransientTaskError("Object storage read failed") from exc
    except Exception as exc:
        raise TransientTaskError("Object storage read failed") from exc

    body = response.get("Body")
    if body is None:
        raise TransientTaskError("Object storage response body is missing")
    try:
        data = body.read()
    except Exception as exc:
        raise TransientTaskError("Object storage read failed") from exc
    finally:
        close_method = getattr(body, "close", None)
        if callable(close_method):
            close_method()
    if not isinstance(data, bytes):
        raise TransientTaskError("Object storage returned invalid payload")
    return data


async def _extract_and_store_document_pages_async(
    document_id: str,
) -> tuple[int, int, TextCleaningStats, EmbeddingResult]:
    try:
        parsed_document_id = _parse_uuid(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc

    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(session, document_id=parsed_document_id)
        if document is None:
            raise PermanentTaskError(f"Document not found: {document_id}")

        content = _read_object_bytes(bucket=document.storage_bucket, object_key=document.storage_object_key)
        try:
            sections = extract_text_sections(file_type=document.file_type, content=content)
        except ValueError as exc:
            raise PermanentTaskError(str(exc)) from exc
        cleaned_sections, cleaning_stats = clean_extracted_sections(sections)
        if not any(section.text for section in cleaned_sections):
            raise PermanentTaskError("extracted document contains no text after cleaning")

        try:
            await _document_repository.delete_document_pages(session, document_id=parsed_document_id)
            for section in cleaned_sections:
                await _document_repository.create_document_page(
                    session,
                    document_id=parsed_document_id,
                    page_number=section.page_number,
                    text=section.text,
                    char_count=section.char_count,
                )
            chunks = await _chunking_service.chunk(document_id=parsed_document_id, pages=cleaned_sections)
            if not chunks:
                raise PermanentTaskError("cleaned document produced no chunks")
            await _document_repository.delete_document_chunks(
                session,
                document_id=parsed_document_id,
                index_version=settings.document_index_version,
            )
            created_chunks = []
            for chunk in chunks:
                created_chunks.append(
                    await _document_repository.create_document_chunk(
                        session,
                        document_id=chunk.document_id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        embedding_model=chunk.embedding_model,
                        index_version=chunk.index_version,
                    )
                )

            embedding_result = await _embedding_service.embed_chunks(chunks=created_chunks)
            if len(embedding_result.vectors_by_chunk_id) != len(created_chunks):
                raise PermanentTaskError("embedding generation did not cover all chunks")
            for chunk_id, vector in embedding_result.vectors_by_chunk_id.items():
                if len(vector) != settings.qdrant_vector_size:
                    raise PermanentTaskError(
                        f"embedding dimension mismatch for chunk {chunk_id}: "
                        f"expected {settings.qdrant_vector_size}, got {len(vector)}"
                    )

            await _usage_repository.create_usage_event(
                session,
                organization_id=document.organization_id,
                user_id=document.uploaded_by_user_id,
                event_type="document.embedding",
                model_name=embedding_result.model_name,
                input_tokens=embedding_result.input_tokens,
                output_tokens=None,
                cost_usd=embedding_result.approximate_cost_usd,
                metadata={
                    "document_id": str(document.id),
                    "chunk_count": len(created_chunks),
                    "batch_count": embedding_result.batch_count,
                    "retry_count": embedding_result.retry_count,
                    "index_version": embedding_result.index_version,
                    "latency_ms": embedding_result.latency_ms,
                    "total_tokens": embedding_result.total_tokens,
                },
            )
            updated = await _document_repository.update_document_status(
                session,
                document_id=parsed_document_id,
                status=DocumentStatus.indexed.value,
                error_message=None,
                page_count=len(cleaned_sections),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        if updated is None:
            raise TransientTaskError(f"Unable to move document to indexed state: {document_id}")
        return len(cleaned_sections), len(chunks), cleaning_stats, embedding_result


class DocumentTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        document_id = kwargs.get("document_id")
        if document_id is None and args:
            document_id = args[0]
        if not isinstance(document_id, str):
            return
        try:
            set_document_status(
                document_id,
                status=DocumentStatus.failed,
                error_message=str(exc),
            )
            log_document_event(
                event="document.processing.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.failed.value,
                error=str(exc),
            )
        except Exception:
            return


@celery_app.task(name="documents.process", bind=True, base=DocumentTask)
def process_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, str | int | float]:
    """Extract text and persist document_pages before marking a document as indexed."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")

    if not force and status in {
        DocumentStatus.processing.value,
        DocumentStatus.indexed.value,
        DocumentStatus.deleted.value,
    }:
        log_document_event(
            event="document.processing.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"document_id": document_id, "status": "skipped"}

    try:
        processing_updated = set_document_status(document_id, status=DocumentStatus.processing)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if not processing_updated:
        raise TransientTaskError(f"Unable to move document to processing state: {document_id}")

    log_document_event(
        event="document.processing.started",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.processing.value,
    )

    page_count, chunk_count, cleaning_stats, embedding_result = _run(
        _extract_and_store_document_pages_async(document_id)
    )

    log_document_event(
        event="document.processing.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.indexed.value,
        page_count=page_count,
        chunk_count=chunk_count,
        index_version=settings.document_index_version,
        embedding_batch_count=embedding_result.batch_count,
        embedding_retry_count=embedding_result.retry_count,
        embedding_input_tokens=embedding_result.input_tokens,
        embedding_total_tokens=embedding_result.total_tokens,
        embedding_latency_ms=embedding_result.latency_ms,
        embedding_cost_usd=float(embedding_result.approximate_cost_usd),
        **cleaning_stats.as_log_fields(),
    )
    return {
        "document_id": document_id,
        "status": DocumentStatus.indexed.value,
        "page_count": page_count,
        "chunk_count": chunk_count,
        "index_version": settings.document_index_version,
        "embedding_batch_count": embedding_result.batch_count,
        "embedding_retry_count": embedding_result.retry_count,
        "embedding_input_tokens": embedding_result.input_tokens,
        "embedding_total_tokens": embedding_result.total_tokens,
        "embedding_latency_ms": embedding_result.latency_ms,
        "embedding_cost_usd": float(embedding_result.approximate_cost_usd),
        "cleaning_pages_modified": cleaning_stats.pages_modified,
    }


@celery_app.task(name="documents.delete", bind=True, base=DocumentTask)
def delete_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str]:
    """Scaffold task for idempotent document deletion orchestration."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")

    if status == DocumentStatus.deleted.value:
        log_document_event(
            event="document.deletion.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"document_id": document_id, "status": "skipped"}

    deleting_updated = set_document_status(document_id, status=DocumentStatus.deleting)
    if not deleting_updated:
        raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")
    deleted_updated = set_document_status(document_id, status=DocumentStatus.deleted)
    if not deleted_updated:
        raise TransientTaskError(f"Unable to move document to deleted state: {document_id}")

    log_document_event(
        event="document.deletion.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.deleted.value,
    )
    return {"document_id": document_id, "status": DocumentStatus.deleted.value}


@celery_app.task(name="documents.reindex", bind=True, base=DocumentTask)
def reindex_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str]:
    """Scaffold task for idempotent document re-index orchestration."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")
    if status == DocumentStatus.deleted.value:
        raise PermanentTaskError(f"Cannot reindex deleted document: {document_id}")

    processing_updated = set_document_status(document_id, status=DocumentStatus.processing)
    if not processing_updated:
        raise TransientTaskError(f"Unable to move document to processing state: {document_id}")
    indexed_updated = set_document_status(document_id, status=DocumentStatus.indexed)
    if not indexed_updated:
        raise TransientTaskError(f"Unable to move document to indexed state: {document_id}")

    log_document_event(
        event="document.reindex.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.indexed.value,
    )
    return {"document_id": document_id, "status": DocumentStatus.indexed.value}
