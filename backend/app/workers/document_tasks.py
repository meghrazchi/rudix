from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import select, text

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
from app.domains.documents.extraction import extract_document
from app.domains.documents.extraction.models import DocumentProfile
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.dlp_service import scan_text_for_dlp
from app.domains.documents.services.embedding_service import (
    EmbeddingResult,
    EmbeddingService,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.domains.documents.services.language_detection_service import (
    confidence_bucket as _language_confidence_bucket,
)
from app.domains.documents.services.language_detection_service import (
    detect_language_from_text as _detect_language_from_text,
)
from app.domains.documents.services.ocr_detection import detect_ocr_need
from app.domains.documents.services.ocr_language_config import resolve_ocr_tesseract_string
from app.domains.documents.services.ocr_quality_service import OcrQualityService
from app.domains.documents.services.ocr_service import merge_ocr_with_sections, run_ocr
from app.domains.documents.services.qdrant_service import QdrantService
from app.domains.documents.services.table_chunking_service import build_table_chunk
from app.domains.documents.services.text_extraction import (
    extract_pdf_pages_native,
    extract_text_sections,
)
from app.domains.documents.services.text_normalization import (
    TextCleaningStats,
    clean_extracted_sections,
)
from app.domains.graph.services.entity_extraction_service import EntityExtractionService
from app.domains.graph.services.entity_resolution_service import (
    EntityResolutionInput,
    EntityResolutionService,
)
from app.domains.graph.services.graph_service import GraphService
from app.domains.graph.services.relation_extraction_service import RelationExtractionService
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.domains.pipeline.services.pipeline_event_service import sanitize_pipeline_payload
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.enums import DocumentStatus, GraphExtractionStatus
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
_graph_service = GraphService()
_entity_resolution_service = EntityResolutionService()
_entity_extraction_service = EntityExtractionService(
    batch_size=settings.entity_extraction_batch_size,
    timeout_seconds=settings.entity_extraction_timeout_seconds,
    max_retries=settings.entity_extraction_max_retries,
)
_relation_extraction_service = RelationExtractionService(
    batch_size=settings.relation_extraction_batch_size,
    timeout_seconds=settings.relation_extraction_timeout_seconds,
    max_retries=settings.relation_extraction_max_retries,
    confidence_threshold=settings.relation_confidence_threshold,
)


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
_ocr_quality_service = OcrQualityService()


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
        chunk_profile = getattr(svc, "_profile", None)
        chunk_strategy = getattr(chunk_profile, "strategy", settings.chunking_strategy)
        chunk_size_tokens = getattr(svc, "chunk_size_tokens", settings.chunk_size_tokens)
        chunk_overlap_tokens = getattr(svc, "chunk_overlap_tokens", settings.chunk_overlap_tokens)
        effective_index_version = getattr(svc, "index_version", settings.document_index_version)
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
        _table_chunk_count = 0
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
                    # Classify OCR quality and persist snapshot + derived fields (F299).
                    derived_quality_status = _ocr_quality_service.classify(
                        avg_confidence=ocr_result.avg_confidence,
                        ocr_status=ocr_result.status,
                        ocr_applied=True,
                        file_type=document.file_type,
                    )
                    async with SessionLocal() as ocr_quality_session:
                        await _document_repository.update_document_ocr_quality(
                            ocr_quality_session,
                            document_id=parsed_document_id,
                            ocr_quality_snapshot=ocr_quality_snapshot,
                            ocr_quality_status=derived_quality_status,
                            ocr_avg_confidence=ocr_result.avg_confidence,
                        )
                        # Persist per-page OCR confidence for retrieval downranking.
                        page_confidence_map = {
                            p.page_number: p.confidence
                            for p in ocr_result.pages
                            if p.status == "completed" and p.confidence is not None
                        }
                        if page_confidence_map:
                            await _document_repository.update_document_pages_ocr_confidence_bulk(
                                ocr_quality_session,
                                document_id=parsed_document_id,
                                page_confidences=page_confidence_map,
                            )
                        await ocr_quality_session.commit()
                    log_document_event(
                        event="document.ocr_quality.classified",
                        document_id=str(document.id),
                        organization_id=resolved_organization_id,
                        ocr_quality_status=derived_quality_status,
                        ocr_avg_confidence=ocr_result.avg_confidence,
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
                        "strategy": chunk_strategy,
                        "chunk_size_tokens": chunk_size_tokens,
                        "chunk_overlap_tokens": chunk_overlap_tokens,
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
                    strategy=chunk_strategy,
                    profile_source=profile_source,
                    index_version=effective_index_version,
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
                _final_strategy = chunks[0].strategy_name if chunks else chunk_strategy
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

                # Table-aware chunking (F298): create structured table chunks from extracted
                # table blocks. These supplement the regular text chunks and are indexed
                # with chunk_type='table' so the retrieval boost can identify them.
                if (
                    settings.feature_enable_table_aware_retrieval
                    and extraction_result is not None
                    and extraction_result.total_table_blocks > 0
                ):
                    _table_chunk_base = len(chunks)
                    _table_global_idx = 0
                    for _page_result in extraction_result.pages:
                        if not _page_result.table_blocks:
                            continue
                        _section_text = " ".join(
                            b.text.strip() for b in _page_result.text_blocks if b.text.strip()
                        )
                        _section_context: str | None = (
                            _section_text[:300] if _section_text else None
                        )
                        for _table_block in _page_result.table_blocks:
                            _table_result = build_table_chunk(
                                _table_block, section_context=_section_context
                            )
                            if not _table_result.text.strip():
                                _table_global_idx += 1
                                continue
                            _tbl_chunk_index = _table_chunk_base + _table_global_idx
                            _tbl_point_id = _qdrant_service.build_point_id(
                                document_id=parsed_document_id,
                                chunk_index=_tbl_chunk_index,
                                index_version=effective_index_version,
                            )
                            _tbl_db_chunk = await _document_repository.create_document_chunk(
                                session,
                                document_id=parsed_document_id,
                                page_number=_table_block.page_number,
                                chunk_index=_tbl_chunk_index,
                                text=_table_result.text,
                                token_count=max(1, len(_table_result.text) // 4),
                                qdrant_point_id=_tbl_point_id,
                                embedding_model=settings.openai_embedding_model,
                                index_version=effective_index_version,
                                chunk_hash=compute_chunk_hash(_table_result.text),
                                section_path=(
                                    f"page:{_table_block.page_number}"
                                    f":table:{_table_block.table_index}"
                                ),
                                language=document.language,
                                chunk_type="table",
                                table_metadata=_table_result.table_metadata,
                            )
                            created_chunks.append(_tbl_db_chunk)
                            _table_chunk_count += 1
                            _table_global_idx += 1
                    if _table_chunk_count > 0:
                        log_document_event(
                            event="document.pipeline.stage",
                            document_id=str(document.id),
                            request_id=request_id,
                            organization_id=resolved_organization_id,
                            user_id=resolved_user_id,
                            stage="table_chunk",
                            stage_status="completed",
                            table_chunk_count=_table_chunk_count,
                        )

                # Sentinels shared between entity and relation extraction stages (F283/F284).
                _entity_result = None
                _chunk_pairs: list[tuple[int, str]] = []
                _chunk_id_by_index: dict[int, UUID] = {}
                _page_by_index: dict[int, int | None] = {}

                # Entity extraction stage (F283): extract entities from all chunks and
                # write them to the Enterprise Graph. Failures are isolated from the
                # SQLAlchemy transaction — non-strict mode logs and continues; strict
                # mode raises DocumentPipelineTransientError to abort the pipeline.
                if (
                    False
                    and settings.enterprise_graph_enabled
                    and settings.feature_enable_entity_extraction
                ):
                    current_stage = "extract_entities"
                    _extraction_run_id = uuid4()
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
                        await _graph_service.start_extraction_run(
                            organization_id=document.organization_id,
                            document_id=document.id,
                            run_id=_extraction_run_id,
                            strategy="llm_extraction_v1",
                        )
                        _chunk_pairs = [(p.chunk_index, p.text) for p in chunks if p.text.strip()]
                        _chunk_id_by_index = {
                            p.chunk_index: c.id
                            for p, c in zip(chunks, all_created_chunks, strict=True)
                        }
                        _page_by_index = {p.chunk_index: p.page_number for p in chunks}
                        _entity_result = await _entity_extraction_service.extract_from_chunks(
                            chunks=_chunk_pairs,
                            document_language=document.language,
                            organization_id=str(document.organization_id),
                        )
                        for _item in _entity_result.entities:
                            _chunk_db_id = _chunk_id_by_index.get(_item.source_chunk_index)
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
                                _resolution_result = await _graph_service.resolve_entity(
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
                            alias_id = _entity_resolution_service.build_alias_id(
                                input_=resolution_input,
                                entity_id=_resolved_entity_id,
                                alias_name=alias_name,
                                source_document_id=str(document.id),
                                chunk_id=str(_chunk_db_id) if _chunk_db_id is not None else None,
                            )
                            await _graph_service.upsert_entity(
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
                            await _graph_service.upsert_entity_alias(
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
                                await _graph_service.link_evidence(
                                    organization_id=document.organization_id,
                                    entity_id=_resolved_entity_id,
                                    chunk_id=_chunk_db_id,
                                    source_document_id=document.id,
                                    confidence=_item.confidence,
                                    citation_text=_item.evidence_span,
                                    citation_reference=(
                                        f"{document.filename}, chunk {_item.source_chunk_index}"
                                    ),
                                    extraction_run_id=_extraction_run_id,
                                    page_number=_page_by_index.get(_item.source_chunk_index),
                                )
                        await _graph_service.finish_extraction_run(
                            organization_id=document.organization_id,
                            run_id=_extraction_run_id,
                            status="completed",
                            entity_count=len(_entity_result.entities),
                        )
                        log_document_event(
                            event="document.pipeline.stage",
                            document_id=str(document.id),
                            request_id=request_id,
                            organization_id=resolved_organization_id,
                            user_id=resolved_user_id,
                            stage="extract_entities",
                            stage_status="completed",
                            entity_count=len(_entity_result.entities),
                            batch_count=_entity_result.batch_count,
                            validation_errors=_entity_result.validation_errors,
                            llm_errors=_entity_result.llm_errors,
                        )
                        await pipeline_recorder.emit_stage(
                            stage="extract_entities",
                            stage_status="completed",
                            outputs={
                                "entity_count": len(_entity_result.entities),
                                "batch_count": _entity_result.batch_count,
                                "validation_errors": _entity_result.validation_errors,
                                "llm_errors": _entity_result.llm_errors,
                                "total_chunks": _entity_result.total_chunks,
                            },
                        )
                    except Exception as _entity_exc:
                        log_document_event(
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
                            await _graph_service.finish_extraction_run(
                                organization_id=document.organization_id,
                                run_id=_extraction_run_id,
                                status="failed",
                                error=str(_entity_exc),
                            )
                        except Exception:
                            pass
                        if settings.entity_extraction_strict_mode:
                            raise DocumentPipelineTransientError(
                                stage="extract_entities",
                                code="ENTITY_EXTRACTION_FAILED",
                                category="processing",
                                message=f"Entity extraction failed: {_entity_exc}",
                            ) from _entity_exc
                        await pipeline_recorder.emit_stage(
                            stage="extract_entities",
                            stage_status="failed",
                            error_message=str(_entity_exc),
                        )

                # Relation extraction stage (F284): extract relationships between already-
                # identified entities. Runs only when entity extraction is also enabled and
                # completed; uses the entity name→id map built above.
                if False and (
                    settings.enterprise_graph_enabled
                    and settings.feature_enable_entity_extraction
                    and settings.feature_enable_relation_extraction
                    and _entity_result is not None
                ):
                    current_stage = "extract_relations"
                    _rel_run_id = uuid4()
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
                        # Build entity name→id lookup and per-chunk entity lists from
                        # the entity extraction result.
                        _entity_name_to_id = {
                            _item.name.lower().strip(): _item.entity_id
                            for _item in _entity_result.entities
                        }
                        _entity_names_by_chunk: dict[int, list[str]] = {}
                        for _item in _entity_result.entities:
                            _entity_names_by_chunk.setdefault(_item.source_chunk_index, []).append(
                                _item.name
                            )

                        _rel_result = await _relation_extraction_service.extract_from_chunks(
                            chunks=_chunk_pairs,
                            entity_name_to_id=_entity_name_to_id,
                            entity_names_by_chunk=_entity_names_by_chunk,
                            organization_id=str(document.organization_id),
                        )
                        for _rel_item in _rel_result.relations:
                            _rel_chunk_db_id = _chunk_id_by_index.get(_rel_item.source_chunk_index)
                            _initial_status = (
                                _relation_extraction_service.compute_initial_status(
                                    _rel_item.confidence
                                )
                                if not settings.relation_extraction_review_mode
                                else "unverified"
                            )
                            await _graph_service.create_relation_with_evidence(
                                organization_id=document.organization_id,
                                from_entity_id=_rel_item.from_entity_id,
                                to_entity_id=_rel_item.to_entity_id,
                                rel_type=_rel_item.rel_type,
                                relation_id=_rel_item.relation_id,
                                citation_text=_rel_item.evidence_span,
                                citation_reference=(
                                    f"{document.filename}, chunk {_rel_item.source_chunk_index}"
                                ),
                                chunk_id=_rel_chunk_db_id,
                                source_document_id=document.id,
                                page_number=_page_by_index.get(_rel_item.source_chunk_index),
                                extraction_run_id=_rel_run_id,
                                confidence=_rel_item.confidence,
                                initial_status=_initial_status,
                            )
                        log_document_event(
                            event="document.pipeline.stage",
                            document_id=str(document.id),
                            request_id=request_id,
                            organization_id=resolved_organization_id,
                            user_id=resolved_user_id,
                            stage="extract_relations",
                            stage_status="completed",
                            relation_count=len(_rel_result.relations),
                            batch_count=_rel_result.batch_count,
                            validation_errors=_rel_result.validation_errors,
                            llm_errors=_rel_result.llm_errors,
                            skipped_unknown_entity=_rel_result.skipped_unknown_entity,
                        )
                        await pipeline_recorder.emit_stage(
                            stage="extract_relations",
                            stage_status="completed",
                            outputs={
                                "relation_count": len(_rel_result.relations),
                                "batch_count": _rel_result.batch_count,
                                "validation_errors": _rel_result.validation_errors,
                                "llm_errors": _rel_result.llm_errors,
                                "skipped_unknown_entity": _rel_result.skipped_unknown_entity,
                            },
                        )
                    except Exception as _rel_exc:
                        log_document_event(
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
                            raise DocumentPipelineTransientError(
                                stage="extract_relations",
                                code="RELATION_EXTRACTION_FAILED",
                                category="processing",
                                message=f"Relation extraction failed: {_rel_exc}",
                            ) from _rel_exc
                        await pipeline_recorder.emit_stage(
                            stage="extract_relations",
                            stage_status="failed",
                            error_message=str(_rel_exc),
                        )

                _chunk_pairs = [(p.chunk_index, p.text) for p in chunks if p.text.strip()]
                _chunk_id_by_index = {
                    p.chunk_index: c.id for p, c in zip(chunks, all_created_chunks, strict=True)
                }
                _page_by_index = {p.chunk_index: p.page_number for p in chunks}
                await _run_document_graph_extraction_async(
                    document,
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    pipeline_type=pipeline_type,
                    chunk_pairs=_chunk_pairs,
                    chunk_id_by_index=_chunk_id_by_index,
                    page_by_index=_page_by_index,
                    pipeline_recorder=pipeline_recorder,
                    clear_existing_facts=True,
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
                if _table_chunk_count > 0:
                    _chunking_config_snapshot["table_chunk_count"] = _table_chunk_count
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
                    _chunking_config_snapshot["embedding_provider_type"] = getattr(
                        embedding_result, "provider_type", None
                    )
                    _chunking_config_snapshot["embedding_vector_dimension"] = getattr(
                        embedding_result, "vector_dimension", None
                    )
                if persist_document_state:
                    if embedding_result is not None:
                        await _document_repository.update_document_embedding_metadata(
                            session,
                            document_id=parsed_document_id,
                            embedding_provider_type=getattr(
                                embedding_result, "provider_type", None
                            ),
                            embedding_vector_dimension=getattr(
                                embedding_result, "vector_dimension", None
                            ),
                        )
                    updated = await _document_repository.update_document_status(
                        session,
                        document_id=parsed_document_id,
                        status=DocumentStatus.indexed.value,
                        error_message=None,
                        page_count=len(cleaned_sections),
                        chunk_count=len(chunks) + _table_chunk_count,
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

            try:
                await _graph_service.clear_document_graph_facts(
                    organization_id=document.organization_id,
                    document_id=document.id,
                    delete_document_node=True,
                )
            except Exception as exc:
                log_document_event(
                    event="document.pipeline.stage",
                    document_id=str(document.id),
                    request_id=request_id,
                    organization_id=resolved_organization_id,
                    user_id=resolved_user_id,
                    stage="delete_graph",
                    stage_status="failed",
                    error=str(exc),
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


async def _update_document_graph_status_async(
    document_id: UUID,
    *,
    status: str,
    run_id: UUID | None = None,
) -> None:
    # Use a short lock_timeout so this never blocks indefinitely when the outer
    # pipeline session holds the documents row lock (e.g. during graph extraction).
    # If the lock can't be acquired, skip the status update rather than deadlocking.
    try:
        async with SessionLocal() as session:
            await session.execute(text("SET LOCAL lock_timeout = '3s'"))
            await _document_repository.update_document_graph_status(
                session,
                document_id=document_id,
                graph_extraction_status=status,
                graph_extraction_run_id=run_id,
            )
            await session.commit()
    except Exception:
        log_document_event(
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
    graph_run_id = uuid4()
    previous_graph_run_id = getattr(document, "graph_extraction_run_id", None)
    resolved_organization_id = organization_id or str(document.organization_id)
    resolved_user_id = user_id or str(document.uploaded_by_user_id)

    if not settings.enterprise_graph_enabled or not settings.feature_enable_entity_extraction:
        await _update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.skipped.value,
            run_id=None,
        )
        return {"entity_count": 0, "relation_count": 0}

    await _update_document_graph_status_async(
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
        await _graph_service.clear_document_graph_facts(
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
        await _graph_service.start_extraction_run(
            organization_id=document.organization_id,
            document_id=document.id,
            run_id=_extraction_run_id,
            strategy="llm_extraction_v1",
        )
        _entity_result = await _entity_extraction_service.extract_from_chunks(
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
                _resolution_result = await _graph_service.resolve_entity(
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
            alias_id = _entity_resolution_service.build_alias_id(
                input_=resolution_input,
                entity_id=_resolved_entity_id,
                alias_name=alias_name,
                source_document_id=str(document.id),
                chunk_id=str(_chunk_db_id) if _chunk_db_id is not None else None,
            )
            await _graph_service.upsert_entity(
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
            await _graph_service.upsert_entity_alias(
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
                await _graph_service.link_evidence(
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
        await _graph_service.finish_extraction_run(
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
        log_document_event(
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
        log_document_event(
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
            await _graph_service.finish_extraction_run(
                organization_id=document.organization_id,
                run_id=_extraction_run_id,
                status="failed",
                error=str(_entity_exc),
            )
        except Exception:
            pass
        if settings.entity_extraction_strict_mode:
            await _update_document_graph_status_async(
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

            _rel_result = await _relation_extraction_service.extract_from_chunks(
                chunks=_chunk_pairs,
                entity_name_to_id=_entity_name_to_id,
                entity_names_by_chunk=_entity_names_by_chunk,
                organization_id=str(document.organization_id),
            )
            for _rel_item in _rel_result.relations:
                _rel_chunk_db_id = chunk_id_by_index.get(_rel_item.source_chunk_index)
                _initial_status = (
                    _relation_extraction_service.compute_initial_status(_rel_item.confidence)
                    if not settings.relation_extraction_review_mode
                    else "unverified"
                )
                await _graph_service.create_relation_with_evidence(
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
            log_document_event(
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
            log_document_event(
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
                await _update_document_graph_status_async(
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

    await _update_document_graph_status_async(
        document.id,
        status=GraphExtractionStatus.completed.value,
        run_id=graph_run_id,
    )
    return {"entity_count": entity_count, "relation_count": relation_count}


async def _reindex_document_graph_async(
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    try:
        parsed_document_id = _parse_uuid(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc

    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(
            session, document_id=parsed_document_id
        )
        if document is None:
            raise PermanentTaskError(f"Document not found: {document_id}")
        chunks = await _document_repository.list_document_chunks(
            session,
            document_id=document.id,
            index_version=settings.document_index_version,
        )

    if document.status == DocumentStatus.deleted.value:
        raise PermanentTaskError(
            f"Cannot re-run graph extraction for deleted document: {document_id}"
        )
    if document.status == DocumentStatus.deleting.value:
        raise PermanentTaskError(
            f"Cannot re-run graph extraction while deleting document: {document_id}"
        )

    if not chunks:
        await _update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.skipped.value,
            run_id=None,
        )
        return {"document_id": document_id, "status": GraphExtractionStatus.skipped.value}

    pipeline_recorder = await PipelineRunRecorder.create(
        document_id=document_id,
        organization_id=organization_id or str(document.organization_id),
        user_id=user_id or str(document.uploaded_by_user_id),
        organization_uuid=document.organization_id,
        document_uuid=document.id,
        pipeline_type="document.graph_reindex",
        inputs={
            "request_id": request_id,
            "document_id": str(document.id),
            "filename": document.filename,
            "file_type": document.file_type,
        },
        config={
            "index_version": settings.document_index_version,
            "entity_extraction_enabled": settings.feature_enable_entity_extraction,
            "relation_extraction_enabled": settings.feature_enable_relation_extraction,
        },
    )

    try:
        result = await _run_document_graph_extraction_async(
            document,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="document.graph_reindex",
            chunk_pairs=[(chunk.chunk_index, chunk.text) for chunk in chunks if chunk.text.strip()],
            chunk_id_by_index={chunk.chunk_index: chunk.id for chunk in chunks},
            page_by_index={chunk.chunk_index: chunk.page_number for chunk in chunks},
            pipeline_recorder=pipeline_recorder,
            clear_existing_facts=True,
        )
        await pipeline_recorder.finalize_run(
            status="completed",
            outputs={
                "document_status": DocumentStatus.indexed.value,
                "graph_status": GraphExtractionStatus.completed.value,
                "chunk_count": len(chunks),
                "entity_count": result["entity_count"],
                "relation_count": result["relation_count"],
            },
        )
        return {
            "document_id": document_id,
            "status": GraphExtractionStatus.completed.value,
            "chunk_count": len(chunks),
            "entity_count": result["entity_count"],
            "relation_count": result["relation_count"],
        }
    except Exception as exc:
        details = details_from_exception(exc)
        await pipeline_recorder.fail_stage_if_open(
            stage=details.get("stage", "graph_reindex"),
            error_message=details.get("message", str(exc)),
            error_details=details,
        )
        await pipeline_recorder.finalize_run(
            status="failed",
            error_message=details.get("message", str(exc)),
            error_details=details,
            outputs={"chunk_count": len(chunks)},
        )
        await _update_document_graph_status_async(
            document.id,
            status=GraphExtractionStatus.failed.value,
            run_id=None,
        )
        raise


@celery_app.task(name="documents.graph_reindex", bind=True, base=RudixTask, ignore_result=True)
def reindex_document_graph(
    self: RudixTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str | int]:
    """Re-run graph extraction for an existing document."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")
    return _run(
        _reindex_document_graph_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )


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

    try:
        document_uuid = _parse_uuid(document_id)
    except ValueError:
        document_uuid = None
    if document_uuid is not None:
        _run(
            _update_document_graph_status_async(
                document_uuid,
                status=GraphExtractionStatus.pending.value,
                run_id=None,
            )
        )
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
    force: bool = False,
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

    try:
        document_uuid = _parse_uuid(document_id)
    except ValueError:
        document_uuid = None
    if document_uuid is not None:
        _run(
            _update_document_graph_status_async(
                document_uuid,
                status=GraphExtractionStatus.pending.value,
                run_id=None,
            )
        )
    log_document_event(
        event="document.reindex.started",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.processing.value,
        force=force,
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
        force=force,
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
            "force": force,
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
