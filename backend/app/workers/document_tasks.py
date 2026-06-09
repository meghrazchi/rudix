from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import select

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.document_errors import (
    build_document_error_details,
    details_from_exception,
    encode_document_error,
)
from app.core.logging import log_chunking_event, log_document_event
from app.db.session import SessionLocal
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.documents.chunking.hashing import compute_chunk_hash
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.embedding_service import (
    EmbeddingResult,
    EmbeddingService,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.domains.documents.services.dlp_service import scan_text_for_dlp
from app.domains.documents.services.language_detection_service import (
    detect_language_from_text as _detect_language_from_text,
    confidence_bucket as _language_confidence_bucket,
)
from app.domains.documents.extraction import extract_document
from app.domains.documents.extraction.models import DocumentProfile
from app.domains.documents.services.ocr_language_config import resolve_ocr_tesseract_string
from app.domains.documents.services.ocr_detection import detect_ocr_need
from app.domains.documents.services.ocr_service import merge_ocr_with_sections, run_ocr
from app.domains.documents.services.qdrant_service import QdrantService
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
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector import ConnectorProvider
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_document_status, set_document_status

_document_repository = DocumentRepository()
_connector_repository = ConnectorRepository()
_pipeline_repository = PipelineRepository()
_usage_repository = UsageRepository()
_audit_log_service = AuditLogService()
_chunking_service = ChunkingService(strategy=settings.chunking_strategy)
_source_provenance_service = SourceProvenanceService()


def _make_chunking_service(
    profile_config: dict | None = None,
    *,
    index_version: str | None = None,
) -> ChunkingService:
    """Return a ChunkingService for the given inline profile config, or the system default.

    Accepted profile_config keys: strategy, chunk_size_tokens, chunk_overlap_tokens.
    Unknown keys are ignored.  Raises ValueError for invalid combinations
    (e.g. overlap >= size); callers should convert this to PermanentTaskError.
    """
    if not profile_config and index_version is None:
        return _chunking_service
    return ChunkingService(
        strategy=profile_config.get("strategy") if profile_config else settings.chunking_strategy,
        chunk_size_tokens=(
            profile_config.get("chunk_size_tokens")
            if profile_config
            else settings.chunk_size_tokens
        ),
        chunk_overlap_tokens=(
            profile_config.get("chunk_overlap_tokens")
            if profile_config
            else settings.chunk_overlap_tokens
        ),
        index_version=index_version,
    )


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


async def _upsert_connector_chunk_references(
    session,
    *,
    document,
    chunks,
) -> None:
    if document.connector_external_item_id is None or not chunks:
        return

    source_document = await _connector_repository.get_source_document_for_document(
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
        locator = _source_provenance_service.build_locator_snapshot(
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
        await _connector_repository.upsert_source_reference(
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
    chunking_service: ChunkingService | None = None,
    profile_source: str = "system_default",
    persist_document_state: bool = True,
    persist_document_pages: bool = True,
    record_usage_event: bool = True,
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
        svc = chunking_service if chunking_service is not None else _chunking_service
        effective_index_version = svc.index_version
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
                "index_version": effective_index_version,
                "embedding_model": settings.openai_embedding_model,
                "qdrant_collection": settings.qdrant_collection,
            },
        )

        current_stage = "extract"
        cleaned_sections = []
        chunks = []
        embedding_result: EmbeddingResult | None = None
        extraction_result = None
        updated = None
        ocr_applied = False
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

            # Advanced extraction pipeline (F237): structured block extraction for PDFs,
            # passthrough wrapping for other types.
            use_advanced_extraction = settings.feature_enable_advanced_pdf_extraction
            if use_advanced_extraction:
                try:
                    extraction_result = extract_document(
                        content,
                        file_type=document.file_type,
                        min_chars_per_page=settings.ocr_min_text_chars_per_page,
                        max_pages=settings.pdf_extraction_max_pages,
                        enable_table_extraction=settings.pdf_extraction_enable_tables,
                        enable_image_extraction=settings.pdf_extraction_enable_images,
                    )
                except ValueError as exc:
                    raise DocumentPipelinePermanentError(
                        stage="extract",
                        code="TEXT_EXTRACTION_FAILED",
                        category="validation",
                        message=str(exc),
                    ) from exc

                if extraction_result.document_profile == DocumentProfile.encrypted:
                    raise DocumentPipelinePermanentError(
                        stage="extract",
                        code="PDF_ENCRYPTED",
                        category="validation",
                        message="Document is password-protected and cannot be extracted",
                    )
                if extraction_result.document_profile == DocumentProfile.corrupted:
                    raise DocumentPipelinePermanentError(
                        stage="extract",
                        code="PDF_CORRUPTED",
                        category="validation",
                        message="Document appears to be corrupted or unreadable",
                    )

                sections = extraction_result.to_sections()
                extraction_snapshot = extraction_result.to_snapshot()

                async with SessionLocal() as extraction_session:
                    await _document_repository.update_document_extraction_snapshot(
                        extraction_session,
                        document_id=parsed_document_id,
                        extraction_snapshot=extraction_snapshot,
                    )
                    await extraction_session.commit()

                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="extract",
                    stage_status="completed",
                    page_count=len(sections),
                    document_profile=extraction_result.document_profile.value,
                    total_tables=extraction_result.total_table_blocks,
                    total_images=extraction_result.total_image_blocks,
                    extraction_engine=extraction_result.extraction_engine,
                    extraction_confidence=extraction_result.extraction_confidence,
                    extraction_duration_ms=extraction_result.duration_ms,
                    extraction_warnings=len(extraction_result.warnings),
                )
                await pipeline_recorder.emit_stage(
                    stage="extract",
                    stage_status="completed",
                    outputs={
                        "page_count": len(sections),
                        "document_profile": extraction_result.document_profile.value,
                        "total_text_blocks": extraction_result.total_text_blocks,
                        "total_table_blocks": extraction_result.total_table_blocks,
                        "total_image_blocks": extraction_result.total_image_blocks,
                        "extraction_engine": extraction_result.extraction_engine,
                        "extraction_confidence": extraction_result.extraction_confidence,
                        "extraction_duration_ms": extraction_result.duration_ms,
                        "warnings": extraction_result.warnings[:5],
                    },
                )
            else:
                # Legacy extraction path (fallback when advanced extraction is disabled).
                ocr_enabled_legacy = settings.ocr_enabled and document.file_type == "pdf"
                if ocr_enabled_legacy:
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
                extraction_result = None

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

            ocr_enabled = settings.ocr_enabled and document.file_type == "pdf"

            if ocr_enabled:
                current_stage = "detect_ocr"
                await pipeline_recorder.emit_stage(stage="detect_ocr", stage_status="started")
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
                    ocr_applied = True
                    current_stage = "ocr"
                    # Resolve effective OCR language: per-doc override → F230 document language → system default.
                    effective_ocr_languages = resolve_ocr_tesseract_string(
                        ocr_override=document.ocr_languages_override,
                        document_language=document.language,
                        system_default=settings.ocr_default_languages,
                    )
                    await pipeline_recorder.emit_stage(
                        stage="ocr",
                        stage_status="started",
                        config={
                            "languages": effective_ocr_languages,
                            "dpi": settings.ocr_image_dpi,
                            "max_pages": settings.ocr_max_pages,
                            "page_timeout_seconds": settings.ocr_page_timeout_seconds,
                            "language_source": (
                                "override"
                                if document.ocr_languages_override
                                else (
                                    "document_language" if document.language else "system_default"
                                )
                            ),
                        },
                    )
                    try:
                        ocr_result = run_ocr(
                            content,
                            detection.ocr_candidate_pages,
                            languages=effective_ocr_languages,
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
                    ocr_completed = sum(1 for p in ocr_result.pages if p.status == "completed")
                    ocr_failed = sum(1 for p in ocr_result.pages if p.status == "failed")
                    ocr_stage_status = "failed" if ocr_result.status == "failed" else "completed"
                    page_warnings = [p.warning for p in ocr_result.pages if p.warning]
                    ocr_quality_snapshot = {
                        "status": ocr_result.status,
                        "mode": detection.mode,
                        "languages": ocr_result.languages,
                        "effective_languages_string": effective_ocr_languages,
                        "pages_processed": len(ocr_result.pages),
                        "pages_completed": ocr_completed,
                        "pages_failed": ocr_failed,
                        "duration_ms": ocr_result.duration_ms,
                        "avg_confidence": ocr_result.avg_confidence,
                        "page_confidences": [
                            {
                                "page_number": p.page_number,
                                "status": p.status,
                                "confidence": p.confidence,
                            }
                            for p in ocr_result.pages
                        ],
                        "warnings": page_warnings,
                    }
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
                            "avg_confidence": ocr_result.avg_confidence,
                            "warnings": page_warnings,
                        },
                    )
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
                        ocr_avg_confidence=ocr_result.avg_confidence,
                        ocr_languages=ocr_result.languages,
                    )
                    # Persist quality snapshot without logging document content.
                    async with SessionLocal() as ocr_quality_session:
                        await _document_repository.update_document_ocr_quality(
                            ocr_quality_session,
                            document_id=parsed_document_id,
                            ocr_quality_snapshot=ocr_quality_snapshot,
                        )
                        await ocr_quality_session.commit()

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

            # Language detection — runs on cleaned text if not already admin-overridden.
            if document.language_source != "admin_override":
                current_stage = "detect_language"
                full_text_sample = "\n".join(
                    section.text for section in cleaned_sections if section.text
                )
                lang_result = _detect_language_from_text(full_text_sample)
                if (
                    lang_result.language_code is not None
                    or document.language_source != "upload_provided"
                ):
                    resolved_language = lang_result.language_code or document.language
                    resolved_source = (
                        "upload_provided"
                        if document.language_source == "upload_provided"
                        and document.language is not None
                        else "auto_detected"
                    )
                    async with SessionLocal() as lang_session:
                        await _document_repository.update_document_language(
                            lang_session,
                            document_id=parsed_document_id,
                            language=resolved_language,
                            language_confidence=lang_result.confidence
                            if lang_result.language_code is not None
                            else None,
                            language_source=resolved_source,
                        )
                        await lang_session.commit()
                    document.language = resolved_language
                    document.language_source = resolved_source
                    document.language_confidence = (
                        lang_result.confidence if lang_result.language_code is not None else None
                    )
                    log_document_event(
                        event="document.pipeline.stage",
                        document_id=str(document.id),
                        request_id=request_id,
                        organization_id=resolved_organization_id,
                        user_id=resolved_user_id,
                        stage="detect_language",
                        stage_status="completed",
                        language_code=resolved_language,
                        language_source=resolved_source,
                        confidence_bucket=_language_confidence_bucket(lang_result.confidence),
                    )
                    await pipeline_recorder.emit_stage(
                        stage="detect_language",
                        stage_status="completed",
                        outputs={
                            "language_code": resolved_language,
                            "language_source": resolved_source,
                            "confidence_bucket": _language_confidence_bucket(
                                lang_result.confidence
                            ),
                        },
                    )

            # DLP scan — runs on cleaned extracted text; never persists matched content.
            if settings.dlp_enabled:
                current_stage = "dlp"
                await pipeline_recorder.emit_stage(
                    stage="dlp",
                    stage_status="started",
                    config={
                        "action": settings.dlp_action,
                        "min_findings": settings.dlp_min_findings,
                    },
                )
                full_text = "\n".join(section.text for section in cleaned_sections if section.text)
                dlp_result = scan_text_for_dlp(
                    full_text,
                    enabled=True,
                    action=settings.dlp_action,  # type: ignore[arg-type]
                    min_findings=settings.dlp_min_findings,
                )
                dlp_result_dict = dlp_result.to_dict()
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="dlp",
                    stage_status="completed",
                    dlp_action=dlp_result.action,
                    dlp_total_findings=dlp_result.total_findings,
                )
                await pipeline_recorder.emit_stage(
                    stage="dlp",
                    stage_status="completed",
                    outputs={
                        "action": dlp_result.action,
                        "total_findings": dlp_result.total_findings,
                        "categories": [f.category for f in dlp_result.findings],
                    },
                )
                if dlp_result.action in ("quarantine", "reject"):
                    terminal_status = (
                        DocumentStatus.quarantined.value
                        if dlp_result.action == "quarantine"
                        else DocumentStatus.blocked.value
                    )
                    async with SessionLocal() as dlp_session:
                        await _document_repository.update_document_dlp_result(
                            dlp_session,
                            document_id=parsed_document_id,
                            status=terminal_status,
                            dlp_scan_result=dlp_result_dict,
                            error_message=f"DLP policy action: {dlp_result.action}",
                        )
                        await dlp_session.commit()
                    await _record_worker_audit_async(
                        action=f"document.processing.dlp_{dlp_result.action}",
                        resource_type="document",
                        resource_id=document_id,
                        organization_id=resolved_organization_id,
                        user_id=resolved_user_id,
                        request_id=request_id,
                        metadata={
                            "status": terminal_status,
                            "total_findings": dlp_result.total_findings,
                            "categories": [f.category for f in dlp_result.findings],
                        },
                    )
                    await pipeline_recorder.finalize_run(
                        status="failed",
                        outputs={"final_status": terminal_status},
                        error_message=f"DLP scan blocked document: {dlp_result.action}",
                    )
                    raise DocumentPipelinePermanentError(
                        stage="dlp",
                        code="DLP_POLICY_BLOCKED",
                        category="security",
                        message=f"Document blocked by DLP policy (action: {dlp_result.action})",
                    )
                elif dlp_result.action == "warn":
                    async with SessionLocal() as dlp_warn_session:
                        await _document_repository.update_document_dlp_result(
                            dlp_warn_session,
                            document_id=parsed_document_id,
                            status=DocumentStatus.processing.value,
                            dlp_scan_result=dlp_result_dict,
                        )
                        await dlp_warn_session.commit()

            current_stage = "index_cleanup"
            log_document_event(
                event="document.pipeline.stage",
                document_id=str(document.id),
                request_id=request_id,
                organization_id=resolved_organization_id,
                user_id=resolved_user_id,
                stage="index_cleanup",
                stage_status="started",
                index_version=effective_index_version,
            )
            await pipeline_recorder.emit_stage(
                stage="index_cleanup",
                stage_status="started",
                config={"index_version": effective_index_version},
            )
            try:
                await _qdrant_service.delete_document_points(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    index_version=effective_index_version,
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
                index_version=effective_index_version,
            )
            await pipeline_recorder.emit_stage(
                stage="index_cleanup",
                stage_status="completed",
                outputs={"index_version": effective_index_version},
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
                        "strategy": svc._profile.strategy,
                        "chunk_size_tokens": svc.chunk_size_tokens,
                        "chunk_overlap_tokens": svc.chunk_overlap_tokens,
                        "index_version": effective_index_version,
                        "profile_source": profile_source,
                    },
                )
                if persist_document_pages:
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
                log_chunking_event(
                    event="document.chunking.started",
                    document_id=str(document.id),
                    organization_id=resolved_organization_id,
                    user_id=user_id,
                    strategy=svc._profile.strategy,
                    profile_source=profile_source,
                    index_version=svc.index_version,
                )
                _chunk_stage_started_at = datetime.now(UTC)
                chunks = await svc.chunk(
                    document_id=parsed_document_id,
                    pages=cleaned_sections,
                    document_context={
                        "file_type": document.file_type,
                        "ocr_applied": ocr_applied,
                    },
                )
                if not chunks:
                    raise DocumentPipelinePermanentError(
                        stage="chunk",
                        code="EMPTY_CHUNK_SET",
                        category="validation",
                        message="cleaned document produced no chunks",
                    )
                _chunk_duration_ms = _safe_duration_ms(
                    started_at=_chunk_stage_started_at, ended_at=datetime.now(UTC)
                )
                _chunk_tokens = [c.token_count for c in chunks]
                _avg_tokens = round(sum(_chunk_tokens) / len(_chunk_tokens), 1)
                _max_tokens = max(_chunk_tokens)
                _min_tokens = min(_chunk_tokens)
                _empty_pages = sum(1 for s in cleaned_sections if not s.text.strip())
                _adaptive_log: dict = {}
                _reason_codes: list[str] | None = None
                _adaptive_language: str | None = None
                if svc.last_adaptive_selection is not None:
                    _sel = svc.last_adaptive_selection
                    _adaptive_log = {
                        "adaptive_selected_strategy": _sel.strategy,
                        "adaptive_reason_codes": _sel.reason_codes,
                    }
                    _reason_codes = _sel.reason_codes
                    if _sel.signals is not None:
                        _adaptive_language = _sel.signals.language
                _final_strategy = chunks[0].strategy_name if chunks else svc._profile.strategy
                _chunk_metrics: dict = {
                    "chunk_count": len(chunks),
                    "avg_tokens": _avg_tokens,
                    "max_tokens": _max_tokens,
                    "min_tokens": _min_tokens,
                    "empty_pages": _empty_pages,
                    "duration_ms": _chunk_duration_ms,
                    "strategy": _final_strategy,
                    "profile_source": profile_source,
                }
                if _reason_codes is not None:
                    _chunk_metrics["reason_codes"] = _reason_codes
                if _adaptive_language is not None:
                    _chunk_metrics["language"] = _adaptive_language
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="chunk",
                    stage_status="completed",
                    chunk_count=len(chunks),
                    **_adaptive_log,
                )
                log_chunking_event(
                    event="document.chunking.completed",
                    document_id=str(document.id),
                    organization_id=resolved_organization_id,
                    user_id=user_id,
                    strategy=_final_strategy,
                    chunk_count=len(chunks),
                    avg_tokens=_avg_tokens,
                    max_tokens=_max_tokens,
                    min_tokens=_min_tokens,
                    duration_ms=_chunk_duration_ms,
                    profile_source=profile_source,
                    reason_codes=_reason_codes,
                    empty_pages=_empty_pages,
                    language=_adaptive_language,
                    index_version=svc.index_version,
                )
                await pipeline_recorder.emit_stage(
                    stage="chunk",
                    stage_status="completed",
                    outputs={
                        "chunk_count": len(chunks),
                        **_adaptive_log,
                        "metrics": _chunk_metrics,
                    },
                )
                await _document_repository.delete_document_chunks(
                    session,
                    document_id=parsed_document_id,
                    index_version=effective_index_version,
                )

                # Detect hierarchical mode: any child chunk (level=1) in the result.
                is_hierarchical = any(c.chunk_level == 1 for c in chunks)
                payload_by_index: dict[int, Any] = {c.chunk_index: c for c in chunks}

                all_created_chunks = []
                for chunk in chunks:
                    # Parents (level=0) in hierarchical mode are not embedded; skip point ID.
                    is_embeddable = not is_hierarchical or chunk.chunk_level == 1
                    qdrant_point_id = (
                        _qdrant_service.build_point_id(
                            document_id=chunk.document_id,
                            chunk_index=chunk.chunk_index,
                            index_version=chunk.index_version,
                        )
                        if is_embeddable
                        else None
                    )
                    all_created_chunks.append(
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
                            chunk_hash=compute_chunk_hash(chunk.text),
                            section_path=(
                                chunk.section_path
                                if chunk.section_path is not None
                                else (
                                    f"page:{chunk.page_number}"
                                    if chunk.page_number is not None
                                    else None
                                )
                            ),
                            language=document.language,
                            chunk_level=chunk.chunk_level if is_hierarchical else None,
                            child_count=chunk.child_count,
                        )
                    )

                # Resolve parent_chunk_id FK and capture parent text for Qdrant payload.
                parent_text_by_child_id: dict[UUID, str] = {}
                if is_hierarchical:
                    created_by_index = {
                        p.chunk_index: c for p, c in zip(chunks, all_created_chunks, strict=True)
                    }
                    for chunk_payload, created in zip(chunks, all_created_chunks, strict=True):
                        if (
                            chunk_payload.chunk_level == 1
                            and chunk_payload.parent_chunk_index is not None
                        ):
                            parent_db = created_by_index.get(chunk_payload.parent_chunk_index)
                            if parent_db is not None:
                                created.parent_chunk_id = parent_db.id
                                parent_payload = payload_by_index.get(
                                    chunk_payload.parent_chunk_index
                                )
                                if parent_payload is not None:
                                    parent_text_by_child_id[created.id] = parent_payload.text
                    await session.flush()

                # Only embed chunks that go into the vector store.
                created_chunks = [
                    c
                    for c, p in zip(all_created_chunks, chunks, strict=True)
                    if not is_hierarchical or p.chunk_level == 1
                ]

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
                _strategy_name = chunks[0].strategy_name if chunks else "token_recursive"
                _strategy_version = chunks[0].strategy_version if chunks else "1.0"
                try:
                    qdrant_result = await _qdrant_service.upsert_chunks(
                        organization_id=document.organization_id,
                        user_id=document.uploaded_by_user_id,
                        document_id=document.id,
                        filename=document.filename,
                        file_type=document.file_type,
                        chunks=created_chunks,
                        vectors_by_chunk_id=embedding_result.vectors_by_chunk_id,
                        chunking_strategy=_strategy_name,
                        chunking_profile_version=_strategy_version,
                        parent_text_by_chunk_id=(
                            parent_text_by_child_id if parent_text_by_child_id else None
                        ),
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

                await _upsert_connector_chunk_references(
                    session,
                    document=document,
                    chunks=created_chunks,
                )

                if record_usage_event:
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
                _total_chunk_tokens = sum(c.token_count for c in chunks)
                _chunking_config_snapshot: dict = {
                    "strategy": _strategy_name,
                    "strategy_version": _strategy_version,
                    "chunk_size_tokens": svc.chunk_size_tokens,
                    "chunk_overlap_tokens": svc.chunk_overlap_tokens,
                    "embedding_model": svc.embedding_model,
                    "index_version": svc.index_version,
                    "profile_source": profile_source,
                    "ocr_applied": ocr_applied,
                    "total_chunk_count": len(chunks),
                    "total_chunk_tokens": _total_chunk_tokens,
                }
                if extraction_result is not None:
                    _chunking_config_snapshot["document_profile"] = (
                        extraction_result.document_profile.value
                    )
                    _chunking_config_snapshot["total_table_blocks"] = (
                        extraction_result.total_table_blocks
                    )
                    _chunking_config_snapshot["total_image_blocks"] = (
                        extraction_result.total_image_blocks
                    )
                if is_hierarchical:
                    parent_count = sum(1 for p in chunks if p.chunk_level == 0)
                    child_count_total = sum(1 for p in chunks if p.chunk_level == 1)
                    _chunking_config_snapshot["hierarchical_mode"] = True
                    _chunking_config_snapshot["parent_chunk_count"] = parent_count
                    _chunking_config_snapshot["child_chunk_count"] = child_count_total
                _adaptive_sel = svc.last_adaptive_selection
                if _adaptive_sel is not None:
                    _chunking_config_snapshot["adaptive_selected_strategy"] = _adaptive_sel.strategy
                    _chunking_config_snapshot["adaptive_reason_codes"] = _adaptive_sel.reason_codes
                    if _adaptive_sel.signals is not None:
                        sig = _adaptive_sel.signals
                        _chunking_config_snapshot["adaptive_signals"] = {
                            "file_type": sig.file_type,
                            "page_count": sig.page_count,
                            "ocr_applied": sig.ocr_applied,
                            "heading_density": sig.heading_density,
                            "total_token_count": sig.total_token_count,
                        }
                if embedding_result is not None:
                    _chunking_config_snapshot["embedding_provider_type"] = (
                        embedding_result.provider_type
                    )
                    _chunking_config_snapshot["embedding_vector_dimension"] = (
                        embedding_result.vector_dimension
                    )
                if persist_document_state:
                    if embedding_result is not None:
                        await _document_repository.update_document_embedding_metadata(
                            session,
                            document_id=parsed_document_id,
                            embedding_provider_type=embedding_result.provider_type,
                            embedding_vector_dimension=embedding_result.vector_dimension,
                        )
                    updated = await _document_repository.update_document_status(
                        session,
                        document_id=parsed_document_id,
                        status=DocumentStatus.indexed.value,
                        error_message=None,
                        page_count=len(cleaned_sections),
                        chunk_count=len(chunks),
                        chunking_strategy=_strategy_name,
                        chunking_profile_version=_strategy_version,
                        chunking_config_snapshot=_chunking_config_snapshot,
                    )
                else:
                    updated = object()
                await session.commit()
            except Exception:
                await session.rollback()
                raise

            if persist_document_state and updated is None:
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
                    "document_status": (
                        DocumentStatus.indexed.value
                        if persist_document_state
                        else "evaluation_indexed"
                    ),
                    "page_count": len(cleaned_sections),
                    "chunk_count": len(chunks),
                    "index_version": effective_index_version,
                },
            )
            return len(cleaned_sections), len(chunks), cleaning_stats, embedding_result
        except Exception as exc:
            details = details_from_exception(exc)
            failing_stage = details.get("stage", "unknown")
            if failing_stage == "unknown":
                failing_stage = current_stage
            if failing_stage == "chunk":
                log_chunking_event(
                    event="document.chunking.failed",
                    document_id=document_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    error_code=details.get("code", "UNKNOWN"),
                    error_message=details.get("message", str(exc)),
                )
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
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="upload_failed",
                severity="error",
                title="Document processing failed",
                message="The document could not be indexed. Check the document details for more information.",
                href=f"/documents?highlight={document_id}",
                source_id=document_id,
            )
            from app.workers.email_helper import emit_upload_failure_email

            emit_upload_failure_email(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                document_id=document_id,
                error_summary=error_details.get("stage"),
            )
        except Exception:
            return


