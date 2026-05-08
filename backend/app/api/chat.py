from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.schemas.chat import ChatMessageRequest, ChatMessageResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def create_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatMessageResponse:
    await ensure_document_ids_access(
        document_ids=payload.document_ids,
        principal=principal,
        db_session=db_session,
    )

    log_query_event(
        event="query.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Chat pipeline for session {session_id} is not implemented in scaffold.",
    )
