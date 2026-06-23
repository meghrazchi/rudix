from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents.workflows import (
    bulk_delete_documents_workflow,
    delete_document_workflow,
    reindex_document_workflow,
    upload_document_workflow,
)
from app.auth.authorization_service import AuthorizationService
from app.auth.dependencies import (
    get_current_principal,
    require_document_policy_access,
    require_roles,
)
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import (
    build_document_resource_contexts_batch,
    get_subject_accessible_collection_ids,
)
from app.clients import clamav_client as clamav_module
from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.core.logging import log_document_event
from app.db.session import get_db_session
from app.domains.admin.schemas.chunking_profiles import ReindexWithProfileRequest
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.chunking_profile_service import ChunkingProfileService
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.services.source_freshness_service import (
    DocumentTrustData,
    SourceFreshnessService,
)
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    BulkDeleteDocumentsRequest,
    BulkDeleteDocumentsResponse,
    CitationPreviewResponse,
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DeleteDocumentResponse,
    DocumentChunkingAdaptiveSignalsResponse,
    DocumentChunkingDiagnosticsResponse,
    DocumentChunkPreviewResponse,
    DocumentChunksResponse,
    DocumentChunkTokenDistributionResponse,
    DocumentCollectionSummary,
    DocumentDetailResponse,
    DocumentLifecycleTimelineStepResponse,
    DocumentListItemResponse,
    DocumentListResponse,
    DocumentSortBy,
    DocumentStatusResponse,
    DocumentVersionListResponse,
    DocumentVersionResponse,
    ReindexDocumentGraphResponse,
    ReindexDocumentResponse,
    SortOrder,
    UploadDocumentMetadata,
    UploadDocumentResponse,
    _parse_tags_string,
)
from app.domains.documents.services.malware_scan import MalwareScanService
from app.domains.documents.services.version_service import get_document_versions
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.domains.pipeline.services.pipeline_graph_service import (
    canonical_pipeline_type,
    pipeline_event_status_to_node_status,
    pipeline_node_description,
    pipeline_node_label,
)
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service
from app.models.collection import Collection, CollectionDocument
from app.models.authorization import SourceAclMapping
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import DocumentReviewStatus, DocumentStatus, OrganizationRole
from app.models.pipeline import PipelineEvent, PipelineRun
from app.models.user import User
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
from app.workers.document_tasks import (
    reindex_document_graph as reindex_document_graph_task,
)

router = APIRouter(prefix="/documents", tags=["documents"])
document_repository = DocumentRepository()
chat_repository = ChatRepository()
pipeline_repository = PipelineRepository()
audit_log_service = AuditLogService()
malware_scan_service = MalwareScanService(clamav_client_provider=clamav_module.get_clamav_client)
_chunking_profile_service = ChunkingProfileService()
_authorization_service = AuthorizationService()
_source_provenance_service = SourceProvenanceService()
_source_freshness_service = SourceFreshnessService()
_ADMIN_ROLES: frozenset[str] = frozenset(
    {OrganizationRole.owner.value, OrganizationRole.admin.value}
)


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


def _citation_preview_error(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
) -> HTTPException:
    detail: dict[str, str] = {
        "code": code,
        "message": message,
    }
    if request_id:
        detail["request_id"] = request_id
    return HTTPException(status_code=status_code, detail=detail)


def _document_preview_url(*, document_id: str, chunk_id: str, citation_id: str) -> str:
    base_url = str(settings.frontend_base_url).rstrip("/")
    return (
        f"{base_url}/documents/{quote(document_id, safe='')}"
        f"?chunk_id={quote(chunk_id, safe='')}"
        f"&citation={quote(citation_id, safe='')}"
    )


