from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.feedback_review.repositories.review import FeedbackReviewRepository
from app.domains.feedback_review.schemas.review import (
    FeedbackReviewItemResponse,
    FeedbackReviewListResponse,
    TriageFeedbackRequest,
    UpdateReviewItemRequest,
)
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/feedback-review", tags=["feedback-review"])

_review_repository = FeedbackReviewRepository()
_audit_log_service = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


def _require_admin(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        user_id = UUID(principal.user_id)
        org_id = UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc
    return user_id, org_id


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {label} format",
        ) from exc


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


@router.get("", response_model=FeedbackReviewListResponse)
async def list_feedback_review_items(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    rating: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    reviewer_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewListResponse:
    _user_id, org_id = _require_admin(principal)

    reviewer_uuid: UUID | None = None
    if reviewer_id:
        reviewer_uuid = _parse_uuid(reviewer_id, "reviewer_id")

    items, total = await _review_repository.list_review_items(
        db,
        organization_id=org_id,
        status=status_filter,
        severity=severity,
        rating=rating,
        reason=reason,
        reviewer_id=reviewer_uuid,
        limit=limit,
        offset=offset,
    )

    from app.models.message_feedback import MessageFeedback
    from app.models.chat import ChatMessage
    from sqlalchemy import select

    feedback_ids = [item.feedback_id for item in items]
    fb_map: dict[UUID, MessageFeedback] = {}
    msg_map: dict[UUID, ChatMessage] = {}

    if feedback_ids:
        fb_result = await db.execute(
            select(MessageFeedback).where(MessageFeedback.id.in_(feedback_ids))
        )
        for fb in fb_result.scalars().all():
            fb_map[fb.id] = fb

        message_ids = [fb.message_id for fb in fb_map.values()]
        if message_ids:
            msg_result = await db.execute(
                select(ChatMessage).where(ChatMessage.id.in_(message_ids))
            )
            for msg in msg_result.scalars().all():
                msg_map[msg.id] = msg

    response_items = []
    for item in items:
        fb = fb_map.get(item.feedback_id)
        msg = msg_map.get(fb.message_id) if fb else None
        response_items.append(FeedbackReviewItemResponse.from_model(item, feedback=fb, message=msg))

    return FeedbackReviewListResponse(
        items=response_items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export")
async def export_feedback_review_csv(
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    rating: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> Response:
    _user_id, org_id = _require_admin(principal)
    csv_content = await _review_repository.build_csv_export(
        db,
        organization_id=org_id,
        status=status_filter,
        severity=severity,
        rating=rating,
        reason=reason,
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedback-review-queue.csv"},
    )


@router.get("/{review_id}", response_model=FeedbackReviewItemResponse)
async def get_feedback_review_item(
    review_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    _user_id, org_id = _require_admin(principal)
    review_uuid = _parse_uuid(review_id, "review_id")

    item = await _review_repository.get_review_item(
        db, review_id=review_uuid, organization_id=org_id
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")

    from app.models.message_feedback import MessageFeedback
    from app.models.chat import ChatMessage
    from sqlalchemy import select

    fb_result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.id == item.feedback_id)
    )
    fb = fb_result.scalar_one_or_none()

    msg: ChatMessage | None = None
    if fb is not None:
        msg_result = await db.execute(select(ChatMessage).where(ChatMessage.id == fb.message_id))
        msg = msg_result.scalar_one_or_none()

    return FeedbackReviewItemResponse.from_model(item, feedback=fb, message=msg)


@router.post(
    "/feedback/{feedback_id}/triage",
    response_model=FeedbackReviewItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def triage_feedback(
    feedback_id: str,
    payload: TriageFeedbackRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    user_id, org_id = _require_admin(principal)
    feedback_uuid = _parse_uuid(feedback_id, "feedback_id")

    from app.models.message_feedback import MessageFeedback
    from sqlalchemy import select

    fb_result = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.id == feedback_uuid,
            MessageFeedback.organization_id == org_id,
        )
    )
    fb = fb_result.scalar_one_or_none()
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    item, created = await _review_repository.get_or_create_review_item(
        db,
        feedback_id=feedback_uuid,
        organization_id=org_id,
        reviewer_id=user_id,
        severity=payload.severity,
        reviewer_notes=payload.reviewer_notes,
    )

    await _audit_log_service.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="feedback.review.triaged",
        resource_type="feedback_review_item",
        resource_id=item.id,
        request_id=_request_id(request),
        metadata={
            "feedback_id": str(feedback_uuid),
            "severity": payload.severity,
            "created": created,
        },
    )
    await db.commit()
    await db.refresh(item)

    from app.models.chat import ChatMessage

    msg_result = await db.execute(select(ChatMessage).where(ChatMessage.id == fb.message_id))
    msg = msg_result.scalar_one_or_none()
    return FeedbackReviewItemResponse.from_model(item, feedback=fb, message=msg)


@router.patch("/{review_id}", response_model=FeedbackReviewItemResponse)
async def update_feedback_review_item(
    review_id: str,
    payload: UpdateReviewItemRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    user_id, org_id = _require_admin(principal)
    review_uuid = _parse_uuid(review_id, "review_id")

    linked_eval_uuid: UUID | None = None
    if payload.linked_eval_question_id:
        linked_eval_uuid = _parse_uuid(payload.linked_eval_question_id, "linked_eval_question_id")

    linked_doc_uuid: UUID | None = None
    if payload.linked_document_id:
        linked_doc_uuid = _parse_uuid(payload.linked_document_id, "linked_document_id")

    item = await _review_repository.update_review_item(
        db,
        review_id=review_uuid,
        organization_id=org_id,
        reviewer_id=user_id,
        status=payload.status,
        severity=payload.severity,
        reviewer_notes=payload.reviewer_notes,
        linked_eval_question_id=linked_eval_uuid,
        linked_document_id=linked_doc_uuid,
        clear_linked_eval=payload.linked_eval_question_id == "",
        clear_linked_document=payload.linked_document_id == "",
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")

    await _audit_log_service.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="feedback.review.updated",
        resource_type="feedback_review_item",
        resource_id=review_uuid,
        request_id=_request_id(request),
        metadata={"status": payload.status, "severity": payload.severity},
    )
    await db.commit()
    await db.refresh(item)

    from app.models.message_feedback import MessageFeedback
    from app.models.chat import ChatMessage
    from sqlalchemy import select

    fb_result = await db.execute(
        select(MessageFeedback).where(MessageFeedback.id == item.feedback_id)
    )
    fb = fb_result.scalar_one_or_none()
    msg: ChatMessage | None = None
    if fb is not None:
        msg_result = await db.execute(select(ChatMessage).where(ChatMessage.id == fb.message_id))
        msg = msg_result.scalar_one_or_none()

    return FeedbackReviewItemResponse.from_model(item, feedback=fb, message=msg)
