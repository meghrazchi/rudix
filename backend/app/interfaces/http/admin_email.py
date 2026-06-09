"""Admin endpoints for email template preview and test-send (non-production only)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.email.repositories.email_delivery import EmailDeliveryRepository
from app.domains.email.repositories.notification_preferences import (
    NotificationPreferencesRepository,
)
from app.domains.email.services.template_service import render_email_template
from app.models.enums import EmailEventType, OrganizationRole

router = APIRouter(prefix="/admin/email", tags=["admin-email"])
_delivery_repo = EmailDeliveryRepository()
_prefs_repo = NotificationPreferencesRepository()
_logger = get_logger("events.admin_email")

_ADMIN_ROLES = [OrganizationRole.owner, OrganizationRole.admin]


class EmailPreviewRequest(BaseModel):
    template_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9_]+\.html$",
    )
    context: dict[str, Any] = Field(default_factory=dict)


class EmailPreviewResponse(BaseModel):
    html: str
    template_name: str


class TestSendRequest(BaseModel):
    recipient_email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    event_type: EmailEventType
    template_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9_]+\.html$",
    )
    subject: str = Field(min_length=1, max_length=512, default="[Test] Rudix Email Preview")
    context: dict[str, Any] = Field(default_factory=dict)


class TestSendResponse(BaseModel):
    sent: bool
    provider: str
    detail: str | None = None


class NotificationPreferenceItem(BaseModel):
    event_type: str
    email_enabled: bool


class NotificationPreferencesResponse(BaseModel):
    items: list[NotificationPreferenceItem]


class UpdatePreferenceRequest(BaseModel):
    event_type: EmailEventType
    email_enabled: bool


@router.post(
    "/preview",
    response_model=EmailPreviewResponse,
    summary="Render an email template to HTML (admin only)",
)
async def preview_email_template(
    payload: EmailPreviewRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
) -> EmailPreviewResponse:
    base_context: dict[str, Any] = {
        "subject": "Preview",
        "frontend_base_url": str(settings.frontend_base_url).rstrip("/"),
        "org_name": "Rudix",
        **payload.context,
    }
    try:
        html = render_email_template(payload.template_name, base_context)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template render error: {exc}",
        )
    return EmailPreviewResponse(html=html, template_name=payload.template_name)


@router.post(
    "/test-send",
    response_model=TestSendResponse,
    summary="Send a test email (non-production only, admin only)",
)
async def test_send_email(
    payload: TestSendRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TestSendResponse:
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="test-send is not available in production",
        )

    from app.domains.email.providers.factory import build_email_provider
    from app.domains.email.providers.base import EmailMessage

    organization_id = UUID(principal.organization_id)  # type: ignore[arg-type]
    user_id = UUID(principal.user_id)

    full_context: dict[str, Any] = {
        "subject": payload.subject,
        "frontend_base_url": str(settings.frontend_base_url).rstrip("/"),
        "org_name": "Rudix",
        **payload.context,
    }
    try:
        html_body = render_email_template(payload.template_name, full_context)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template render error: {exc}",
        )

    provider = build_email_provider()
    message = EmailMessage(
        to_address=str(payload.recipient_email),
        subject=payload.subject,
        html_body=html_body,
        from_address=settings.email_from_address,
        from_name=settings.email_from_name,
        reply_to=settings.email_reply_to,
    )
    result = await provider.send(message)

    log_id = await _delivery_repo.create_log(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        event_type=payload.event_type,
        recipient_email=str(payload.recipient_email),
        subject=payload.subject,
        provider=provider.provider_name,
    )
    from app.models.enums import EmailDeliveryStatus

    await _delivery_repo.update_status(
        db_session,
        log_id=log_id,
        status=EmailDeliveryStatus.sent if result.success else EmailDeliveryStatus.failed,
        provider_message_id=result.provider_message_id,
        error_detail=result.error_detail,
    )
    await db_session.commit()

    _logger.info(
        "admin.email.test_send",
        sent=result.success,
        provider=provider.provider_name,
        to=str(payload.recipient_email),
        user_id=principal.user_id,
        organization_id=principal.organization_id,
    )

    return TestSendResponse(
        sent=result.success,
        provider=provider.provider_name,
        detail=result.error_detail,
    )


@router.get(
    "/delivery-logs",
    summary="List email delivery logs (admin only)",
)
async def list_delivery_logs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    organization_id = UUID(principal.organization_id)  # type: ignore[arg-type]
    logs = await _delivery_repo.list_logs(
        db_session,
        organization_id=organization_id,
        limit=min(limit, 200),
        offset=offset,
    )
    total = await _delivery_repo.count_logs(db_session, organization_id=organization_id)
    return {
        "items": [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "recipient_email": log.recipient_email,
                "subject": log.subject,
                "provider": log.provider,
                "status": log.status,
                "attempt_count": log.attempt_count,
                "provider_message_id": log.provider_message_id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/preferences/me",
    response_model=NotificationPreferencesResponse,
    summary="Get current user's email notification preferences",
)
async def get_my_preferences(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*[r for r in OrganizationRole]))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationPreferencesResponse:
    organization_id = UUID(principal.organization_id)  # type: ignore[arg-type]
    user_id = UUID(principal.user_id)
    prefs = await _prefs_repo.get_preferences(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    saved = {p.event_type: p.email_enabled for p in prefs}
    items = [
        NotificationPreferenceItem(
            event_type=event_type.value,
            email_enabled=saved.get(event_type.value, True),
        )
        for event_type in EmailEventType
    ]
    return NotificationPreferencesResponse(items=items)


@router.put(
    "/preferences/me",
    response_model=NotificationPreferenceItem,
    summary="Update a single email notification preference",
)
async def update_my_preference(
    payload: UpdatePreferenceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*[r for r in OrganizationRole]))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationPreferenceItem:
    from app.domains.email.services.email_service import _MANDATORY_EVENT_TYPES

    if payload.event_type in _MANDATORY_EVENT_TYPES and not payload.email_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot opt out of mandatory event type: {payload.event_type.value}",
        )

    organization_id = UUID(principal.organization_id)  # type: ignore[arg-type]
    user_id = UUID(principal.user_id)
    pref = await _prefs_repo.upsert_preference(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        event_type=payload.event_type,
        email_enabled=payload.email_enabled,
    )
    await db_session.commit()
    return NotificationPreferenceItem(
        event_type=pref.event_type,
        email_enabled=pref.email_enabled,
    )
