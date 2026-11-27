"""Message feedback routes (split from ``chat.py``, R05-01).

The router has no prefix and no tags; ``chat.router`` includes it."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.request_helpers import (
    _principal_user_and_org,
    _request_id_from_request,
)
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.domains.chat.schemas.feedback import (
    MessageFeedbackResponse,
    SessionFeedbackListResponse,
    SubmitFeedbackRequest,
)
from app.models.enums import OrganizationRole

router = APIRouter()
chat_repository = default_deps.chat_repository
audit_log_service = default_deps.audit_log_service


feedback_repository = FeedbackRepository()


# ---------------------------------------------------------------------------
# Feedback endpoints
# ---------------------------------------------------------------------------


def _to_feedback_response(fb: "MessageFeedback") -> MessageFeedbackResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.domains.feedback_review.schemas.review import normalize_feedback_category
    from app.models.message_feedback import MessageFeedback as _MessageFeedback  # noqa: F401

    return MessageFeedbackResponse(
        feedback_id=str(fb.id),
        message_id=str(fb.message_id),
        user_id=str(fb.user_id),
        rating=fb.rating,  # type: ignore[arg-type]
        reason=fb.reason,  # type: ignore[arg-type]
        comment=fb.comment,
        category=normalize_feedback_category(fb.category),  # type: ignore[arg-type]
        question_text=fb.question_text,
        answer_text=fb.answer_text,
        model_name=fb.model_name,
        llm_provider=(
            fb.trust_metadata_json.get("llm_provider")
            if isinstance(fb.trust_metadata_json, dict)
            else None
        ),
        rag_profile_id=str(fb.rag_profile_id) if fb.rag_profile_id else None,
        retain_until=fb.retain_until,
        redacted_at=fb.redacted_at,
        converted_to_eval_question_id=str(fb.converted_to_eval_question_id)
        if fb.converted_to_eval_question_id
        else None,
        trust_metadata=fb.trust_metadata_json if isinstance(fb.trust_metadata_json, dict) else None,
        trace_id=getattr(fb, "trace_id", None),
        selected_citation_ids=getattr(fb, "selected_citation_ids", None),
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


async def _get_assistant_message_for_org(
    db_session: AsyncSession,
    *,
    message_id: UUID,
    organization_id: UUID,
) -> "ChatMessage":  # type: ignore[name-defined]  # noqa: F821
    from sqlalchemy import select as _select

    from app.models.chat import ChatMessage as _ChatMessage
    from app.models.chat import ChatSession as _ChatSession

    result = await db_session.execute(
        _select(_ChatMessage)
        .join(_ChatSession, _ChatMessage.chat_session_id == _ChatSession.id)
        .where(
            _ChatMessage.id == message_id,
            _ChatMessage.role == "assistant",
            _ChatSession.organization_id == organization_id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.put(
    "/messages/{message_id}/feedback",
    response_model=MessageFeedbackResponse,
)
async def submit_message_feedback(
    message_id: str,
    payload: SubmitFeedbackRequest,
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
) -> MessageFeedbackResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    diag = payload.diagnostics
    rag_profile_uuid: UUID | None = None
    if diag and diag.rag_profile_id:
        try:
            rag_profile_uuid = UUID(diag.rag_profile_id)
        except ValueError:
            rag_profile_uuid = None

    feedback = await feedback_repository.upsert_feedback(
        db_session,
        message_id=msg_id,
        user_id=user_id,
        organization_id=organization_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
        category=payload.category,
        question_text=diag.question_text if diag else None,
        answer_text=diag.answer_text if diag else None,
        citations_json={"items": diag.citations} if diag and diag.citations is not None else None,
        retrieval_diagnostics_json=diag.retrieval_diagnostics if diag else None,
        model_name=diag.model_name if diag else None,
        rag_profile_id=rag_profile_uuid,
        trust_metadata_json=(
            {
                **(diag.trust_metadata or {}),
                **(
                    {"llm_provider": diag.llm_provider}
                    if diag and diag.llm_provider is not None
                    else {}
                ),
            }
            if diag
            else None
        ),
        trace_id=diag.trace_id if diag else None,
        selected_citation_ids=diag.selected_citation_ids if diag else None,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.message.feedback.submitted",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={
            "rating": payload.rating,
            "reason": payload.reason,
            "category": payload.category,
            "has_diagnostics": diag is not None,
        },
    )
    await db_session.commit()
    await db_session.refresh(feedback)
    return _to_feedback_response(feedback)


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_feedback(
    message_id: str,
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    deleted = await feedback_repository.delete_feedback(
        db_session,
        message_id=msg_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.message.feedback.deleted",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()


@router.get(
    "/sessions/{session_id}/feedback",
    response_model=SessionFeedbackListResponse,
)
async def list_session_feedback(
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
) -> SessionFeedbackListResponse:
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

    items = await feedback_repository.list_feedback_for_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    return SessionFeedbackListResponse(
        items=[_to_feedback_response(fb) for fb in items],
        total=len(items),
    )
