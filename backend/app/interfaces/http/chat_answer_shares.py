"""Per-answer share links and the shared answer page (split from ``chat.py``).

The router has no prefix and no tags; ``chat.router`` includes it."""

import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.request_helpers import (
    _principal_user_and_org,
    _request_id_from_request,
)
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import (
    PasswordHashConfig,
    build_password_hasher,
    hash_password,
    verify_password,
)
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.domains.chat.repositories.answer_share import AnswerShareRepository
from app.domains.chat.schemas.answer_share import (
    AnswerShareListResponse,
    AnswerShareResponse,
    CreateAnswerShareRequest,
    SharedAnswerCitationResponse,
    SharedAnswerResponse,
)
from app.domains.chat.services.confidence_calibration import _confidence_category_from_score
from app.interfaces.http.chat_feedback import _get_assistant_message_for_org
from app.models.enums import OrganizationRole

router = APIRouter()
chat_repository = default_deps.chat_repository
_source_freshness_service = default_deps.source_freshness_service
_document_repository_for_trust = default_deps.document_repository_for_trust
audit_log_service = default_deps.audit_log_service


answer_share_repository = AnswerShareRepository()


_answer_share_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=65536,
        time_cost=2,
        parallelism=2,
        hash_length=32,
        salt_length=16,
    )
)
_MAX_ACTIVE_ANSWER_SHARES = 10


def _to_answer_share_response(share: "AnswerShare") -> AnswerShareResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.models.answer_share import AnswerShare as _AnswerShare  # noqa: F401

    return AnswerShareResponse(
        share_id=str(share.id),
        message_id=str(share.chat_message_id),
        token=share.token,
        access_mode=share.access_mode,  # type: ignore[arg-type]
        allowed_user_ids=list(share.allowed_user_ids or []),
        has_password=share.password_hash is not None,
        created_at=share.created_at,
        expires_at=share.expires_at,
        is_revoked=share.is_revoked,
        shared_by_user_id=str(share.shared_by_user_id),
    )


