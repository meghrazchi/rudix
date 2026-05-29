from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents.workflows import (
    delete_document_workflow,
    reindex_document_workflow,
    upload_document_workflow,
)
from app.auth.dependencies import get_current_principal, require_document_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import clamav_client as clamav_module
from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.core.logging import log_document_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DeleteDocumentResponse,
    DocumentChunkPreviewResponse,
    DocumentChunksResponse,
    DocumentDetailResponse,
    DocumentLifecycleTimelineStepResponse,
    DocumentListItemResponse,
    DocumentListResponse,
    DocumentSortBy,
    DocumentStatusResponse,
    ReindexDocumentResponse,
    SortOrder,
    UploadDocumentResponse,
)
from app.domains.documents.services.malware_scan import MalwareScanService
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.domains.pipeline.services.pipeline_graph_service import (
    canonical_pipeline_type,
    pipeline_event_status_to_node_status,
    pipeline_node_description,
    pipeline_node_label,
)
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.pipeline import PipelineEvent, PipelineRun
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.document_tasks import (
    delete_document as delete_document_task,
)
from app.workers.document_tasks import (
    process_document,
)
from app.workers.document_tasks import (
    reindex_document as reindex_document_task,
)

router = APIRouter(prefix="/documents", tags=["documents"])
document_repository = DocumentRepository()
pipeline_repository = PipelineRepository()
audit_log_service = AuditLogService()
malware_scan_service = MalwareScanService(clamav_client_provider=clamav_module.get_clamav_client)


def _principal_user_and_org(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.user_id), UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _safe_error_payload(document: Document) -> tuple[str | None, object | None]:
    error_message, error_details = decode_document_error(document.error_message)
    if document.error_message is None:
        return None, None
    if error_details is not None:
        return error_message, error_details
    # Legacy/plain errors are not exposed verbatim.
    return "Processing failed", None


