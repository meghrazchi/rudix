"""Session share-link routes and the shared session page (split from ``chat.py``).

The router has no prefix and no tags; ``chat.router`` includes it."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.message_citations import load_message_citations
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.request_helpers import (
    _principal_user_and_org,
    _request_id_from_request,
)
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.domains.chat.repositories.share import ChatShareRepository
from app.domains.chat.schemas.chat import ChatSessionMessageResponse
from app.domains.chat.schemas.share import (
    ChatShareListResponse,
    ChatShareResponse,
    CreateChatShareRequest,
    SharedSessionResponse,
)
from app.domains.chat.services.confidence_calibration import _confidence_category_from_score
from app.models.enums import OrganizationRole

router = APIRouter()
chat_repository = default_deps.chat_repository
audit_log_service = default_deps.audit_log_service


share_repository = ChatShareRepository()
_MAX_ACTIVE_SHARES_PER_SESSION = 10


# ---------------------------------------------------------------------------
# Share endpoints
# ---------------------------------------------------------------------------


def _to_share_response(share: "ChatShare") -> ChatShareResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.models.chat_share import ChatShare as _ChatShare  # noqa: F401

    return ChatShareResponse(
        share_id=str(share.id),
        session_id=str(share.chat_session_id),
        token=share.token,
        created_at=share.created_at,
        expires_at=share.expires_at,
        is_revoked=share.is_revoked,
        shared_by_user_id=str(share.shared_by_user_id),
    )


@router.post(
    "/sessions/{session_id}/shares",
    response_model=ChatShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_share(
    session_id: str,
    payload: CreateChatShareRequest,
    request: Request,
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
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatShareResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    active_count = await share_repository.count_active_chat_shares(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if active_count >= _MAX_ACTIVE_SHARES_PER_SESSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum of {_MAX_ACTIVE_SHARES_PER_SESSION} active share links per session reached.",
        )

    expires_at: datetime | None = None
    if payload.expires_in_hours is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(hours=payload.expires_in_hours)

    token = secrets.token_urlsafe(32)
    share = await share_repository.create_chat_share(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        shared_by_user_id=user_id,
        token=token,
        expires_at=expires_at,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.session.shared",
        resource_type="chat_session",
        resource_id=chat_session_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db_session.commit()
    await db_session.refresh(share)

    log_query_event(
        event="chat.session.shared",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_201_CREATED,
    )
    return _to_share_response(share)


@router.get("/sessions/{session_id}/shares", response_model=ChatShareListResponse)
async def list_chat_shares(
    session_id: str,
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
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatShareListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    shares = await share_repository.list_active_chat_shares(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    items = [_to_share_response(s) for s in shares]
    return ChatShareListResponse(items=items, total=len(items))


@router.delete(
    "/sessions/{session_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_chat_share(
    session_id: str,
    share_id: str,
    request: Request,
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
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        chat_session_id = UUID(session_id)
        share_uuid = UUID(share_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Share not found"
        ) from exc

    revoked = await share_repository.revoke_chat_share(
        db_session,
        share_id=share_uuid,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.session.share.revoked",
        resource_type="chat_session",
        resource_id=chat_session_id,
        request_id=request_id,
        metadata={"share_id": share_id},
    )
    await db_session.commit()

    log_query_event(
        event="chat.session.share.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/shared/{token}", response_model=SharedSessionResponse)
async def get_shared_session(
    token: str,
    request: Request,
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
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SharedSessionResponse:
    _, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    share = await share_repository.get_chat_share_by_token(
        db_session,
        token=token,
        organization_id=organization_id,
    )
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    from sqlalchemy import select as _select

    from app.models.chat import ChatSession as _ChatSession

    result = await db_session.execute(
        _select(_ChatSession).where(_ChatSession.id == share.chat_session_id)
    )
    chat_session = result.scalar_one_or_none()
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    messages_orm = await chat_repository.list_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
        limit=500,
        offset=0,
    )
    total_messages = await chat_repository.count_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
    )

    # Shared views have never carried source provenance; keep that (no ``decorate``).
    shared_citations = await load_message_citations(
        db_session,
        messages=messages_orm,
        organization_id=organization_id,
        repository=chat_repository,
    )
    items = [
        ChatSessionMessageResponse(
            message_id=str(message.id),
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_category=_confidence_category_from_score(message.confidence_score),
            citations=shared_citations.get(message.id, []),
            created_at=message.created_at,
        )
        for message in messages_orm
    ]

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=principal.user_id,
        action="chat.session.share.viewed",
        resource_type="chat_session",
        resource_id=chat_session.id,
        request_id=request_id,
        metadata={"share_id": str(share.id), "share_owner_user_id": str(share.shared_by_user_id)},
    )
    await db_session.commit()

    log_query_event(
        event="chat.session.share.viewed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(chat_session.id),
        status_code=status.HTTP_200_OK,
    )
    return SharedSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        shared_at=share.created_at,
        messages=items,
        total_messages=total_messages,
    )
