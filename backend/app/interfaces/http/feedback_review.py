from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.feedback_review.repositories.review import FeedbackReviewRepository
from app.domains.feedback_review.schemas.review import (
    ConvertToEvalCaseRequest,
    ConvertToEvalCaseResponse,
    FeedbackCategoryMetric,
    FeedbackMetricsResponse,
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
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
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

    from sqlalchemy import select

    from app.models.chat import ChatMessage
    from app.models.message_feedback import MessageFeedback

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
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
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


@router.get("/metrics", response_model=FeedbackMetricsResponse)
async def get_feedback_metrics(
    days: int = Query(default=30, ge=1, le=365),
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackMetricsResponse:
    _user_id, org_id = _require_admin(principal)
    data = await _review_repository.get_feedback_metrics(db, organization_id=org_id, days=days)
    return FeedbackMetricsResponse(
        period_days=data["period_days"],
        total_feedback=data["total_feedback"],
        categories=[
            FeedbackCategoryMetric(
                category=c["category"],
                count=c["count"],
                avg_confidence_score=c["avg_confidence_score"],
            )
            for c in data["categories"]
        ],
    )


@router.get("/{review_id}", response_model=FeedbackReviewItemResponse)
async def get_feedback_review_item(
    review_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    _user_id, org_id = _require_admin(principal)
    review_uuid = _parse_uuid(review_id, "review_id")

    item = await _review_repository.get_review_item(
        db, review_id=review_uuid, organization_id=org_id
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")

    from sqlalchemy import select

    from app.models.chat import ChatMessage
    from app.models.message_feedback import MessageFeedback

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
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    user_id, org_id = _require_admin(principal)
    feedback_uuid = _parse_uuid(feedback_id, "feedback_id")

    from sqlalchemy import select

    from app.models.message_feedback import MessageFeedback

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
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
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

    from sqlalchemy import select

    from app.models.chat import ChatMessage
    from app.models.message_feedback import MessageFeedback

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
    "/{review_id}/convert-to-eval",
    response_model=ConvertToEvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_review_item_to_eval_case(
    review_id: str,
    payload: ConvertToEvalCaseRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ConvertToEvalCaseResponse:
    from uuid import UUID as _UUID

    from sqlalchemy import select as _select

    from app.domains.chat.repositories.feedback import FeedbackRepository as _FeedbackRepo
    from app.domains.evaluations.repositories.evaluations import (
        EvaluationRepository as _EvalRepo,
    )
    from app.models.evaluation import EvaluationSet as _EvalSet
    from app.models.feedback_review_item import FeedbackReviewItem as _ReviewItem
    from app.models.message_feedback import MessageFeedback as _MsgFeedback

    user_id, org_id = _require_admin(principal)
    review_uuid = _parse_uuid(review_id, "review_id")

    try:
        eval_set_id = _UUID(payload.evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid evaluation_set_id format",
        ) from exc

    review_result = await db.execute(
        _select(_ReviewItem).where(
            _ReviewItem.id == review_uuid,
            _ReviewItem.organization_id == org_id,
        )
    )
    item = review_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")

    eval_set_result = await db.execute(
        _select(_EvalSet).where(
            _EvalSet.id == eval_set_id,
            _EvalSet.organization_id == org_id,
        )
    )
    eval_set = eval_set_result.scalar_one_or_none()
    if eval_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    fb_result = await db.execute(_select(_MsgFeedback).where(_MsgFeedback.id == item.feedback_id))
    fb = fb_result.scalar_one_or_none()
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    # Derive question text: prefer captured question_text, fall back to message content
    question_text = fb.question_text
    if not question_text:
        from app.models.chat import ChatMessage as _ChatMsg

        msg_result = await db.execute(_select(_ChatMsg).where(_ChatMsg.id == fb.message_id))
        msg = msg_result.scalar_one_or_none()
        if msg and msg.content:
            question_text = str(msg.content).strip()

    if not question_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No question text available for this feedback item",
        )

    eval_repo = _EvalRepo()
    existing_texts = await eval_repo.get_existing_question_texts(db, evaluation_set_id=eval_set_id)
    already_existed = question_text.lower() in existing_texts

    if already_existed:
        from sqlalchemy import func as _func

        from app.models.evaluation import EvaluationQuestion as _EvalQ

        existing_result = await db.execute(
            _select(_EvalQ).where(
                _EvalQ.evaluation_set_id == eval_set_id,
                _func.lower(_EvalQ.question) == question_text.lower(),
            )
        )
        existing_q = existing_result.scalars().first()
        eval_question_id = str(existing_q.id) if existing_q else ""
    else:
        metadata: dict = {
            "source": "feedback",
            "feedback_id": str(item.feedback_id),
            "review_id": str(item.id),
            "category": fb.category,
            "model_name": fb.model_name,
        }
        if fb.citations_json:
            metadata["citations"] = fb.citations_json
        if fb.retrieval_diagnostics_json:
            metadata["retrieval_diagnostics"] = fb.retrieval_diagnostics_json
        if getattr(fb, "trace_id", None):
            metadata["trace_id"] = fb.trace_id
        if getattr(fb, "selected_citation_ids", None):
            metadata["selected_citation_ids"] = fb.selected_citation_ids

        question = await eval_repo.create_evaluation_question(
            db,
            evaluation_set_id=eval_set_id,
            question=question_text,
            expected_answer=fb.answer_text or None,
            difficulty=payload.default_difficulty,
            owner_id=user_id,
            metadata=metadata,
        )
        eval_question_id = str(question.id)

        fb_repo = _FeedbackRepo()
        await fb_repo.mark_converted(db, feedback_id=item.feedback_id, eval_question_id=question.id)

    from datetime import datetime as _dt
    from uuid import UUID as _UUID2

    eval_q_uuid = _UUID2(eval_question_id) if eval_question_id else None
    item.status = "eval_created"
    item.linked_eval_question_id = eval_q_uuid
    item.resolved_at = _dt.now(tz=UTC)
    if payload.reviewer_notes:
        item.reviewer_notes = payload.reviewer_notes
    db.add(item)

    await _audit_log_service.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="feedback.review.converted_to_eval",
        resource_type="feedback_review_item",
        resource_id=review_uuid,
        request_id=_request_id(request),
        metadata={
            "evaluation_set_id": payload.evaluation_set_id,
            "evaluation_question_id": eval_question_id,
            "already_existed": already_existed,
        },
    )
    await db.commit()

    return ConvertToEvalCaseResponse(
        review_id=str(item.id),
        evaluation_set_id=payload.evaluation_set_id,
        evaluation_question_id=eval_question_id,
        question=question_text,
        already_existed=already_existed,
    )


@router.post("/feedback/{feedback_id}/redact", response_model=FeedbackReviewItemResponse)
async def redact_feedback_diagnostics(
    feedback_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))] = ...,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> FeedbackReviewItemResponse:
    from sqlalchemy import select as _select

    from app.domains.chat.repositories.feedback import FeedbackRepository as _FeedbackRepo
    from app.models.chat import ChatMessage as _ChatMsg
    from app.models.feedback_review_item import FeedbackReviewItem as _ReviewItem

    user_id, org_id = _require_admin(principal)
    feedback_uuid = _parse_uuid(feedback_id, "feedback_id")

    fb_repo = _FeedbackRepo()
    fb = await fb_repo.redact_feedback(db, feedback_id=feedback_uuid, organization_id=org_id)
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    await _audit_log_service.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="feedback.diagnostics.redacted",
        resource_type="message_feedback",
        resource_id=feedback_uuid,
        request_id=_request_id(request),
        metadata={},
    )
    await db.commit()
    await db.refresh(fb)

    review_result = await db.execute(
        _select(_ReviewItem).where(_ReviewItem.feedback_id == feedback_uuid)
    )
    item = review_result.scalar_one_or_none()

    msg: _ChatMsg | None = None
    if item is not None:
        msg_result = await db.execute(_select(_ChatMsg).where(_ChatMsg.id == fb.message_id))
        msg = msg_result.scalar_one_or_none()

    if item is None:
        return FeedbackReviewItemResponse.from_model_feedback_only(fb)

    return FeedbackReviewItemResponse.from_model(item, feedback=fb, message=msg)