async def _connector_source_link_allowed(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    connection_id: UUID | None,
    source_visibility: str | None,
) -> bool:
    if connection_id is None:
        return False
    if source_visibility == "org_wide":
        return True
    result = await db_session.execute(
        select(SourceAclMapping.id).where(
            SourceAclMapping.organization_id == organization_id,
            SourceAclMapping.connector_connection_id == connection_id,
            SourceAclMapping.user_id == user_id,
            SourceAclMapping.principal_type == "user",
            SourceAclMapping.acl_effect == "allow",
            SourceAclMapping.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


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


def _build_chunking_diagnostics(
    *,
    file_type: str,
    chunking_strategy: str | None,
    chunking_profile_version: str | None,
    chunking_config_snapshot: dict[str, object] | None,
    token_distribution: dict[str, int | float] | None,
) -> DocumentChunkingDiagnosticsResponse | None:
    snapshot = chunking_config_snapshot if isinstance(chunking_config_snapshot, dict) else None
    if chunking_strategy is None and chunking_profile_version is None and snapshot is None:
        return None

    adaptive_signals = None
    raw_signals = snapshot.get("adaptive_signals") if snapshot else None
    if isinstance(raw_signals, dict):
        adaptive_signals = DocumentChunkingAdaptiveSignalsResponse(
            file_type=str(raw_signals.get("file_type") or file_type),
            page_count=int(raw_signals.get("page_count") or 0),
            total_token_count=int(raw_signals.get("total_token_count") or 0),
            ocr_applied=bool(raw_signals.get("ocr_applied", False)),
            heading_density=(
                float(raw_signals["heading_density"])
                if raw_signals.get("heading_density") is not None
                else None
            ),
            avg_chars_per_page=(
                float(raw_signals["avg_chars_per_page"])
                if raw_signals.get("avg_chars_per_page") is not None
                else None
            ),
            avg_paragraph_tokens=(
                float(raw_signals["avg_paragraph_tokens"])
                if raw_signals.get("avg_paragraph_tokens") is not None
                else None
            ),
        )

    distribution_model = (
        DocumentChunkTokenDistributionResponse(**token_distribution)
        if token_distribution is not None
        else None
    )

    return DocumentChunkingDiagnosticsResponse(
        strategy=chunking_strategy,
        selected_strategy=(
            str(snapshot.get("adaptive_selected_strategy"))
            if snapshot and snapshot.get("adaptive_selected_strategy")
            else chunking_strategy
        ),
        profile_version=chunking_profile_version,
        profile_source=(
            str(snapshot.get("profile_source"))
            if snapshot and snapshot.get("profile_source")
            else None
        ),
        chunk_size_tokens=(
            int(snapshot.get("chunk_size_tokens"))
            if snapshot and snapshot.get("chunk_size_tokens") is not None
            else None
        ),
        chunk_overlap_tokens=(
            int(snapshot.get("chunk_overlap_tokens"))
            if snapshot and snapshot.get("chunk_overlap_tokens") is not None
            else None
        ),
        embedding_model=(
            str(snapshot.get("embedding_model"))
            if snapshot and snapshot.get("embedding_model")
            else None
        ),
        index_version=(
            str(snapshot.get("index_version"))
            if snapshot and snapshot.get("index_version")
            else None
        ),
        embedding_provider_type=(
            str(snapshot.get("embedding_provider_type"))
            if snapshot and snapshot.get("embedding_provider_type")
            else None
        ),
        embedding_vector_dimension=(
            int(snapshot.get("embedding_vector_dimension"))
            if snapshot and snapshot.get("embedding_vector_dimension") is not None
            else None
        ),
        ocr_applied=(
            bool(snapshot.get("ocr_applied"))
            if snapshot and snapshot.get("ocr_applied") is not None
            else None
        ),
        hierarchical_mode=bool(snapshot.get("hierarchical_mode", False)) if snapshot else False,
        parent_chunk_count=(
            int(snapshot.get("parent_chunk_count"))
            if snapshot and snapshot.get("parent_chunk_count") is not None
            else None
        ),
        child_chunk_count=(
            int(snapshot.get("child_chunk_count"))
            if snapshot and snapshot.get("child_chunk_count") is not None
            else None
        ),
        reason_codes=(
            [str(code) for code in snapshot.get("adaptive_reason_codes", [])]
            if snapshot and isinstance(snapshot.get("adaptive_reason_codes"), list)
            else []
        ),
        adaptive_signals=adaptive_signals,
        token_distribution=distribution_model,
    )


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

        safe_outputs = (
            latest_event.outputs_json if isinstance(latest_event.outputs_json, dict) else None
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
                outputs=safe_outputs,
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
    collection_id: Annotated[str | None, Form()] = None,
    source: Annotated[str | None, Form(max_length=512)] = None,
    language: Annotated[str | None, Form(max_length=32)] = None,
    retention_class: Annotated[str | None, Form(max_length=64)] = None,
    notes: Annotated[str | None, Form(max_length=4096)] = None,
    tags: Annotated[str | None, Form()] = None,
) -> UploadDocumentResponse:
    request_id = _request_id_from_request(request)
    user_id, organization_id = _principal_user_and_org(principal)

    try:
        upload_metadata = UploadDocumentMetadata(
            collection_id=collection_id or None,
            source=source or None,
            language=language or None,
            retention_class=retention_class or None,
            notes=notes or None,
            tags=_parse_tags_string(tags),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return await upload_document_workflow(
        request_id=request_id,
        file=file,
        organization_id=organization_id,
        user_id=user_id,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        malware_scan_service=malware_scan_service,
        plan_enforcement_service=plan_enforcement_service,
        process_document_task=process_document,
        minio_client=minio_module.get_minio_client(),
        upload_metadata=upload_metadata,
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
    freshness_filter: Annotated[DocumentReviewStatus | None, Query(alias="freshness")] = None,
    sort_by: DocumentSortBy = "created_at",
    sort_order: SortOrder = "desc",
    filename_query: Annotated[str | None, Query(max_length=255)] = None,
    file_type: Annotated[str | None, Query(pattern="^(pdf|docx|txt)$")] = None,
    language: Annotated[str | None, Query(max_length=32)] = None,
) -> DocumentListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    user_roles = list(principal.roles or [])

    documents = await document_repository.list_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
        review_status=freshness_filter.value if freshness_filter is not None else None,
        file_type=file_type,
        filename_query=filename_query,
        language=language,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await document_repository.count_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
        review_status=freshness_filter.value if freshness_filter is not None else None,
        file_type=file_type,
        filename_query=filename_query,
        language=language,
    )

    # Policy filtering — admins bypass via rule 5; others are filtered here.
    if not _ADMIN_ROLES.intersection(user_roles):
        accessible_collection_ids = await get_subject_accessible_collection_ids(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
        )
        resource_contexts = await build_document_resource_contexts_batch(
            db_session,
            documents=documents,
            organization_id=organization_id,
            subject_accessible_collection_ids=accessible_collection_ids,
        )
        accessible_ids = {
            ctx.resource_id
            for ctx in await _authorization_service.filter_accessible_resources(
                principal, Action.list, resource_contexts, db_session
            )
        }
        documents = [d for d in documents if str(d.id) in accessible_ids]
        total = len(documents)

    # Batch-fetch collection memberships for all documents in one query.
    doc_ids = [doc.id for doc in documents]
    collections_by_doc: dict[object, list[DocumentCollectionSummary]] = {}
    source_provider_by_doc: dict[object, str] = {}
    if doc_ids:
        coll_result = await db_session.execute(
            select(CollectionDocument.document_id, Collection.id, Collection.name)
            .join(Collection, CollectionDocument.collection_id == Collection.id)
            .where(
                CollectionDocument.document_id.in_(doc_ids),
                Collection.is_archived.is_(False),
            )
            .order_by(Collection.name)
        )
        for doc_id, coll_id, coll_name in coll_result:
            collections_by_doc.setdefault(doc_id, []).append(
                DocumentCollectionSummary(collection_id=str(coll_id), name=coll_name)
            )

        # Batch-fetch connector source provider for all documents in one query.
        src_result = await db_session.execute(
            select(SourceDocument.document_id, ConnectorProvider.key)
            .join(ExternalItem, ExternalItem.id == SourceDocument.external_item_id)
            .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
            .join(ConnectorProvider, ConnectorProvider.id == ConnectorConnection.provider_id)
            .where(SourceDocument.document_id.in_(doc_ids))
            .distinct(SourceDocument.document_id)
        )
        for doc_id, provider_key in src_result:
            source_provider_by_doc[doc_id] = provider_key

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
                graph_extraction_status=document.graph_extraction_status,
                page_count=document.page_count,
                chunk_count=chunk_count,
                error_message=safe_error_message,
                error_details=safe_error_details,
                source=document.source,
                source_provider=source_provider_by_doc.get(document.id),
                language=document.language,
                retention_class=document.retention_class,
                notes=document.notes,
                tags=_parse_tags_string(document.tags),
                collections=collections_by_doc.get(document.id, []),
                review_status=document.review_status,
                review_owner_id=str(document.review_owner_id)
                if document.review_owner_id is not None
                else None,
                review_due_date=document.review_due_date,
                expiry_date=document.expiry_date,
                trust_level=document.trust_level,
                trust_status=document.trust_status,
                version_label=document.version_label,
                review_date=document.review_date,
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
        freshness_filter=(freshness_filter.value if freshness_filter is not None else None),
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return DocumentListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        status=status_filter,
        freshness=freshness_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
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
            section_path=chunk.section_path,
            language=chunk.language,
            chunk_level=chunk.chunk_level,
            child_count=chunk.child_count,
            source_start_offset=chunk.source_start_offset,
            source_end_offset=chunk.source_end_offset,
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


@router.get(
    "/{document_id}/citations/{citation_id}/preview",
    response_model=CitationPreviewResponse,
)
async def get_citation_preview(
    request: Request,
    document_id: str,
    citation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CitationPreviewResponse:
    del document_id
    request_id = _request_id_from_request(request)
    user_id, _ = _principal_user_and_org(principal)

    try:
        citation_uuid = UUID(citation_id)
    except ValueError as exc:
        raise _citation_preview_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="citation_not_found",
            message="Citation not found.",
            request_id=request_id,
        ) from exc

    citation = await chat_repository.get_citation_for_document(
        db_session,
        citation_id=citation_uuid,
        document_id=document.id,
    )
    if citation is None:
        raise _citation_preview_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="citation_not_found",
            message="Citation not found.",
            request_id=request_id,
        )

    deleted_document_statuses = {
        DocumentStatus.delete_requested.value,
        DocumentStatus.deleting.value,
        DocumentStatus.deleted.value,
        DocumentStatus.retained_by_policy.value,
    }
    if document.status in deleted_document_statuses:
        raise _citation_preview_error(
            status_code=status.HTTP_410_GONE,
            code="citation_deleted",
            message="Citation source has been deleted.",
            request_id=request_id,
        )

    indexed_document_statuses = {
        DocumentStatus.indexed.value,
        DocumentStatus.ocr_applied.value,
    }
    if document.status not in indexed_document_statuses:
        raise _citation_preview_error(
            status_code=status.HTTP_409_CONFLICT,
            code="citation_not_indexed",
            message="Citation source is not yet indexed.",
            request_id=request_id,
        )

    chunk = await document_repository.get_document_chunk_by_id(
        db_session,
        document_id=document.id,
        chunk_id=citation.chunk_id,
    )
    if chunk is None:
        raise _citation_preview_error(
            status_code=status.HTTP_409_CONFLICT,
            code="citation_not_indexed",
            message="Citation source is not yet indexed.",
            request_id=request_id,
        )

    trust_data = DocumentTrustData(
        document_id=document.id,
        trust_status=document.trust_status,
        review_status=document.review_status,
        review_owner_id=document.review_owner_id,
        review_due_date=document.review_due_date,
        expiry_date=document.expiry_date,
        version_label=document.version_label,
        review_date=document.review_date,
        effective_date=document.effective_date,
        stale_after_days=document.stale_after_days,
        superseded_by_document_id=document.superseded_by_document_id,
        trust_level=document.trust_level,
        last_updated_at=document.updated_at,
    )
    freshness_state = _source_freshness_service.derive_freshness_state(trust_data)
    if freshness_state in {"stale", "expired", "deprecated"}:
        raise _citation_preview_error(
            status_code=status.HTTP_409_CONFLICT,
            code="citation_stale",
            message="Citation source is stale.",
            request_id=request_id,
        )

    source_provider = "upload"
    source_provider_label = "Uploaded file"
    source_title = document.filename
    source_key: str | None = None
    source_url: str | None = None
    source_link_allowed = False
    source_section = chunk.section_path or (
        f"Page {chunk.page_number}" if chunk.page_number is not None else None
    )
    source_last_synced_at: datetime | None = None
    source_content_hash = document.checksum
    source_sync_version: int | None = None
    source_trust_status = "uploaded"
    provenance = None

    if document.connector_external_item_id is not None:
        provenance_by_chunk_id = await _source_provenance_service.load_citation_details(
            db_session,
            organization_id=document.organization_id,
            chunk_ids=[citation.chunk_id],
        )
        provenance = provenance_by_chunk_id.get(citation.chunk_id)
        if provenance is None:
            raise _citation_preview_error(
                status_code=status.HTTP_409_CONFLICT,
                code="citation_not_indexed",
                message="Citation source is not yet indexed.",
                request_id=request_id,
            )

        source_trust_status = provenance.source_trust_status
        if source_trust_status == "revoked":
            raise _citation_preview_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="citation_unauthorized",
                message="Citation source is unavailable.",
                request_id=request_id,
            )
        if source_trust_status == "deleted":
            raise _citation_preview_error(
                status_code=status.HTTP_410_GONE,
                code="citation_deleted",
                message="Citation source has been deleted.",
                request_id=request_id,
            )
        if source_trust_status == "stale":
            raise _citation_preview_error(
                status_code=status.HTTP_409_CONFLICT,
                code="citation_stale",
                message="Citation source is stale.",
                request_id=request_id,
            )

        source_provider = provenance.provider_key or source_provider
        source_provider_label = provenance.provider_label or source_provider_label
        source_title = provenance.source_title or source_title
        source_key = provenance.source_key
        source_url = provenance.source_deep_link
        source_section = provenance.source_section or source_section
        source_last_synced_at = provenance.source_last_synced_at
        source_content_hash = provenance.source_content_hash
        source_sync_version = provenance.source_sync_version
        source_link_allowed = await _connector_source_link_allowed(
            db_session,
            organization_id=document.organization_id,
            user_id=user_id,
            connection_id=provenance.connector_connection_id,
            source_visibility=provenance.source_visibility,
        )

    document_last_indexed_at: datetime | None = None
    if document.current_version_id is not None:
        current_version = await db_session.get(DocumentVersion, document.current_version_id)
        if current_version is not None:
            document_last_indexed_at = current_version.indexed_at

    uploader = None
    if document.uploaded_by_user_id is not None:
        uploader = await db_session.get(User, document.uploaded_by_user_id)

    highlight_start_offset = citation.start_offset
    highlight_end_offset = citation.end_offset
    if highlight_start_offset is None and citation.text_snippet:
        highlight_start_offset = 0
    if highlight_end_offset is None and citation.text_snippet:
        highlight_end_offset = len(citation.text_snippet)

    snippet = (
        citation.text_snippet.strip() if citation.text_snippet else _chunk_preview_text(chunk.text)
    )
    preview = CitationPreviewResponse(
        citation_id=str(citation.id),
        document_id=str(document.id),
        chunk_id=str(chunk.id),
        filename=document.filename,
        document_title=document.filename,
        document_type=document.file_type,
        document_owner_id=str(document.uploaded_by_user_id)
        if document.uploaded_by_user_id is not None
        else None,
        document_owner_email=uploader.email if uploader is not None else None,
        document_owner_display_name=uploader.display_name if uploader is not None else None,
        document_version_label=document.version_label,
        document_last_updated_at=document.updated_at,
        document_last_indexed_at=document_last_indexed_at,
        page_number=citation.page_number or chunk.page_number,
        chunk_index=chunk.chunk_index,
        section_path=chunk.section_path,
        source_section=source_section,
        source_provider=source_provider,
        source_provider_label=source_provider_label,
        source_title=source_title,
        source_key=source_key,
        source_url=source_url if source_link_allowed else None,
        source_link_allowed=source_link_allowed,
        document_url=_document_preview_url(
            document_id=str(document.id),
            chunk_id=str(chunk.id),
            citation_id=str(citation.id),
        ),
        snippet=snippet,
        highlight_start_offset=highlight_start_offset,
        highlight_end_offset=highlight_end_offset,
        source_start_offset=chunk.source_start_offset,
        source_end_offset=chunk.source_end_offset,
        source_last_synced_at=source_last_synced_at,
        source_content_hash=source_content_hash,
        source_sync_version=source_sync_version,
        source_visibility=provenance.source_visibility if provenance is not None else None,
        source_trust_status=source_trust_status,
        freshness_state=freshness_state,
        doc_trust_status=document.trust_status,
        doc_review_status=document.review_status,
        doc_review_owner_id=str(document.review_owner_id)
        if document.review_owner_id is not None
        else None,
        doc_review_due_date=document.review_due_date,
        doc_expiry_date=document.expiry_date,
        doc_version_label=document.version_label,
        doc_review_date=document.review_date,
        doc_effective_date=document.effective_date,
        doc_stale_warning=freshness_state == "stale",
        doc_expired_warning=freshness_state == "expired",
        doc_is_excluded_status=freshness_state in {"deprecated", "expired"},
        doc_unreviewed_warning=freshness_state == "unreviewed",
        doc_deprecated_warning=freshness_state == "deprecated",
        doc_ocr_quality_status=document.ocr_quality_status,
        doc_ocr_low_confidence_warning=document.ocr_quality_status == "low",
        request_id=request_id,
    )

    log_document_event(
        event="document.citation_preview.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        citation_id=str(citation.id),
        chunk_id=str(chunk.id),
        request_id=request_id,
        status_code=status.HTTP_200_OK,
        source_provider=source_provider,
        source_link_allowed=source_link_allowed,
        freshness_state=freshness_state,
    )
    return preview


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentDetailResponse:
    del document_id
    user_id, organization_id = _principal_user_and_org(principal)
    document_uuid = document.id
    document_id_text = str(document_uuid)
    filename = document.filename
    file_type = document.file_type
    document_status = document.status
    graph_extraction_status = document.graph_extraction_status
    page_count = document.page_count
    checksum = document.checksum
    created_at = document.created_at
    updated_at = document.updated_at
    doc_source = document.source
    doc_language = document.language
    doc_language_confidence = document.language_confidence
    doc_language_source = document.language_source
    doc_retention_class = document.retention_class
    doc_notes = document.notes
    doc_tags = _parse_tags_string(document.tags)
    chunking_strategy = document.chunking_strategy
    chunking_profile_version = document.chunking_profile_version
    chunking_config_snapshot = (
        document.chunking_config_snapshot
        if isinstance(document.chunking_config_snapshot, dict)
        else None
    )
    doc_ocr_languages_override = document.ocr_languages_override
    doc_ocr_quality_snapshot = document.ocr_quality_snapshot
    doc_ocr_quality_status = document.ocr_quality_status
    doc_ocr_avg_confidence = document.ocr_avg_confidence
    doc_extraction_snapshot = document.extraction_snapshot
    doc_embedding_provider_type = document.embedding_provider_type
    doc_embedding_vector_dimension = document.embedding_vector_dimension
    doc_review_status = document.review_status
    doc_review_owner_id = document.review_owner_id
    doc_review_due_date = document.review_due_date
    doc_expiry_date = document.expiry_date
    doc_trust_level = document.trust_level
    doc_trust_status = document.trust_status
    doc_version_label = document.version_label
    doc_review_date = document.review_date
    doc_effective_date = document.effective_date
    doc_trusted_at = document.trusted_at
    doc_stale_after_days = document.stale_after_days
    doc_last_indexed_at: datetime | None = None
    if document.current_version_id is not None:
        current_version = await db_session.get(DocumentVersion, document.current_version_id)
        if current_version is not None:
            doc_last_indexed_at = current_version.indexed_at

    uploader = None
    if document.uploaded_by_user_id is not None:
        uploader = await db_session.get(User, document.uploaded_by_user_id)

    source_provider = None
    source_provider_label = None
    source_title = None
    source_key = None
    source_url = None
    source_link_allowed = False
    source_last_synced_at: datetime | None = None
    source_sync_version: int | None = None
    source_visibility: str | None = None
    source_trust_status: str | None = "uploaded"
    if document.connector_external_item_id is not None:
        provenance_by_doc_id = await _source_provenance_service.load_citation_details_for_documents(
            db_session,
            organization_id=document.organization_id,
            document_ids=[document.id],
        )
        provenance = provenance_by_doc_id.get(document.id)
        if provenance is not None:
            source_provider = provenance.provider_key
            source_provider_label = provenance.provider_label
            source_title = provenance.source_title
            source_key = provenance.source_key
            source_url = provenance.source_deep_link
            source_last_synced_at = provenance.source_last_synced_at
            source_sync_version = provenance.source_sync_version
            source_visibility = provenance.source_visibility
            source_trust_status = provenance.source_trust_status
            source_link_allowed = await _connector_source_link_allowed(
                db_session,
                organization_id=document.organization_id,
                user_id=user_id,
                connection_id=provenance.connector_connection_id,
                source_visibility=provenance.source_visibility,
            )

    safe_error_message, safe_error_details = _safe_error_payload(document)
    chunk_count = await document_repository.count_document_chunks(
        db_session,
        document_id=document_uuid,
        index_version=settings.document_index_version,
    )
    token_distribution = await document_repository.get_document_chunk_token_distribution(
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
        source_provider=source_provider,
        source_link_allowed=source_link_allowed,
        source_trust_status=source_trust_status,
    )
    return DocumentDetailResponse(
        document_id=document_id_text,
        filename=filename,
        file_type=file_type,
        status=document_status,
        graph_extraction_status=graph_extraction_status,
        page_count=page_count,
        chunk_count=chunk_count,
        checksum=checksum,
        error_message=safe_error_message,
        error_details=safe_error_details,
        source=doc_source,
        language=doc_language,
        language_confidence=doc_language_confidence,
        language_source=doc_language_source,
        ocr_languages_override=doc_ocr_languages_override,
        ocr_quality_snapshot=doc_ocr_quality_snapshot,
        ocr_quality_status=doc_ocr_quality_status,
        ocr_avg_confidence=doc_ocr_avg_confidence,
        extraction_snapshot=doc_extraction_snapshot,
        embedding_provider_type=doc_embedding_provider_type,
        embedding_vector_dimension=doc_embedding_vector_dimension,
        retention_class=doc_retention_class,
        notes=doc_notes,
        tags=doc_tags,
        review_status=doc_review_status,
        review_owner_id=str(doc_review_owner_id) if doc_review_owner_id is not None else None,
        review_due_date=doc_review_due_date,
        expiry_date=doc_expiry_date,
        trust_level=doc_trust_level,
        trust_status=doc_trust_status,
        version_label=doc_version_label,
        review_date=doc_review_date,
        effective_date=doc_effective_date,
        trusted_at=doc_trusted_at,
        stale_after_days=doc_stale_after_days,
        uploaded_by_user_id=str(document.uploaded_by_user_id)
        if document.uploaded_by_user_id is not None
        else None,
        uploaded_by_user_email=uploader.email if uploader is not None else None,
        uploaded_by_user_display_name=uploader.display_name if uploader is not None else None,
        source_provider=source_provider,
        source_provider_label=source_provider_label,
        source_title=source_title,
        source_key=source_key,
        source_url=source_url if source_link_allowed else None,
        source_link_allowed=source_link_allowed,
        source_last_synced_at=source_last_synced_at,
        source_sync_version=source_sync_version,
        source_visibility=source_visibility,
        source_trust_status=source_trust_status,
        document_title=filename,
        document_type=file_type,
        document_owner_id=str(document.uploaded_by_user_id)
        if document.uploaded_by_user_id is not None
        else None,
        document_owner_email=uploader.email if uploader is not None else None,
        document_owner_display_name=uploader.display_name if uploader is not None else None,
        document_version_label=doc_version_label,
        document_last_updated_at=updated_at,
        document_last_indexed_at=doc_last_indexed_at,
        chunking_diagnostics=_build_chunking_diagnostics(
            file_type=file_type,
            chunking_strategy=chunking_strategy,
            chunking_profile_version=chunking_profile_version,
            chunking_config_snapshot=chunking_config_snapshot,
            token_distribution=token_distribution,
        ),
        lifecycle_timeline=lifecycle_timeline,
        created_at=created_at,
        updated_at=updated_at,
    )


