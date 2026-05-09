from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.document_errors import (
    build_document_error_details,
    details_from_exception,
    encode_document_error,
)
from app.core.logging import log_document_event
from app.db.session import SessionLocal
from app.models.enums import DocumentStatus
from app.repositories.documents import DocumentRepository
from app.repositories.usage import UsageRepository
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import (
    EmbeddingResult,
    EmbeddingService,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.services.qdrant_service import QdrantService
from app.services.text_extraction import extract_text_sections
from app.services.text_normalization import TextCleaningStats, clean_extracted_sections
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_document_status, set_document_status

_document_repository = DocumentRepository()
_usage_repository = UsageRepository()
_chunking_service = ChunkingService()
_embedding_service = EmbeddingService()
_qdrant_service = QdrantService()
_worker_loop: asyncio.AbstractEventLoop | None = None


class DocumentPipelinePermanentError(PermanentTaskError):
    def __init__(self, *, stage: str, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.error_details = build_document_error_details(
            stage=stage,
            code=code,
            category=category,
            retryable=False,
            message=message,
        )


class DocumentPipelineTransientError(TransientTaskError):
    def __init__(self, *, stage: str, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.error_details = build_document_error_details(
            stage=stage,
            code=code,
            category=category,
            retryable=True,
            message=message,
        )


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


def _object_key_prefix(object_key: str) -> str:
    normalized = object_key.strip()
    if not normalized:
        return normalized
    stem, separator, suffix = normalized.rpartition(".")
    if separator and suffix and "/" not in suffix:
        return stem
    return normalized


def _delete_objects_by_prefix(*, bucket: str, prefix: str) -> int:
    minio = minio_module.minio_client
    if minio is None:
        raise TransientTaskError("Object storage is unavailable")

    deleted_count = 0
    continuation_token: str | None = None
    while True:
        list_kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token
        try:
            response = minio.list_objects_v2(**list_kwargs)
        except Exception as exc:
            raise TransientTaskError("Object storage listing failed") from exc

        contents = response.get("Contents", [])
        for item in contents:
            key = item.get("Key")
            if not isinstance(key, str) or not key:
                continue
            try:
                minio.delete_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
                if error_code in {"NoSuchKey", "404", "NotFound"}:
                    continue
                raise TransientTaskError("Object storage delete failed") from exc
            except Exception as exc:
                raise TransientTaskError("Object storage delete failed") from exc
            deleted_count += 1

        if not response.get("IsTruncated"):
            break
        next_token = response.get("NextContinuationToken")
        if not isinstance(next_token, str) or not next_token:
            break
        continuation_token = next_token

    return deleted_count


async def _extract_and_store_document_pages_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> tuple[int, int, TextCleaningStats, EmbeddingResult]:
    try:
        parsed_document_id = _parse_uuid(document_id)
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="resolve_document",
            code="INVALID_DOCUMENT_ID",
            category="validation",
            message=f"Invalid document_id: {document_id}",
        ) from exc

    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(session, document_id=parsed_document_id)
        if document is None:
            raise DocumentPipelinePermanentError(
                stage="resolve_document",
                code="DOCUMENT_NOT_FOUND",
                category="validation",
                message=f"Document not found: {document_id}",
            )

        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="extract",
            stage_status="started",
        )
        try:
            content = _read_object_bytes(bucket=document.storage_bucket, object_key=document.storage_object_key)
        except PermanentTaskError as exc:
            raise DocumentPipelinePermanentError(
                stage="extract",
                code="SOURCE_OBJECT_MISSING",
                category="validation",
                message=str(exc),
            ) from exc
        except TransientTaskError as exc:
            raise DocumentPipelineTransientError(
                stage="extract",
                code="SOURCE_OBJECT_READ_FAILED",
                category="infrastructure",
                message=str(exc),
            ) from exc
        try:
            sections = extract_text_sections(file_type=document.file_type, content=content)
        except ValueError as exc:
            raise DocumentPipelinePermanentError(
                stage="extract",
                code="TEXT_EXTRACTION_FAILED",
                category="validation",
                message=str(exc),
            ) from exc
        cleaned_sections, cleaning_stats = clean_extracted_sections(sections)
        if not any(section.text for section in cleaned_sections):
            raise DocumentPipelinePermanentError(
                stage="clean",
                code="EMPTY_AFTER_CLEANING",
                category="validation",
                message="extracted document contains no text after cleaning",
            )
        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="extract",
            stage_status="completed",
            page_count=len(cleaned_sections),
            **cleaning_stats.as_log_fields(),
        )

        try:
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="chunk",
                stage_status="started",
            )
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
                raise DocumentPipelinePermanentError(
                    stage="chunk",
                    code="EMPTY_CHUNK_SET",
                    category="validation",
                    message="cleaned document produced no chunks",
                )
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="chunk",
                stage_status="completed",
                chunk_count=len(chunks),
            )
            await _document_repository.delete_document_chunks(
                session,
                document_id=parsed_document_id,
                index_version=settings.document_index_version,
            )
            created_chunks = []
            for chunk in chunks:
                qdrant_point_id = _qdrant_service.build_point_id(
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    index_version=chunk.index_version,
                )
                created_chunks.append(
                    await _document_repository.create_document_chunk(
                        session,
                        document_id=chunk.document_id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        qdrant_point_id=qdrant_point_id,
                        embedding_model=chunk.embedding_model,
                        index_version=chunk.index_version,
                    )
                )

            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="embed",
                stage_status="started",
            )
            try:
                embedding_result = await _embedding_service.embed_chunks(chunks=created_chunks)
            except PermanentEmbeddingError as exc:
                raise DocumentPipelinePermanentError(
                    stage="embed",
                    code="EMBEDDING_FAILED_PERMANENT",
                    category="validation",
                    message=str(exc),
                ) from exc
            except TransientEmbeddingError as exc:
                raise DocumentPipelineTransientError(
                    stage="embed",
                    code="EMBEDDING_FAILED_TRANSIENT",
                    category="infrastructure",
                    message=str(exc),
                ) from exc
            if len(embedding_result.vectors_by_chunk_id) != len(created_chunks):
                raise DocumentPipelinePermanentError(
                    stage="embed",
                    code="EMBEDDING_INCOMPLETE",
                    category="validation",
                    message="embedding generation did not cover all chunks",
                )
            for chunk_id, vector in embedding_result.vectors_by_chunk_id.items():
                if len(vector) != settings.qdrant_vector_size:
                    raise DocumentPipelinePermanentError(
                        stage="embed",
                        code="EMBEDDING_DIMENSION_MISMATCH",
                        category="validation",
                        message=(
                            f"embedding dimension mismatch for chunk {chunk_id}: "
                            f"expected {settings.qdrant_vector_size}, got {len(vector)}"
                        ),
                    )
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="embed",
                stage_status="completed",
                embedding_batch_count=embedding_result.batch_count,
                embedding_retry_count=embedding_result.retry_count,
            )
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="index",
                stage_status="started",
            )
            try:
                qdrant_result = await _qdrant_service.upsert_chunks(
                    organization_id=document.organization_id,
                    user_id=document.uploaded_by_user_id,
                    document_id=document.id,
                    filename=document.filename,
                    file_type=document.file_type,
                    chunks=created_chunks,
                    vectors_by_chunk_id=embedding_result.vectors_by_chunk_id,
                )
            except ValueError as exc:
                raise DocumentPipelinePermanentError(
                    stage="index",
                    code="QDRANT_PAYLOAD_INVALID",
                    category="validation",
                    message=str(exc),
                ) from exc
            except Exception as exc:
                raise DocumentPipelineTransientError(
                    stage="index",
                    code="QDRANT_UPSERT_FAILED",
                    category="infrastructure",
                    message="qdrant upsert failed",
                ) from exc
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=organization_id or str(document.organization_id),
                user_id=user_id or str(document.uploaded_by_user_id),
                stage="index",
                stage_status="completed",
                qdrant_upserted_count=qdrant_result.upserted_count,
                qdrant_batch_count=qdrant_result.batch_count,
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
                    "qdrant_upserted_count": qdrant_result.upserted_count,
                    "qdrant_batch_count": qdrant_result.batch_count,
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
            raise DocumentPipelineTransientError(
                stage="status",
                code="STATUS_INDEXED_UPDATE_FAILED",
                category="infrastructure",
                message=f"Unable to move document to indexed state: {document_id}",
            )
        return len(cleaned_sections), len(chunks), cleaning_stats, embedding_result


