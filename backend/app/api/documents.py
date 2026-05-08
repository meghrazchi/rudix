from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal, require_document_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.logging import log_document_event
from app.db.session import get_db_session
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.documents import DocumentRepository
from app.schemas.documents import (
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentStatusResponse,
    UploadDocumentResponse,
)
from app.services.upload_validation import validate_upload
from app.workers.document_tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])
document_repository = DocumentRepository()


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


def _object_key(
    *,
    organization_id: UUID,
    user_id: UUID,
    document_id: UUID,
    extension: str,
) -> str:
    return f"uploads/{organization_id}/{user_id}/{document_id}.{extension}"


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
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    try:
        content = await file.read(max_size_bytes + 1)
    finally:
        await file.close()

    try:
        validated = validate_upload(
            filename=file.filename or "",
            content_type=file.content_type,
            content=content,
            max_size_bytes=max_size_bytes,
        )
    except OverflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb} MB",
        ) from exc
    except ValueError as exc:
        message = str(exc)
        if message in {"unsupported file extension", "unsupported mime type"}:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc

    user_id, organization_id = _principal_user_and_org(principal)
    document_id = uuid4()
    object_key = _object_key(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        extension=validated.extension,
    )

    minio = minio_module.minio_client
    if minio is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        )

    try:
        minio.put_object(
            Bucket=settings.minio_bucket,
            Key=object_key,
            Body=content,
            ContentType=validated.content_type,
            ContentLength=validated.file_size_bytes,
        )
    except Exception as exc:
        log_document_event(
            event="document.upload.failed",
            organization_id=str(organization_id),
            user_id=str(user_id),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload storage operation failed",
        ) from exc

    try:
        document = await document_repository.create_document(
            db_session,
            document_id=document_id,
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=validated.normalized_filename,
            file_type=validated.extension,
            storage_bucket=settings.minio_bucket,
            storage_object_key=object_key,
            checksum=validated.checksum_sha256,
            status=DocumentStatus.uploaded.value,
        )
        await db_session.commit()
        await db_session.refresh(document)
    except Exception as exc:
        await db_session.rollback()
        delete_method = getattr(minio, "delete_object", None)
        if callable(delete_method):
            try:
                delete_method(Bucket=settings.minio_bucket, Key=object_key)
            except Exception:
                pass
        log_document_event(
            event="document.upload.metadata_failed",
            organization_id=str(organization_id),
            user_id=str(user_id),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist document metadata",
        ) from exc

    log_document_event(
        event="document.upload.accepted",
        document_id=str(document.id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        request_id=request.headers.get("x-request-id"),
        status_code=status.HTTP_201_CREATED,
        file_type=validated.extension,
        file_size_bytes=validated.file_size_bytes,
    )

    request_id = request.headers.get("x-request-id")
    try:
        task_result = process_document.delay(
            str(document.id),
            request_id=request_id,
            organization_id=str(organization_id),
            user_id=str(user_id),
        )
    except Exception as exc:
        log_document_event(
            event="document.processing.enqueue_failed",
            document_id=str(document.id),
            organization_id=str(organization_id),
            user_id=str(user_id),
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document uploaded but could not be queued for processing",
        ) from exc

    log_document_event(
        event="document.processing.queued",
        document_id=str(document.id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        request_id=request_id,
        task_id=str(task_result.id),
        status_code=status.HTTP_201_CREATED,
    )

    return UploadDocumentResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=DocumentStatus.uploaded.value,
        queue_status="queued",
        checksum=validated.checksum_sha256,
        message="Document uploaded and queued for processing.",
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


@router.get("/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
) -> DocumentStatusResponse:
    log_document_event(
        event="document.status.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Document status retrieval for {document_id} is not implemented in scaffold.",
    )
