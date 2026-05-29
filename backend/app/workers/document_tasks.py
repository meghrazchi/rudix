from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime
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
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.embedding_service import (
    EmbeddingResult,
    EmbeddingService,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.domains.documents.services.qdrant_service import QdrantService
from app.domains.documents.services.ocr_detection import detect_ocr_need
from app.domains.documents.services.ocr_service import merge_ocr_with_sections, run_ocr
from app.domains.documents.services.text_extraction import (
    extract_pdf_pages_native,
    extract_text_sections,
)
from app.domains.documents.services.text_normalization import (
    TextCleaningStats,
    clean_extracted_sections,
)
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.domains.pipeline.services.pipeline_event_service import sanitize_pipeline_payload
from app.models.enums import DocumentStatus
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_document_status, set_document_status

_document_repository = DocumentRepository()
_pipeline_repository = PipelineRepository()
_usage_repository = UsageRepository()
_audit_log_service = AuditLogService()
_chunking_service = ChunkingService()
_embedding_service = EmbeddingService()
_qdrant_service = QdrantService()


def _safe_duration_ms(*, started_at: datetime, ended_at: datetime) -> int:
    return max(int((ended_at - started_at).total_seconds() * 1000), 0)


class PipelineRunRecorder:
    def __init__(
        self,
        *,
        run_id: UUID | None,
        run_started_at: datetime,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
    ) -> None:
        self.run_id = run_id
        self.run_started_at = run_started_at
        self.document_id = document_id
        self.organization_id = organization_id
        self.user_id = user_id
        self._sequence = 0
        self._stage_started_at: dict[str, datetime] = {}
        self._stage_finalized: set[str] = set()

    @classmethod
    async def create(
        cls,
        *,
        document_id: str,
        organization_id: str | None,
        user_id: str | None,
        organization_uuid: UUID,
        document_uuid: UUID,
        pipeline_type: str,
        inputs: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> PipelineRunRecorder:
        run_started_at = datetime.now(UTC)
        run_id: UUID | None = None

        if settings.feature_enable_pipeline_explorer:
            try:
                async with SessionLocal() as telemetry_session:
                    async with telemetry_session.begin():
                        run = await _pipeline_repository.create_pipeline_run(
                            telemetry_session,
                            organization_id=organization_uuid,
                            document_id=document_uuid,
                            pipeline_type=pipeline_type,
                            status="running",
                            started_at=run_started_at,
                            inputs=sanitize_pipeline_payload(inputs or {}),
                            config=sanitize_pipeline_payload(config or {}),
                        )
                    run_id = run.id
            except Exception as exc:
                log_document_event(
                    event="document.pipeline.telemetry.failed",
                    document_id=document_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    error=str(exc),
                    telemetry_operation="create_run",
                )

        return cls(
            run_id=run_id,
            run_started_at=run_started_at,
            document_id=document_id,
            organization_id=organization_id,
            user_id=user_id,
        )

    async def emit_stage(
        self,
        *,
        stage: str,
        stage_status: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        logs: list[Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if self.run_id is None:
            return

        now = datetime.now(UTC)
        started_at: datetime | None = None
        completed_at: datetime | None = None
        duration_ms: int | None = None

        if stage_status == "started":
            self._stage_started_at[stage] = now
            started_at = now
        else:
            started_at = self._stage_started_at.get(stage, now)
            completed_at = now
            duration_ms = _safe_duration_ms(started_at=started_at, ended_at=now)
            self._stage_finalized.add(stage)

        try:
            async with SessionLocal() as telemetry_session:
                async with telemetry_session.begin():
                    await _pipeline_repository.create_pipeline_event(
                        telemetry_session,
                        pipeline_run_id=self.run_id,
                        sequence=self._sequence,
                        node_name=stage,
                        status=stage_status,
                        started_at=started_at,
                        completed_at=completed_at,
                        duration_ms=duration_ms,
                        inputs=sanitize_pipeline_payload(inputs or {}),
                        outputs=sanitize_pipeline_payload(outputs or {}),
                        config=sanitize_pipeline_payload(config or {}),
                        logs=sanitize_pipeline_payload(logs or []),
                        error_message=sanitize_pipeline_payload(error_message),
                        error_details=sanitize_pipeline_payload(error_details or {}),
                    )
                    self._sequence += 1
        except Exception as exc:
            log_document_event(
                event="document.pipeline.telemetry.failed",
                document_id=self.document_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                error=str(exc),
                stage=stage,
                stage_status=stage_status,
                telemetry_operation="create_stage_event",
            )

    async def fail_stage_if_open(
        self,
        *,
        stage: str,
        error_message: str,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if stage in self._stage_finalized:
            return
        await self.emit_stage(
            stage=stage,
            stage_status="failed",
            error_message=error_message,
            error_details=error_details or {},
        )

    async def finalize_run(
        self,
        *,
        status: str,
        outputs: dict[str, Any] | None = None,
        logs: list[Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        if self.run_id is None:
            return
        completed_at = datetime.now(UTC)
        try:
            async with SessionLocal() as telemetry_session:
                async with telemetry_session.begin():
                    await _pipeline_repository.update_pipeline_run(
                        telemetry_session,
                        pipeline_run_id=self.run_id,
                        status=status,
                        completed_at=completed_at,
                        duration_ms=_safe_duration_ms(
                            started_at=self.run_started_at, ended_at=completed_at
                        ),
                        outputs=sanitize_pipeline_payload(outputs or {}),
                        logs=sanitize_pipeline_payload(logs or []),
                        error_message=sanitize_pipeline_payload(error_message),
                        error_details=sanitize_pipeline_payload(error_details or {}),
                    )
        except Exception as exc:
            log_document_event(
                event="document.pipeline.telemetry.failed",
                document_id=self.document_id,
                organization_id=self.organization_id,
                user_id=self.user_id,
                error=str(exc),
                status=status,
                telemetry_operation="update_run",
            )


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


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _record_worker_audit_async(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    organization_uuid = _parse_optional_uuid(organization_id)
    if organization_uuid is None:
        return
    user_uuid = _parse_optional_uuid(user_id)
    parsed_resource_id = _parse_optional_uuid(resource_id)
    try:
        async with SessionLocal() as audit_session:
            wrote_audit = await _audit_log_service.record(
                audit_session,
                organization_id=organization_uuid,
                user_id=user_uuid,
                action=action,
                resource_type=resource_type,
                resource_id=parsed_resource_id,
                request_id=request_id,
                metadata=metadata or {},
            )
            if wrote_audit:
                await audit_session.commit()
    except Exception:
        return


def _record_worker_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _run(
        _record_worker_audit_async(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            metadata=metadata,
        )
    )


def _read_object_bytes(*, bucket: str, object_key: str) -> bytes:
    minio = minio_module.get_minio_client()
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
    minio = minio_module.get_minio_client()
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
    pipeline_type: str = "document.process",
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
        document = await _document_repository.get_document_by_id(
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
            config={
                "index_version": settings.document_index_version,
                "embedding_model": settings.openai_embedding_model,
                "qdrant_collection": settings.qdrant_collection,
            },
        )

        current_stage = "extract"
        cleaned_sections = []
        chunks = []
        embedding_result: EmbeddingResult | None = None
        updated = None
        try:
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="extract",
                stage_status="started",
            )
            await pipeline_recorder.emit_stage(
                stage="extract",
                stage_status="started",
                inputs={
                    "bucket": document.storage_bucket,
                    "object_key": document.storage_object_key,
                },
            )
            try:
                content = _read_object_bytes(
                    bucket=document.storage_bucket, object_key=document.storage_object_key
                )
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
            ocr_enabled = settings.ocr_enabled and document.file_type == "pdf"
            if ocr_enabled:
                sections = extract_pdf_pages_native(content)
            else:
                try:
                    sections = extract_text_sections(
                        file_type=document.file_type, content=content
                    )
                except ValueError as exc:
                    raise DocumentPipelinePermanentError(
                        stage="extract",
                        code="TEXT_EXTRACTION_FAILED",
                        category="validation",
                        message=str(exc),
                    ) from exc

            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="extract",
                stage_status="completed",
                page_count=len(sections),
            )
            await pipeline_recorder.emit_stage(
                stage="extract",
                stage_status="completed",
                outputs={"page_count": len(sections)},
            )

            if ocr_enabled:
                current_stage = "detect_ocr"
                await pipeline_recorder.emit_stage(
                    stage="detect_ocr", stage_status="started"
                )
                detection = detect_ocr_need(
                    sections,
                    min_chars_per_page=settings.ocr_min_text_chars_per_page,
                )
                await pipeline_recorder.emit_stage(
                    stage="detect_ocr",
                    stage_status="completed",
                    outputs={
                        "requires_ocr": detection.requires_ocr,
                        "mode": detection.mode,
                        "page_count": detection.page_count,
                        "native_text_pages": detection.native_text_pages,
                        "ocr_candidate_pages": detection.ocr_candidate_pages,
                        "reason": detection.reason,
                    },
                )
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="detect_ocr",
                    stage_status="completed",
                    ocr_required=detection.requires_ocr,
                    ocr_mode=detection.mode,
                )

                if detection.requires_ocr:
                    current_stage = "ocr"
                    await pipeline_recorder.emit_stage(
                        stage="ocr",
                        stage_status="started",
                        config={
                            "languages": settings.ocr_default_languages,
                            "dpi": settings.ocr_image_dpi,
                            "max_pages": settings.ocr_max_pages,
                            "page_timeout_seconds": settings.ocr_page_timeout_seconds,
                        },
                    )
                    try:
                        ocr_result = run_ocr(
                            content,
                            detection.ocr_candidate_pages,
                            languages=settings.ocr_default_languages,
                            dpi=settings.ocr_image_dpi,
                            page_timeout_seconds=settings.ocr_page_timeout_seconds,
                            max_pages=settings.ocr_max_pages,
                        )
                    except RuntimeError as exc:
                        raise DocumentPipelinePermanentError(
                            stage="ocr",
                            code="OCR_DEPENDENCIES_MISSING",
                            category="infrastructure",
                            message=str(exc),
                        ) from exc

                    sections = merge_ocr_with_sections(
                        sections,
                        ocr_result,
                        min_chars_per_page=settings.ocr_min_text_chars_per_page,
                    )
                    ocr_completed = sum(
                        1 for p in ocr_result.pages if p.status == "completed"
                    )
                    ocr_failed = sum(
                        1 for p in ocr_result.pages if p.status == "failed"
                    )
                    ocr_stage_status = (
                        "failed"
                        if ocr_result.status == "failed"
                        else "completed"
                    )
                    await pipeline_recorder.emit_stage(
                        stage="ocr",
                        stage_status=ocr_stage_status,
                        outputs={
                            "status": ocr_result.status,
                            "mode": detection.mode,
                            "languages": ocr_result.languages,
                            "pages_processed": len(ocr_result.pages),
                            "pages_completed": ocr_completed,
                            "pages_failed": ocr_failed,
                            "duration_ms": ocr_result.duration_ms,
                            "warnings": [
                                p.warning
                                for p in ocr_result.pages
                                if p.warning
                            ],
                        },
                    )
                    page_warnings = [p.warning for p in ocr_result.pages if p.warning]
                    log_document_event(
                        event="document.pipeline.stage",
                        document_id=str(document.id),
                        request_id=request_id,
                        organization_id=resolved_organization_id,
                        user_id=resolved_user_id,
                        stage="ocr",
                        stage_status=ocr_stage_status,
                        ocr_status=ocr_result.status,
                        ocr_pages_processed=len(ocr_result.pages),
                        ocr_duration_ms=ocr_result.duration_ms,
                        ocr_page_warnings=page_warnings,
                    )
                    if ocr_result.status == "failed":
                        first_warning = page_warnings[0] if page_warnings else "unknown error"
                        raise DocumentPipelinePermanentError(
                            stage="ocr",
                            code="OCR_FAILED",
                            category="processing",
                            message=f"OCR failed on all candidate pages: {first_warning}",
                        )

            cleaned_sections, cleaning_stats = clean_extracted_sections(sections)
            if not any(section.text for section in cleaned_sections):
                raise DocumentPipelinePermanentError(
                    stage="clean",
                    code="EMPTY_AFTER_CLEANING",
                    category="validation",
                    message="extracted document contains no text after cleaning",
                )

            current_stage = "index_cleanup"
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="index_cleanup",
                stage_status="started",
                index_version=settings.document_index_version,
            )
            await pipeline_recorder.emit_stage(
                stage="index_cleanup",
                stage_status="started",
                config={"index_version": settings.document_index_version},
            )
            try:
                await _qdrant_service.delete_document_points(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    index_version=settings.document_index_version,
                )
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
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="index_cleanup",
                stage_status="completed",
                index_version=settings.document_index_version,
            )
            await pipeline_recorder.emit_stage(
                stage="index_cleanup",
                stage_status="completed",
                outputs={"index_version": settings.document_index_version},
            )

            try:
                current_stage = "chunk"
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="chunk",
                    stage_status="started",
                )
                await pipeline_recorder.emit_stage(
                    stage="chunk",
                    stage_status="started",
                    config={
                        "chunk_size_tokens": settings.chunk_size_tokens,
                        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
                        "index_version": settings.document_index_version,
                    },
                )
                await _document_repository.delete_document_pages(
                    session, document_id=parsed_document_id
                )
                for section in cleaned_sections:
                    await _document_repository.create_document_page(
                        session,
                        document_id=parsed_document_id,
                        page_number=section.page_number,
                        text=section.text,
                        char_count=section.char_count,
                    )
                chunks = await _chunking_service.chunk(
                    document_id=parsed_document_id, pages=cleaned_sections
                )
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
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="chunk",
                    stage_status="completed",
                    chunk_count=len(chunks),
                )
                await pipeline_recorder.emit_stage(
                    stage="chunk",
                    stage_status="completed",
                    outputs={"chunk_count": len(chunks)},
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

                current_stage = "embed"
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="embed",
                    stage_status="started",
                )
                await pipeline_recorder.emit_stage(
                    stage="embed",
                    stage_status="started",
                    config={"embedding_model": settings.openai_embedding_model},
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
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="embed",
                    stage_status="completed",
                    embedding_batch_count=embedding_result.batch_count,
                    embedding_retry_count=embedding_result.retry_count,
                )
                await pipeline_recorder.emit_stage(
                    stage="embed",
                    stage_status="completed",
                    outputs={
                        "batch_count": embedding_result.batch_count,
                        "retry_count": embedding_result.retry_count,
                        "input_tokens": embedding_result.input_tokens,
                        "total_tokens": embedding_result.total_tokens,
                        "latency_ms": embedding_result.latency_ms,
                    },
                )

                current_stage = "index"
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="index",
                    stage_status="started",
                )
                await pipeline_recorder.emit_stage(
                    stage="index",
                    stage_status="started",
                    config={"collection": settings.qdrant_collection},
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
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="index",
                    stage_status="completed",
                    qdrant_upserted_count=qdrant_result.upserted_count,
                    qdrant_batch_count=qdrant_result.batch_count,
                )
                await pipeline_recorder.emit_stage(
                    stage="index",
                    stage_status="completed",
                    outputs={
                        "qdrant_upserted_count": qdrant_result.upserted_count,
                        "qdrant_batch_count": qdrant_result.batch_count,
                    },
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
                current_stage = "status"
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
            if embedding_result is None:
                raise DocumentPipelineTransientError(
                    stage="embed",
                    code="EMBEDDING_MISSING",
                    category="infrastructure",
                    message=f"Embedding result was not produced for document: {document_id}",
                )

            await pipeline_recorder.finalize_run(
                status="completed",
                outputs={
                    "document_status": DocumentStatus.indexed.value,
                    "page_count": len(cleaned_sections),
                    "chunk_count": len(chunks),
                    "index_version": settings.document_index_version,
                },
            )
            return len(cleaned_sections), len(chunks), cleaning_stats, embedding_result
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
            )
            raise


