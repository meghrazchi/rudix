from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_principal, require_document_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_document_event
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.schemas.documents import (
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentStatusResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


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
