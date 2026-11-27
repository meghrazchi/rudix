"""Chat session routes: sessions, stats, messages (split from ``chat.py``, R05-01).

The router has no prefix and no tags; ``chat.router`` includes it."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.message_citations import load_message_citations
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.domains.chat.repositories.chat import (
    MESSAGE_SORT_NAME,
    SESSION_SORT_NAME,
    message_sort_key,
    session_sort_key,
)
from app.domains.chat.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionListResponse,
    ChatSessionMessageListResponse,
    ChatSessionMessageResponse,
    ChatSessionResponse,
    ChatStatsResponse,
    CreateChatSessionRequest,
    UpdateChatSessionRequest,
)
from app.domains.chat.services.citation_enrichment import _with_provenance
from app.domains.chat.services.confidence_calibration import _confidence_category_from_score
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.shared.pagination import encode_cursor, resolve_page_request, split_page

router = APIRouter()
chat_repository = default_deps.chat_repository
_source_provenance_service = default_deps.source_provenance_service
# Every session route admits the four organisation roles (the pre-split annotation).
_ChatMember = Annotated[
    AuthenticatedPrincipal,
    Depends(
        require_roles(
            OrganizationRole.owner.value,
            OrganizationRole.admin.value,
            OrganizationRole.member.value,
            OrganizationRole.viewer.value,
        )
    ),
]


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    payload: CreateChatSessionRequest,
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    title = payload.title.strip() if payload.title is not None else None

    chat_session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        title=title,
    )
    await db_session.commit()
    await db_session.refresh(chat_session)

    log_query_event(
        event="chat.session.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(chat_session.id),
        status_code=status.HTTP_201_CREATED,
    )
    return ChatSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        message_count=0,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=255)] = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    include_total: bool | None = None,
) -> ChatSessionListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    normalized_search = search.strip() if search and search.strip() else None
    page = resolve_page_request(
        cursor=cursor, offset=offset, include_total=include_total, sort_name=SESSION_SORT_NAME
    )
    sessions, has_more = split_page(
        await chat_repository.list_chat_sessions(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            limit=limit + 1,
            offset=offset,
            search=normalized_search,
            keyset=page.keyset,
        ),
        limit,
    )
    total = (
        await chat_repository.count_chat_sessions(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            search=normalized_search,
        )
        if page.include_total
        else None
    )
    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[session.id for session in sessions],
    )

    items = [
        ChatSessionResponse(
            session_id=str(chat_session.id),
            title=chat_session.title,
            message_count=message_counts.get(chat_session.id, 0),
            created_at=chat_session.created_at,
            updated_at=chat_session.updated_at,
        )
        for chat_session in sessions
    ]

    log_query_event(
        event="chat.session.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return ChatSessionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=(
            encode_cursor(SESSION_SORT_NAME, session_sort_key(sessions[-1])) if has_more else None
        ),
    )


@router.get("/stats", response_model=ChatStatsResponse)
async def get_chat_stats(
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatStatsResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    total_sessions = await chat_repository.count_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    questions_asked = await chat_repository.count_user_questions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    return ChatStatsResponse(
        questions_asked=questions_asked,
        total_sessions=total_sessions,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionResponse:
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

    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[chat_session.id],
    )

    log_query_event(
        event="chat.session.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_200_OK,
    )
    return ChatSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        message_count=message_counts.get(chat_session.id, 0),
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.get("/sessions/{session_id}/messages", response_model=ChatSessionMessageListResponse)
async def list_chat_session_messages(
    session_id: str,
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    include_total: bool | None = None,
) -> ChatSessionMessageListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    page = resolve_page_request(
        cursor=cursor, offset=offset, include_total=include_total, sort_name=MESSAGE_SORT_NAME
    )
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

    messages, has_more = split_page(
        await chat_repository.list_chat_messages(
            db_session,
            chat_session_id=chat_session.id,
            limit=limit + 1,
            offset=offset,
            keyset=page.keyset,
        ),
        limit,
    )
    total = (
        await chat_repository.count_chat_messages(
            db_session,
            chat_session_id=chat_session.id,
        )
        if page.include_total
        else None
    )

    citations_by_message = await load_message_citations(
        db_session,
        messages=messages,
        organization_id=organization_id,
        decorate=_with_provenance,
        repository=chat_repository,
        provenance_service=_source_provenance_service,
    )
    items = [
        ChatSessionMessageResponse(
            message_id=str(message.id),
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_category=_confidence_category_from_score(message.confidence_score),
            citations=citations_by_message.get(message.id, []),
            created_at=message.created_at,
        )
        for message in messages
    ]

    log_query_event(
        event="chat.session.messages.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return ChatSessionMessageListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=(
            encode_cursor(MESSAGE_SORT_NAME, message_sort_key(messages[-1])) if has_more else None
        ),
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    payload: UpdateChatSessionRequest,
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionResponse:
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

    title = payload.title.strip() if payload.title is not None else None
    chat_session = await chat_repository.update_chat_session_title(
        db_session,
        chat_session=chat_session,
        title=title,
    )
    await db_session.commit()
    await db_session.refresh(chat_session)

    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[chat_session.id],
    )

    log_query_event(
        event="chat.session.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_200_OK,
    )
    return ChatSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        message_count=message_counts.get(chat_session.id, 0),
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: str,
    principal: _ChatMember,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    deleted = await chat_repository.delete_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    await db_session.commit()

    log_query_event(
        event="chat.session.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse, deprecated=True)
async def create_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    principal: _ChatMember,
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
