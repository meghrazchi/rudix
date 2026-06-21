"""HTTP interface — verified answers and curated knowledge cards (F255)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.verified_answers.repositories.verified_answers import VerifiedAnswerRepository
from app.domains.verified_answers.schemas.verified_answers import (
    ApproveRequest,
    CreateFromChatRequest,
    CreateVerifiedAnswerRequest,
    CitationResponse,
    RejectRequest,
    UpdateVerifiedAnswerRequest,
    VerifiedAnswerListResponse,
    VerifiedAnswerResponse,
    VerifiedAnswerVersionListResponse,
    VersionResponse,
)
from app.models.enums import OrganizationRole
from app.models.verified_answer import VerifiedAnswer

router = APIRouter(prefix="/verified-answers", tags=["verified-answers"])

_repo = VerifiedAnswerRepository()
_audit = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_REVIEWER_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.reviewer.value,
)
_READ_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
    OrganizationRole.reviewer.value,
    OrganizationRole.developer.value,
)
_WRITE_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.reviewer.value,
)


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid user context"
        ) from exc


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _is_stale(answer: VerifiedAnswer) -> bool:
    today = datetime.now(timezone.utc).date()
    if answer.expiry_date and today > answer.expiry_date:
        return True
    if answer.review_date and today > answer.review_date and answer.status == "published":
        return True
    return False


def _citation_to_response(cit) -> CitationResponse:
    return CitationResponse(
        citation_id=str(cit.id),
        document_id=str(cit.document_id),
        chunk_id=str(cit.chunk_id) if cit.chunk_id else None,
        text_snippet=cit.text_snippet,
        page_number=cit.page_number,
        citation_order=cit.citation_order,
    )


def _to_response(answer: VerifiedAnswer) -> VerifiedAnswerResponse:
    return VerifiedAnswerResponse(
        answer_id=str(answer.id),
        organization_id=str(answer.organization_id),
        title=answer.title,
        question=answer.question,
        answer_text=answer.answer_text,
        status=answer.status,  # type: ignore[arg-type]
        tags=answer.tags,
        collection_id=str(answer.collection_id) if answer.collection_id else None,
        owner_id=str(answer.owner_id) if answer.owner_id else None,
        requires_citations=answer.requires_citations,
        review_date=answer.review_date,
        expiry_date=answer.expiry_date,
        approved_by_id=str(answer.approved_by_id) if answer.approved_by_id else None,
        approved_at=answer.approved_at,
        published_at=answer.published_at,
        rejection_note=answer.rejection_note,
        source_message_id=str(answer.source_message_id) if answer.source_message_id else None,
        created_by_id=str(answer.created_by_id) if answer.created_by_id else None,
        is_stale=_is_stale(answer),
        citations=[_citation_to_response(c) for c in (answer.citations or [])],
        created_at=answer.created_at,
        updated_at=answer.updated_at,
    )


def _version_to_response(v) -> VersionResponse:
    return VersionResponse(
        version_id=str(v.id),
        version_number=v.version_number,
        title=v.title,
        question=v.question,
        answer_text=v.answer_text,
        tags=v.tags,
        change_reason=v.change_reason,
        changed_by_id=str(v.changed_by_id) if v.changed_by_id else None,
        created_at=v.created_at,
    )


def _guard_citations(answer: VerifiedAnswer) -> None:
    """Raise if citations are required but none are attached."""
    if answer.requires_citations and not answer.citations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This knowledge card requires at least one citation. "
            "Add a citation or have an admin waive the requirement.",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=VerifiedAnswerResponse, status_code=status.HTTP_201_CREATED)
async def create_verified_answer(
    request: Request,
    payload: CreateVerifiedAnswerRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    collection_uuid: UUID | None = None
    if payload.collection_id:
        collection_uuid = _parse_uuid(payload.collection_id, "Collection")

    answer = await _repo.create(
        db,
        organization_id=org_id,
        title=payload.title,
        question=payload.question,
        answer_text=payload.answer_text,
        tags=payload.tags,
        collection_id=collection_uuid,
        owner_id=user_id,
        requires_citations=payload.requires_citations,
        review_date=payload.review_date,
        expiry_date=payload.expiry_date,
        source_message_id=None,
        created_by_id=user_id,
    )

    if payload.citations:
        await _repo.replace_citations(db, answer, [c.model_dump() for c in payload.citations])
        await db.refresh(answer)

    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.created",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title},
    )
    await db.commit()
    return _to_response(answer)


@router.get("", response_model=VerifiedAnswerListResponse)
async def list_verified_answers(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    collection_id: Annotated[str | None, Query()] = None,
    owner_id: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VerifiedAnswerListResponse:
    org_id = _org_id(principal)
    col_uuid = _parse_uuid(collection_id, "Collection") if collection_id else None
    owner_uuid = _parse_uuid(owner_id, "User") if owner_id else None

    items = await _repo.list(
        db,
        organization_id=org_id,
        status=status_filter,
        collection_id=col_uuid,
        owner_id=owner_uuid,
        query=query,
        limit=limit,
        offset=offset,
    )
    total = await _repo.count(
        db,
        organization_id=org_id,
        status=status_filter,
        collection_id=col_uuid,
        owner_id=owner_uuid,
        query=query,
    )
    return VerifiedAnswerListResponse(
        items=[_to_response(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{answer_id}", response_model=VerifiedAnswerResponse)
async def get_verified_answer(
    answer_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    return _to_response(answer)


@router.patch("/{answer_id}", response_model=VerifiedAnswerResponse)
async def update_verified_answer(
    answer_id: str,
    request: Request,
    payload: UpdateVerifiedAnswerRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    if answer.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot edit an archived knowledge card"
        )

    collection_uuid: UUID | None = None
    if payload.collection_id:
        collection_uuid = _parse_uuid(payload.collection_id, "Collection")

    await _repo.update_content(
        db,
        answer,
        title=payload.title,
        question=payload.question,
        answer_text=payload.answer_text,
        tags=payload.tags,
        collection_id=collection_uuid,
        requires_citations=payload.requires_citations,
        review_date=payload.review_date,
        expiry_date=payload.expiry_date,
        change_reason=payload.change_reason,
        changed_by_id=user_id,
    )

    if payload.citations is not None:
        await _repo.replace_citations(db, answer, [c.model_dump() for c in payload.citations])

    # If card was previously approved/published, revert to draft on edit.
    if answer.status in ("approved", "published"):
        await _repo.set_status(db, answer, "draft")

    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.updated",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title, "change_reason": payload.change_reason},
    )
    await db.commit()
    return _to_response(answer)


@router.delete("/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_verified_answer(
    answer_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )

    answer_id_copy = answer.id
    title = answer.title
    await _repo.archive(db, answer)
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.archived",
        resource_type="verified_answer",
        resource_id=answer_id_copy,
        request_id=_request_id(request),
        metadata={"title": title},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Workflow transitions
# ---------------------------------------------------------------------------


@router.post("/{answer_id}/submit-for-review", response_model=VerifiedAnswerResponse)
async def submit_for_review(
    answer_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    if answer.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft knowledge cards can be submitted for review",
        )
    _guard_citations(answer)

    await _repo.set_status(db, answer, "pending_review")
    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.submitted_for_review",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title},
    )
    await db.commit()
    return _to_response(answer)


@router.post("/{answer_id}/approve", response_model=VerifiedAnswerResponse)
async def approve_verified_answer(
    answer_id: str,
    request: Request,
    payload: ApproveRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_REVIEWER_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    if answer.status != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only cards in pending_review status can be approved",
        )
    _guard_citations(answer)

    await _repo.approve(db, answer, approved_by_id=user_id, note=payload.note)
    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.approved",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title},
    )
    await db.commit()
    return _to_response(answer)


@router.post("/{answer_id}/reject", response_model=VerifiedAnswerResponse)
async def reject_verified_answer(
    answer_id: str,
    request: Request,
    payload: RejectRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_REVIEWER_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    if answer.status not in ("pending_review", "approved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending_review or approved cards can be rejected",
        )

    await _repo.reject(db, answer, rejected_by_id=user_id, note=payload.note)
    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.rejected",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title, "note": payload.note},
    )
    await db.commit()
    return _to_response(answer)


@router.post("/{answer_id}/publish", response_model=VerifiedAnswerResponse)
async def publish_verified_answer(
    answer_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    if answer.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only approved cards can be published",
        )
    _guard_citations(answer)

    await _repo.publish(db, answer)
    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.published",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title},
    )
    await db.commit()
    return _to_response(answer)


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


@router.get("/{answer_id}/versions", response_model=VerifiedAnswerVersionListResponse)
async def list_versions(
    answer_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerVersionListResponse:
    org_id = _org_id(principal)
    answer_uuid = _parse_uuid(answer_id, "Verified answer")
    # Verify the card belongs to this org.
    answer = await _repo.get(db, answer_id=answer_uuid, organization_id=org_id)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verified answer not found"
        )
    versions = await _repo.list_versions(db, answer_id=answer_uuid, organization_id=org_id)
    return VerifiedAnswerVersionListResponse(
        items=[_version_to_response(v) for v in versions],
        total=len(versions),
    )


# ---------------------------------------------------------------------------
# Create from chat message
# ---------------------------------------------------------------------------


@router.post(
    "/from-message/{message_id}",
    response_model=VerifiedAnswerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_chat_message(
    message_id: str,
    request: Request,
    payload: CreateFromChatRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedAnswerResponse:
    """Promote an assistant chat message into a draft knowledge card.

    The message's answer text and its attached citations are copied to the
    new card. The caller can supply a title and optional question override.
    """
    from app.models.chat import ChatMessage
    from app.models.citation import Citation

    org_id = _org_id(principal)
    user_id = _user_id(principal)
    msg_uuid = _parse_uuid(message_id, "Chat message")
    collection_uuid: UUID | None = None
    if payload.collection_id:
        collection_uuid = _parse_uuid(payload.collection_id, "Collection")

    # Load the chat message within this org context.
    from sqlalchemy import select as sa_select

    msg_result = await db.execute(sa_select(ChatMessage).where(ChatMessage.id == msg_uuid))
    msg = msg_result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat message not found")

    answer_text: str = getattr(msg, "content", "") or ""

    # Load citations attached to this message.
    cit_result = await db.execute(sa_select(Citation).where(Citation.chat_message_id == msg_uuid))
    raw_citations = list(cit_result.scalars().all())

    answer = await _repo.create(
        db,
        organization_id=org_id,
        title=payload.title,
        question=payload.question or answer_text[:200],
        answer_text=answer_text,
        tags=payload.tags,
        collection_id=collection_uuid,
        owner_id=user_id,
        requires_citations=len(raw_citations) > 0,
        review_date=payload.review_date,
        expiry_date=payload.expiry_date,
        source_message_id=msg_uuid,
        created_by_id=user_id,
    )

    if raw_citations:
        citation_dicts = [
            {
                "document_id": str(c.document_id),
                "chunk_id": str(c.chunk_id) if getattr(c, "chunk_id", None) else None,
                "text_snippet": getattr(c, "text_snippet", None),
                "page_number": getattr(c, "page_number", None),
                "citation_order": idx,
            }
            for idx, c in enumerate(raw_citations)
        ]
        await _repo.replace_citations(db, answer, citation_dicts)

    await db.commit()
    await db.refresh(answer)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="verified_answer.created_from_chat",
        resource_type="verified_answer",
        resource_id=answer.id,
        request_id=_request_id(request),
        metadata={"title": answer.title, "source_message_id": message_id},
    )
    await db.commit()
    return _to_response(answer)


# ---------------------------------------------------------------------------
# Retrieval — surface verified answers for a chat query
# ---------------------------------------------------------------------------


@router.get("/search/match", response_model=VerifiedAnswerListResponse)
async def search_verified_answers(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[str, Query(min_length=1, max_length=512)],
    collection_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
) -> VerifiedAnswerListResponse:
    """Find published knowledge cards that closely match a query string.

    Used by the chat pipeline to surface verified answers above generated results.
    """
    org_id = _org_id(principal)
    col_uuid = _parse_uuid(collection_id, "Collection") if collection_id else None

    items = await _repo.find_published_match(
        db,
        organization_id=org_id,
        query=query,
        collection_id=col_uuid,
        limit=limit,
    )
    return VerifiedAnswerListResponse(
        items=[_to_response(a) for a in items],
        total=len(items),
        limit=limit,
        offset=0,
    )