async def _delete_document_assets_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    pipeline_type: str = "document.delete",
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
        document = await _document_repository.get_document_by_id(
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
            log_document_event(
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
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="delete_index",
                stage_status="completed",
            )
            await pipeline_recorder.emit_stage(stage="delete_index", stage_status="completed")

            current_stage = "delete_storage"
            log_document_event(
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
            log_document_event(
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

            current_stage = "delete_metadata"
            log_document_event(
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
            _record_worker_audit(
                action="document.task.failed",
                resource_type="document",
                resource_id=document_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "task_name": self.name,
                    "status": DocumentStatus.failed.value,
                    "error_type": exc.__class__.__name__,
                    "error_code": error_details["code"],
                    "error_category": error_details["category"],
                    "retryable": error_details["retryable"],
                },
            )
        except Exception:
            return


@celery_app.task(name="documents.process", bind=True, base=DocumentTask, ignore_result=True)
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
            pipeline_type="document.process",
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
    _record_worker_audit(
        action="document.process.completed",
        resource_type="document",
        resource_id=document_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={
            "status": DocumentStatus.indexed.value,
            "page_count": page_count,
            "chunk_count": chunk_count,
        },
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


@celery_app.task(name="documents.delete", bind=True, base=DocumentTask, ignore_result=True)
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
            pipeline_type="document.delete",
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
    _record_worker_audit(
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


@celery_app.task(name="documents.reindex", bind=True, base=DocumentTask, ignore_result=True)
def reindex_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int | float]:
    """Re-index a document idempotently for the active index/model version."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")
    if status == DocumentStatus.deleted.value:
        raise PermanentTaskError(f"Cannot reindex deleted document: {document_id}")
    if status == DocumentStatus.deleting.value:
        raise PermanentTaskError(f"Cannot reindex deleting document: {document_id}")

    if status != DocumentStatus.processing.value:
        processing_updated = set_document_status(document_id, status=DocumentStatus.processing)
        if not processing_updated:
            raise TransientTaskError(f"Unable to move document to processing state: {document_id}")

    log_document_event(
        event="document.reindex.started",
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
            pipeline_type="document.reindex",
        )
    )

    log_document_event(
        event="document.reindex.completed",
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
    _record_worker_audit(
        action="document.reindex.completed",
        resource_type="document",
        resource_id=document_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={
            "status": DocumentStatus.indexed.value,
            "page_count": page_count,
            "chunk_count": chunk_count,
        },
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