class DocumentDeleteTask(DocumentTask):
    """Task base class for document deletion — leaves document in delete_requested on terminal failure."""

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
            error_message = f"delete_failed: {encode_document_error(error_details)}"
            # Revert to delete_requested so the admin can retry the cleanup.
            set_document_status(
                document_id,
                status=DocumentStatus.delete_requested,
                error_message=error_message,
            )
            log_document_event(
                event="document.deletion.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.delete_requested.value,
                error=str(exc),
                error_stage=error_details["stage"],
                error_code=error_details["code"],
                error_category=error_details["category"],
                retryable=error_details["retryable"],
            )
            _record_worker_audit(
                action="document.delete.failed",
                resource_type="document",
                resource_id=document_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "task_name": self.name,
                    "status": DocumentStatus.delete_requested.value,
                    "error_type": exc.__class__.__name__,
                    "error_code": error_details["code"],
                    "error_category": error_details["category"],
                    "retryable": error_details["retryable"],
                },
            )
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="security_warning",
                severity="error",
                title="Document deletion failed",
                message="Cleanup could not complete. An admin can retry the deletion.",
                href=f"/admin/documents/deletion?highlight={document_id}",
                source_id=document_id,
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
    chunking_profile_config: dict | None = None,
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

    try:
        _svc = _make_chunking_service(chunking_profile_config)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc

    page_count, chunk_count, cleaning_stats, embedding_result = _run(
        _extract_and_store_document_pages_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="document.process",
            chunking_service=_svc,
            profile_source="custom_profile" if chunking_profile_config else "system_default",
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
    from app.workers.notification_helper import emit_notification

    emit_notification(
        organization_id=organization_id,
        user_id=user_id,
        event_type="upload_indexed",
        severity="info",
        title="Document indexed",
        message=f"{page_count} page(s), {chunk_count} chunk(s) ready for search.",
        href=f"/documents?highlight={document_id}",
        source_id=document_id,
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


@celery_app.task(name="documents.delete", bind=True, base=DocumentDeleteTask, ignore_result=True)
def delete_document(
    self: DocumentDeleteTask,
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

    if status not in {DocumentStatus.deleting.value, DocumentStatus.delete_requested.value}:
        deleting_updated = set_document_status(document_id, status=DocumentStatus.deleting)
        if not deleting_updated:
            raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")
    elif status == DocumentStatus.delete_requested.value:
        # Transition from delete_requested → deleting as the task begins.
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
    chunking_profile_config: dict | None = None,
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

    try:
        _svc = _make_chunking_service(chunking_profile_config)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc

    page_count, chunk_count, cleaning_stats, embedding_result = _run(
        _extract_and_store_document_pages_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="document.reindex",
            chunking_service=_svc,
            profile_source="custom_profile" if chunking_profile_config else "system_default",
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


async def _backfill_dispatch_async(
    organization_uuid: UUID,
    *,
    chunking_profile_config: dict | None,
    request_id: str | None,
    user_id: str | None,
) -> int:
    """Query all indexed documents for an org and dispatch reindex tasks for each."""
    dispatched = 0
    offset = 0
    page_size = 100
    while True:
        async with SessionLocal() as session:
            docs = await _document_repository.list_documents(
                session,
                organization_id=organization_uuid,
                status=DocumentStatus.indexed.value,
                limit=page_size,
                offset=offset,
            )
        if not docs:
            break
        for doc in docs:
            celery_app.send_task(
                "documents.reindex",
                kwargs={
                    "document_id": str(doc.id),
                    "organization_id": str(organization_uuid),
                    "user_id": user_id,
                    "request_id": request_id,
                    "chunking_profile_config": chunking_profile_config,
                },
            )
            dispatched += 1
        offset += len(docs)
        if len(docs) < page_size:
            break
    return dispatched


@celery_app.task(name="documents.backfill", bind=True, base=DocumentTask, ignore_result=True)
def backfill_documents(
    self: DocumentTask,
    *,
    organization_id: str,
    chunking_profile_config: dict | None = None,
    request_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    """Queue reindex tasks for all indexed documents in the given organization.

    Uses chunking_profile_config when provided; falls back to the system default.
    Safe to re-run: each dispatched reindex task is itself idempotent.
    """
    try:
        org_uuid = _parse_uuid(organization_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid organization_id: {organization_id}") from exc

    try:
        _make_chunking_service(chunking_profile_config)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc

    dispatched = _run(
        _backfill_dispatch_async(
            org_uuid,
            chunking_profile_config=chunking_profile_config,
            request_id=request_id,
            user_id=user_id,
        )
    )
    log_document_event(
        event="document.backfill.completed",
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        dispatched_count=dispatched,
    )
    _record_worker_audit(
        action="document.backfill.completed",
        resource_type="organization",
        resource_id=organization_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={"dispatched_count": dispatched},
    )
    return {"organization_id": organization_id, "dispatched_count": dispatched}
