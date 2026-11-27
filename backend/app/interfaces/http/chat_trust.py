"""Saved-answer trust metadata route (split from ``chat.py``, R05-01).

The router has no prefix and no tags; ``chat.router`` includes it."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import _safe_http_error
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.chat.schemas.trust_metadata import AnswerTrustMetadataResponse
from app.models.enums import ChatRole, OrganizationRole

router = APIRouter()
chat_repository = default_deps.chat_repository


@router.get(
    "/messages/{message_id}/trust-metadata",
    response_model=AnswerTrustMetadataResponse,
    summary="Get answer trust metadata for a saved message",
    description=(
        "Returns the versioned trust metadata snapshot for a saved assistant message. "
        "Available after chat completion. Never returns raw prompts, chain-of-thought, "
        "ACL snapshots, or internal UUIDs. Organization-scoped and user-filtered."
    ),
)
async def get_message_trust_metadata(
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
) -> AnswerTrustMetadataResponse:
    user_id, organization_id = _principal_user_and_org(principal)

    try:
        message_uuid = UUID(message_id)
    except ValueError as exc:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="message_not_found",
            message="Message not found",
        ) from exc

    message = await chat_repository.get_message_for_user(
        db_session,
        message_id=message_uuid,
        organization_id=organization_id,
        user_id=user_id,
    )
    if message is None or message.role != ChatRole.assistant.value:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="message_not_found",
            message="Message not found",
        )

    if message.trust_metadata_json is None:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="trust_metadata_not_available",
            message="Trust metadata is not available for this message",
        )

    return AnswerTrustMetadataResponse.model_validate(message.trust_metadata_json)
