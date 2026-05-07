from fastapi import APIRouter, HTTPException, status

from app.core.logging import log_document_event
from app.schemas.documents import (
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DocumentStatusResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload-url", response_model=CreateUploadUrlResponse)
async def create_upload_url(_: CreateUploadUrlRequest) -> CreateUploadUrlResponse:
    log_document_event(
        event="document.upload_url.requested",
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Upload URL generation is not implemented in scaffold.",
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(document_id: str) -> DocumentStatusResponse:
    log_document_event(
        event="document.status.requested",
        document_id=document_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Document status retrieval for {document_id} is not implemented in scaffold.",
    )