@router.post(
    "/messages/{message_id}/shares",
    response_model=AnswerShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_answer_share(
    message_id: str,
    payload: CreateAnswerShareRequest,
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
) -> AnswerShareResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    # Verify the message belongs to an assistant turn in this org.
    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    active_count = await answer_share_repository.count_active_answer_shares(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if active_count >= _MAX_ACTIVE_ANSWER_SHARES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum of {_MAX_ACTIVE_ANSWER_SHARES} active share links per answer reached.",
        )

    if payload.access_mode == "specific_users" and not payload.allowed_user_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="allowed_user_ids must not be empty when access_mode is 'specific_users'.",
        )

    from datetime import UTC, timedelta

    expires_at = (
        datetime.now(tz=UTC) + timedelta(hours=payload.expires_in_hours)
        if payload.expires_in_hours is not None
        else None
    )
    password_hash = (
        hash_password(payload.password, _answer_share_password_hasher) if payload.password else None
    )
    allowed_ids = payload.allowed_user_ids if payload.access_mode == "specific_users" else None

    token = secrets.token_urlsafe(32)
    share = await answer_share_repository.create_answer_share(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        shared_by_user_id=user_id,
        token=token,
        access_mode=payload.access_mode,
        allowed_user_ids=allowed_ids,
        password_hash=password_hash,
        expires_at=expires_at,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="answer.shared",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "access_mode": payload.access_mode,
            "has_password": password_hash is not None,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db_session.commit()
    await db_session.refresh(share)

    log_query_event(
        event="answer.shared",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=message_id,
        status_code=status.HTTP_201_CREATED,
    )
    return _to_answer_share_response(share)


@router.get("/messages/{message_id}/shares", response_model=AnswerShareListResponse)
async def list_answer_shares(
    message_id: str,
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
) -> AnswerShareListResponse:
    user_id, organization_id = _principal_user_and_org(principal)

    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    shares = await answer_share_repository.list_active_answer_shares(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    items = [_to_answer_share_response(s) for s in shares]
    return AnswerShareListResponse(items=items, total=len(items))


@router.delete(
    "/messages/{message_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_answer_share(
    message_id: str,
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
        msg_id = UUID(message_id)
        share_uuid = UUID(share_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Share not found"
        ) from exc

    revoked = await answer_share_repository.revoke_answer_share(
        db_session,
        share_id=share_uuid,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="answer.share.revoked",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={"share_id": share_id},
    )
    await db_session.commit()

    log_query_event(
        event="answer.share.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=message_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/answer-shared/{token}", response_model=SharedAnswerResponse)
async def get_shared_answer(
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
    password: Annotated[str | None, Query(max_length=128)] = None,
) -> SharedAnswerResponse:
    viewer_user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    share = await answer_share_repository.get_answer_share_by_token(
        db_session,
        token=token,
        organization_id=organization_id,
    )
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    # Password check
    if share.password_hash is not None:
        if not password or not verify_password(
            password, share.password_hash, _answer_share_password_hasher
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid password is required to access this share link.",
            )

    # Specific-users access check
    if share.access_mode == "specific_users":
        allowed = [str(uid) for uid in (share.allowed_user_ids or [])]
        if str(viewer_user_id) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not in the allowed-users list for this share link.",
            )

    # Load the assistant message and its preceding user message.
    from sqlalchemy import select as _select

    from app.models.chat import ChatMessage as _ChatMessage

    assistant_result = await db_session.execute(
        _select(_ChatMessage).where(_ChatMessage.id == share.chat_message_id)
    )
    assistant_msg = assistant_result.scalar_one_or_none()
    if assistant_msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    # Find the user message that immediately precedes this assistant message in the same session.
    user_msg_result = await db_session.execute(
        _select(_ChatMessage)
        .where(
            _ChatMessage.chat_session_id == assistant_msg.chat_session_id,
            _ChatMessage.role == "user",
            _ChatMessage.created_at < assistant_msg.created_at,
        )
        .order_by(_ChatMessage.created_at.desc())
        .limit(1)
    )
    user_msg = user_msg_result.scalar_one_or_none()
    question_text = user_msg.content if user_msg else ""

    # Load citations — include snippet/filename only, not document_id/chunk_id (safety).
    citation_rows = await chat_repository.list_citations_for_message(
        db_session,
        chat_message_id=assistant_msg.id,
    )
    citation_doc_ids = [citation.document_id for citation in citation_rows]
    trust_docs = await _document_repository_for_trust.get_documents_by_ids_for_trust(
        db_session,
        document_ids=citation_doc_ids,
        organization_id=organization_id,
    )
    trust_map = _source_freshness_service.build_trust_map(trust_docs)
    trust_docs_by_id = {str(doc.id): doc for doc in trust_docs}
    safe_citations: list[SharedAnswerCitationResponse] = []
    for citation in citation_rows:
        trust = trust_map.get(str(citation.document_id))
        if trust is not None:
            effective_status = _source_freshness_service.compute_effective_trust_status(trust)
            warning = effective_status in {
                "stale",
                "needs_review",
                "unreviewed",
                "expired",
                "archived",
                "deprecated",
                "superseded",
                "draft",
            }
        else:
            effective_status = None
            warning = False

        source_doc = trust_docs_by_id.get(str(citation.document_id))
        safe_citations.append(
            SharedAnswerCitationResponse(
                document_id=str(citation.document_id),
                chunk_id=str(citation.chunk_id),
                filename=source_doc.filename if source_doc is not None else None,
                page_number=citation.page_number,
                text_snippet=citation.text_snippet,
                source_trust_status=effective_status,
                source_freshness_warning=warning,
                source_freshness_warning_reason=(
                    "Citation comes from a stale, draft, unreviewed, expired, or archived source."
                    if warning
                    else None
                ),
            )
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=viewer_user_id,
        action="answer.share.viewed",
        resource_type="chat_message",
        resource_id=share.chat_message_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "share_owner_user_id": str(share.shared_by_user_id),
            "access_mode": share.access_mode,
        },
    )
    await db_session.commit()

    log_query_event(
        event="answer.share.viewed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(share.chat_message_id),
        status_code=status.HTTP_200_OK,
    )
    return SharedAnswerResponse(
        question=question_text,
        answer=assistant_msg.content,
        citations=safe_citations,
        confidence_score=assistant_msg.confidence_score,
        confidence_category=_confidence_category_from_score(assistant_msg.confidence_score),
        shared_at=share.created_at,
        expires_at=share.expires_at,
        access_mode=share.access_mode,  # type: ignore[arg-type]
    )