def _chunk_preview_text(text: str, *, max_length: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


def _safe_log_lines(
    value: object,
    *,
    max_lines: int = 4,
    max_chars: int = 240,
) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for raw_line in value:
        line = str(raw_line).strip()
        if not line:
            continue
        if len(line) > max_chars:
            line = f"{line[: max_chars - 1].rstrip()}…"
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _duration_from_event(event: PipelineEvent) -> int | None:
    if event.duration_ms is not None and event.duration_ms >= 0:
        return event.duration_ms
    if event.started_at is None or event.completed_at is None:
        return None
    return max(int((event.completed_at - event.started_at).total_seconds() * 1000), 0)


def _timeline_status_from_event(
    event_status: str,
) -> Literal["pending", "running", "completed", "failed", "skipped"]:
    mapped_status = pipeline_event_status_to_node_status(event_status)
    if mapped_status == "running":
        return "running"
    if mapped_status == "completed":
        return "completed"
    if mapped_status == "failed":
        return "failed"
    if mapped_status == "skipped":
        return "skipped"
    return "pending"


def _is_pipeline_tables_missing_error(error: ProgrammingError) -> bool:
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if sqlstate == "42P01":
        return True
    lowered = str(error).lower()
    return (
        'relation "pipeline_runs" does not exist' in lowered
        or 'relation "pipeline_events" does not exist' in lowered
    )


def _build_lifecycle_timeline_from_pipeline(
    *,
    document: Document,
    pipeline_run: PipelineRun,
    events: list[PipelineEvent],
) -> list[DocumentLifecycleTimelineStepResponse]:
    if not events:
        return []

    ordered_node_names: list[str] = []
    grouped_events: dict[str, list[PipelineEvent]] = {}
    for event in events:
        if event.node_name not in grouped_events:
            grouped_events[event.node_name] = []
            ordered_node_names.append(event.node_name)
        grouped_events[event.node_name].append(event)

    timeline: list[DocumentLifecycleTimelineStepResponse] = []
    for node_name in ordered_node_names:
        node_events = grouped_events[node_name]
        latest_event = node_events[-1]
        started_candidates = [
            item.started_at for item in node_events if item.started_at is not None
        ]
        completed_candidates = [
            item.completed_at for item in node_events if item.completed_at is not None
        ]
        started_at = min(started_candidates) if started_candidates else latest_event.started_at
        completed_at = (
            max(completed_candidates) if completed_candidates else latest_event.completed_at
        )

        timeline.append(
            DocumentLifecycleTimelineStepResponse(
                step=node_name,
                label=pipeline_node_label(node_name),
                description=pipeline_node_description(node_name),
                status=_timeline_status_from_event(latest_event.status),
                document_id=str(document.id),
                pipeline_run_id=str(pipeline_run.id),
                pipeline_type=canonical_pipeline_type(pipeline_run.pipeline_type),
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=_duration_from_event(latest_event),
                logs=_safe_log_lines(latest_event.logs_json),
            )
        )

    return timeline


def _lifecycle_step(
    *,
    document_id: str,
    step: str,
    label: str,
    description: str,
    status: Literal["pending", "running", "completed", "failed", "skipped"],
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> DocumentLifecycleTimelineStepResponse:
    return DocumentLifecycleTimelineStepResponse(
        step=step,
        label=label,
        description=description,
        status=status,
        document_id=document_id,
        pipeline_run_id=None,
        pipeline_type=None,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=None,
        logs=[],
    )


def _build_lifecycle_timeline_from_document_state(
    *,
    document_id: str,
    document_status: str,
    created_at: datetime,
    updated_at: datetime,
    page_count: int | None,
    chunk_count: int,
) -> list[DocumentLifecycleTimelineStepResponse]:
    timeline: list[DocumentLifecycleTimelineStepResponse] = [
        _lifecycle_step(
            document_id=document_id,
            step="uploaded",
            label="Uploaded",
            description="Document metadata accepted and queued for processing.",
            status="completed",
            started_at=created_at,
            completed_at=created_at,
        ),
        _lifecycle_step(
            document_id=document_id,
            step="virus_scan",
            label="Virus scanned",
            description="Security scan completed before storage and indexing.",
            status="completed",
            started_at=created_at,
            completed_at=created_at,
        ),
    ]

    if document_status == DocumentStatus.processing.value:
        timeline.append(
            _lifecycle_step(
                document_id=document_id,
                step="processing",
                label="Processing",
                description="Extraction, chunking, and embedding generation in progress.",
                status="running",
                started_at=updated_at,
            )
        )
        return timeline

    if document_status in {
        DocumentStatus.indexed.value,
        DocumentStatus.failed.value,
        DocumentStatus.deleting.value,
        DocumentStatus.deleted.value,
    } and (page_count is None or page_count > 0):
        timeline.append(
            _lifecycle_step(
                document_id=document_id,
                step="extract",
                label="Extracted",
                description="Extract raw text and metadata from source files.",
                status="completed",
                started_at=updated_at,
                completed_at=updated_at,
            )
        )

    if chunk_count > 0:
        timeline.extend(
            [
                _lifecycle_step(
                    document_id=document_id,
                    step="chunk",
                    label="Chunked",
                    description="Split text into retrieval-sized chunks.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
                _lifecycle_step(
                    document_id=document_id,
                    step="embed",
                    label="Embedded",
                    description="Generate vector embeddings for chunks.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
                _lifecycle_step(
                    document_id=document_id,
                    step="index",
                    label="Upserted to Qdrant",
                    description="Upsert embedded chunks into vector storage.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
            ]
        )

    if document_status == DocumentStatus.indexed.value:
        timeline.extend(
            [
                _lifecycle_step(
                    document_id=document_id,
                    step="indexed",
                    label="Indexed",
                    description="Document indexing lifecycle completed.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
                _lifecycle_step(
                    document_id=document_id,
                    step="ready_for_chat",
                    label="Ready for chat",
                    description="Document is available for retrieval-backed chat queries.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
            ]
        )
    elif document_status == DocumentStatus.failed.value:
        timeline.append(
            _lifecycle_step(
                document_id=document_id,
                step="failed",
                label="Failed",
                description="Processing stopped due to a recoverable or terminal error.",
                status="failed",
                started_at=updated_at,
                completed_at=updated_at,
            )
        )
    elif document_status == DocumentStatus.deleting.value:
        timeline.append(
            _lifecycle_step(
                document_id=document_id,
                step="deleting",
                label="Deleting",
                description="Deletion queued or currently in progress.",
                status="running",
                started_at=updated_at,
            )
        )
    elif document_status == DocumentStatus.deleted.value:
        timeline.extend(
            [
                _lifecycle_step(
                    document_id=document_id,
                    step="deleting",
                    label="Deleting",
                    description="Deletion queued or currently in progress.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
                _lifecycle_step(
                    document_id=document_id,
                    step="deleted",
                    label="Deleted",
                    description="Document removed from active organization access.",
                    status="completed",
                    started_at=updated_at,
                    completed_at=updated_at,
                ),
            ]
        )

    return timeline


def _download_media_type(file_type: str) -> str:
    if file_type == "pdf":
        return "application/pdf"
    if file_type == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if file_type == "txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


@router.post("/upload", response_model=UploadDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.upload))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UploadDocumentResponse:
    request_id = _request_id_from_request(request)
    user_id, organization_id = _principal_user_and_org(principal)
    return await upload_document_workflow(
        request_id=request_id,
        file=file,
        organization_id=organization_id,
        user_id=user_id,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        malware_scan_service=malware_scan_service,
        process_document_task=process_document,
        minio_client=minio_module.get_minio_client(),
    )


@router.post("/upload-url", response_model=CreateUploadUrlResponse)
async def create_upload_url(
    payload: CreateUploadUrlRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.upload))],
) -> CreateUploadUrlResponse:
    del payload, rate_limit
    log_document_event(
        event="document.upload_url.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Upload URL generation is not implemented in scaffold.",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    sort_by: DocumentSortBy = "created_at",
    sort_order: SortOrder = "desc",
    filename_query: Annotated[str | None, Query(max_length=255)] = None,
    file_type: Annotated[str | None, Query(pattern="^(pdf|docx|txt)$")] = None,
) -> DocumentListResponse:
    _, organization_id = _principal_user_and_org(principal)

    documents = await document_repository.list_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
        file_type=file_type,
        filename_query=filename_query,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await document_repository.count_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
        file_type=file_type,
        filename_query=filename_query,
    )

    items: list[DocumentListItemResponse] = []
    for document in documents:
        chunk_count = await document_repository.count_document_chunks(
            db_session,
            document_id=document.id,
            index_version=settings.document_index_version,
        )
        safe_error_message, safe_error_details = _safe_error_payload(document)
        items.append(
            DocumentListItemResponse(
                document_id=str(document.id),
                filename=document.filename,
                file_type=document.file_type,
                status=document.status,
                page_count=document.page_count,
                chunk_count=chunk_count,
                error_message=safe_error_message,
                error_details=safe_error_details,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )

    log_document_event(
        event="document.list.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
        status_filter=status_filter.value if status_filter is not None else None,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return DocumentListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        status=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_full_text: bool = False,
) -> DocumentChunksResponse:
    del document_id
    chunks = await document_repository.list_document_chunks_paginated(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
        limit=limit,
        offset=offset,
    )
    total = await document_repository.count_document_chunks(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
    )

    items = [
        DocumentChunkPreviewResponse(
            chunk_id=str(chunk.id),
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            token_count=chunk.token_count,
            embedding_model=chunk.embedding_model,
            index_version=chunk.index_version,
            text_preview=_chunk_preview_text(chunk.text),
            text=chunk.text if include_full_text else None,
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]

    log_document_event(
        event="document.chunks.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        limit=limit,
        offset=offset,
        total=total,
        returned=len(items),
        include_full_text=include_full_text,
    )
    return DocumentChunksResponse(
        document_id=str(document.id),
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        include_full_text=include_full_text,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentDetailResponse:
    del document_id
    _, organization_id = _principal_user_and_org(principal)
    document_uuid = document.id
    document_id_text = str(document_uuid)
    filename = document.filename
    file_type = document.file_type
    document_status = document.status
    page_count = document.page_count
    checksum = document.checksum
    created_at = document.created_at
    updated_at = document.updated_at

    safe_error_message, safe_error_details = _safe_error_payload(document)
    chunk_count = await document_repository.count_document_chunks(
        db_session,
        document_id=document_uuid,
        index_version=settings.document_index_version,
    )
    lifecycle_timeline: list[DocumentLifecycleTimelineStepResponse] = []
    try:
        pipeline_run = await pipeline_repository.resolve_latest_pipeline_run(
            db_session,
            organization_id=organization_id,
            pipeline_types=["document.process", "document.reindex", "document.delete"],
            document_id=document_uuid,
        )
        if pipeline_run is not None:
            pipeline_events = await pipeline_repository.list_pipeline_events_for_run(
                db_session,
                pipeline_run_id=pipeline_run.id,
            )
            lifecycle_timeline = _build_lifecycle_timeline_from_pipeline(
                document=document,
                pipeline_run=pipeline_run,
                events=pipeline_events,
            )
    except ProgrammingError as exc:
        if not _is_pipeline_tables_missing_error(exc):
            raise
        await db_session.rollback()
        log_document_event(
            event="document.detail.timeline.unavailable",
            document_id=document_id_text,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            reason="pipeline_tables_missing",
        )
    if not lifecycle_timeline:
        lifecycle_timeline = _build_lifecycle_timeline_from_document_state(
            document_id=document_id_text,
            document_status=document_status,
            created_at=created_at,
            updated_at=updated_at,
            page_count=page_count,
            chunk_count=chunk_count,
        )
    log_document_event(
        event="document.detail.requested",
        document_id=document_id_text,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        document_status=document_status,
    )
    return DocumentDetailResponse(
        document_id=document_id_text,
        filename=filename,
        file_type=file_type,
        status=document_status,
        page_count=page_count,
        chunk_count=chunk_count,
        checksum=checksum,
        error_message=safe_error_message,
        error_details=safe_error_details,
        lifecycle_timeline=lifecycle_timeline,
        created_at=created_at,
        updated_at=updated_at,
    )


@router.get("/{document_id}/download")
async def download_document(
    request: Request,
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
) -> Response:
    del document_id
    request_id = _request_id_from_request(request)
    minio = minio_module.get_minio_client()
    if minio is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        )

    body = None
    try:
        object_response = minio.get_object(
            Bucket=document.storage_bucket,
            Key=document.storage_object_key,
        )
        body = object_response["Body"]
        content = body.read()
    except Exception as exc:
        log_document_event(
            event="document.download.failed",
            document_id=str(document.id),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document file is unavailable",
        ) from exc
    finally:
        try:
            if body is not None:
                body.close()
        except Exception:
            pass

    filename = document.filename or f"{document.id}.{document.file_type}"
    content_disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    media_type = _download_media_type(document.file_type)

    log_document_event(
        event="document.download.completed",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
        status_code=status.HTTP_200_OK,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition},
    )


@router.delete(
    "/{document_id}", response_model=DeleteDocumentResponse, status_code=status.HTTP_202_ACCEPTED
)
async def delete_document_endpoint(
    request: Request,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.delete))],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeleteDocumentResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)
    return await delete_document_workflow(
        request_id=request_id,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        document=document,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        delete_document_task=delete_document_task,
    )


@router.post(
    "/{document_id}/reindex",
    response_model=ReindexDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_document_endpoint(
    request: Request,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReindexDocumentResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)
    return await reindex_document_workflow(
        request_id=request_id,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        document=document,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        reindex_document_task=reindex_document_task,
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
) -> DocumentStatusResponse:
    del document_id
    safe_error_message, safe_error_details = _safe_error_payload(document)
    log_document_event(
        event="document.status.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        document_status=document.status,
    )
    return DocumentStatusResponse(
        document_id=str(document.id),
        status=document.status,
        error_message=safe_error_message,
        error_details=safe_error_details,
        updated_at=document.updated_at,
    )