@router.get("/{document_id}/download")
async def download_document(
    request: Request,
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
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
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.delete))],
    document: Annotated[Document, Depends(require_document_policy_access(Action.delete))],
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
    "/bulk-delete",
    response_model=BulkDeleteDocumentsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def bulk_delete_documents_endpoint(
    request: Request,
    body: BulkDeleteDocumentsRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.delete))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BulkDeleteDocumentsResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)
    user_roles = list(principal.roles or [])

    # For non-admin principals, verify delete permission on every requested document.
    if not _ADMIN_ROLES.intersection(user_roles) and body.document_ids:
        from uuid import UUID as _UUID

        from app.auth.resource_context_builder import build_document_resource_contexts_batch

        accessible_collection_ids = await get_subject_accessible_collection_ids(
            db_session,
            organization_id=actor_organization_id,
            user_id=actor_user_id,
            user_roles=user_roles,
        )
        docs_to_check = []
        for doc_id_str in body.document_ids:
            try:
                doc_uuid = _UUID(doc_id_str)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
                ) from exc
            doc = await document_repository.get_document(
                db_session,
                document_id=doc_uuid,
                organization_id=actor_organization_id,
            )
            if doc is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
                )
            docs_to_check.append(doc)

        resource_contexts = await build_document_resource_contexts_batch(
            db_session,
            documents=docs_to_check,
            organization_id=actor_organization_id,
            subject_accessible_collection_ids=accessible_collection_ids,
        )
        accessible_ids = {
            ctx.resource_id
            for ctx in await _authorization_service.filter_accessible_resources(
                principal, Action.delete, resource_contexts, db_session
            )
        }
        unauthorized = [str(d.id) for d in docs_to_check if str(d.id) not in accessible_ids]
        if unauthorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to delete one or more requested documents",
            )

    return await bulk_delete_documents_workflow(
        request_id=request_id,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        document_ids=body.document_ids,
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
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    document: Annotated[Document, Depends(require_document_policy_access(Action.manage))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    body: ReindexWithProfileRequest | None = None,
) -> ReindexDocumentResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    chunking_profile_config: dict | None = None
    if body is not None:
        chunking_profile_config = (
            await _chunking_profile_service.resolve_profile_config_for_reindex(
                db_session,
                profile_id=body.chunking_profile_id,
                inline_config=body.chunking_profile_config,
                organization_id=actor_organization_id,
            )
        )
        if body.ocr_languages:
            from app.domains.documents.services.ocr_language_config import (
                iso_list_to_tesseract_string,
            )

            tesseract_str = iso_list_to_tesseract_string(body.ocr_languages)
            await document_repository.update_document_ocr_config(
                db_session,
                document_id=document.id,
                ocr_languages_override=tesseract_str,
            )

    return await reindex_document_workflow(
        request_id=request_id,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        document=document,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        reindex_document_task=reindex_document_task,
        chunking_profile_config=chunking_profile_config,
        force=body.force if body is not None else False,
    )


@router.post(
    "/{document_id}/graph/reindex",
    response_model=ReindexDocumentGraphResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_document_graph_endpoint(
    request: Request,
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    document: Annotated[Document, Depends(require_document_policy_access(Action.manage))],
) -> ReindexDocumentGraphResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)
    reindex_document_graph_task.delay(
        str(document.id),
        request_id=request_id,
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
    )
    log_document_event(
        event="document.graph_reindex.requested",
        document_id=str(document.id),
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
        status_code=status.HTTP_202_ACCEPTED,
        queue_status="queued",
    )
    return ReindexDocumentGraphResponse(
        document_id=str(document.id),
        status="pending",
        queue_status="queued",
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
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
        graph_extraction_status=document.graph_extraction_status,
        error_message=safe_error_message,
        error_details=safe_error_details,
        updated_at=document.updated_at,
    )


# ---------------------------------------------------------------------------
# Document version history (F253)
# ---------------------------------------------------------------------------


def _version_response(ver: object) -> DocumentVersionResponse:
    from app.models.document_version import DocumentVersion as _DV

    v: _DV = ver  # type: ignore[assignment]
    return DocumentVersionResponse(
        version_id=str(v.id),
        document_id=str(v.document_id),
        version_number=v.version_number,
        change_reason=v.change_reason,
        content_hash=v.content_hash,
        extraction_hash=v.extraction_hash,
        chunking_profile_snapshot=v.chunking_profile_snapshot,
        embedding_model=v.embedding_model,
        embedding_vector_dimension=v.embedding_vector_dimension,
        index_version=v.index_version,
        filename=v.filename,
        page_count=v.page_count,
        chunk_count=v.chunk_count,
        status=v.status,
        indexed_at=v.indexed_at,
        is_current=v.is_current,
        source_updated_at=v.source_updated_at,
        created_by_user_id=str(v.created_by_user_id) if v.created_by_user_id else None,
        created_at=v.created_at,
    )


@router.get(
    "/{document_id}/versions",
    response_model=DocumentVersionListResponse,
    summary="List document version history",
)
async def list_document_versions(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_policy_access(Action.view))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentVersionListResponse:
    """Return the full version history for a document, newest version first.

    Versions are scoped to the calling user's organization so cross-org leakage
    is impossible even if document_id is guessed.
    """
    del document_id
    _user_id, organization_id = _principal_user_and_org(principal)
    versions = await get_document_versions(
        db_session,
        document_id=document.id,
        organization_id=organization_id,
    )
    return DocumentVersionListResponse(
        document_id=str(document.id),
        items=[_version_response(v) for v in versions],
        total=len(versions),
    )


# ---------------------------------------------------------------------------
# Sample dataset
# ---------------------------------------------------------------------------

_SAMPLE_DOCUMENTS = [
    {
        "filename": "Rudix Quick Start Guide.pdf",
        "file_type": "pdf",
        "source": "sample-dataset",
        "notes": "Sample document — demonstrates PDF ingestion and citation extraction.",
        "page_count": 8,
        "chunk_count": 24,
    },
    {
        "filename": "Enterprise RAG Best Practices.docx",
        "file_type": "docx",
        "source": "sample-dataset",
        "notes": "Sample document — covers retrieval-augmented generation patterns for enterprise teams.",
        "page_count": 12,
        "chunk_count": 38,
    },
    {
        "filename": "Data Governance Policy Template.txt",
        "file_type": "txt",
        "source": "sample-dataset",
        "notes": "Sample document — plain-text policy template for knowledge-base governance.",
        "page_count": None,
        "chunk_count": 14,
    },
]


class LoadSampleDatasetResponse(BaseModel):
    created: int
    skipped: int
    document_ids: list[str]


@router.post(
    "/sample",
    response_model=LoadSampleDatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Load sample dataset",
)
async def load_sample_dataset(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoadSampleDatasetResponse:
    """Create pre-indexed sample documents so new workspaces can explore Rudix immediately.

    Only available when the org has sample_docs_enabled=True.  Idempotent — already-present
    sample documents (identified by source='sample-dataset') are skipped.
    """
    from app.models.organization import Organization as _Org

    user_id, organization_id = _principal_user_and_org(principal)

    result = await db_session.execute(select(_Org).where(_Org.id == organization_id))
    _org = result.scalar_one_or_none()
    if _org is None or not _org.sample_docs_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sample dataset is not enabled for this organization.",
        )

    existing = await db_session.execute(
        select(Document.filename).where(
            Document.organization_id == organization_id,
            Document.source == "sample-dataset",
        )
    )
    existing_names = {row[0] for row in existing.all()}

    created_ids: list[str] = []
    skipped = 0
    for spec in _SAMPLE_DOCUMENTS:
        if spec["filename"] in existing_names:
            skipped += 1
            continue
        doc = Document(
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=spec["filename"],
            file_type=spec["file_type"],
            storage_bucket="sample",
            storage_object_key=f"sample/{organization_id}/{spec['filename']}",
            status=DocumentStatus.indexed.value,
            source=spec["source"],
            notes=spec["notes"],
            page_count=spec["page_count"],
            chunk_count=spec["chunk_count"],
            ingestion_source="upload",
        )
        db_session.add(doc)
        await db_session.flush()
        created_ids.append(str(doc.id))

    await db_session.commit()
    return LoadSampleDatasetResponse(
        created=len(created_ids),
        skipped=skipped,
        document_ids=created_ids,
    )