async def _delete_document_assets_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> tuple[int, int]:
    try:
        parsed_document_id = _parse_uuid(document_id)
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="resolve_document",
            code="INVALID_DOCUMENT_ID",
            category="validation",
            message=f"Invalid document_id: {document_id}",
        ) from exc

    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(session, document_id=parsed_document_id)
        if document is None:
            raise DocumentPipelinePermanentError(
                stage="resolve_document",
                code="DOCUMENT_NOT_FOUND",
                category="validation",
                message=f"Document not found: {document_id}",
            )

        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_index",
            stage_status="started",
        )
        try:
            await _qdrant_service.delete_document_points(
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
        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_index",
            stage_status="completed",
        )

        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_storage",
            stage_status="started",
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
        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_storage",
            stage_status="completed",
            deleted_object_count=deleted_object_count,
        )

        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_metadata",
            stage_status="started",
        )
        try:
            deleted_chunks = await _document_repository.delete_document_chunks(
                session,
                document_id=parsed_document_id,
                index_version=None,
            )
            deleted_pages = await _document_repository.delete_document_pages(
                session,
                document_id=parsed_document_id,
            )
            updated = await _document_repository.update_document_status(
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
        log_document_event(
            event="document.pipeline.stage",
            document_id=str(document.id),
            request_id=request_id,
            organization_id=organization_id or str(document.organization_id),
            user_id=user_id or str(document.uploaded_by_user_id),
            stage="delete_metadata",
            stage_status="completed",
            deleted_chunk_count=deleted_chunks,
            deleted_page_count=deleted_pages,
        )
        return deleted_chunks, deleted_pages


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
            error_details = details_from_exception(exc)
            set_document_status(
                document_id,
                status=DocumentStatus.failed,
                error_message=encode_document_error(error_details),
            )
            log_document_event(
                event="document.processing.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.failed.value,
                error=str(exc),
                error_stage=error_details["stage"],
                error_code=error_details["code"],
                error_category=error_details["category"],
                retryable=error_details["retryable"],
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
        _extract_and_store_document_pages_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
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
        qdrant_collection=settings.qdrant_collection,
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
    """Delete document vectors/storage assets and mark metadata as deleted."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        # Idempotent for hard-delete policies where row may already be removed.
        log_document_event(
            event="document.deletion.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code="not_found",
        )
        return {"document_id": document_id, "status": "skipped"}

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

    if status != DocumentStatus.deleting.value:
        deleting_updated = set_document_status(document_id, status=DocumentStatus.deleting)
        if not deleting_updated:
            raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")

    deleted_chunks, deleted_pages = _run(
        _delete_document_assets_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    log_document_event(
        event="document.deletion.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.deleted.value,
        deleted_chunk_count=deleted_chunks,
        deleted_page_count=deleted_pages,
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
