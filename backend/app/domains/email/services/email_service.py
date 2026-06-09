"""Core transactional email service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage
from app.domains.email.providers.factory import build_email_provider
from app.domains.email.repositories.email_delivery import EmailDeliveryRepository
from app.domains.email.repositories.notification_preferences import (
    NotificationPreferencesRepository,
)
from app.domains.email.services.template_service import render_email_template
from app.models.enums import EmailDeliveryStatus, EmailEventType

_logger = get_logger("email.service")

# Security-critical event types that may not be opted out of.
_MANDATORY_EVENT_TYPES: frozenset[EmailEventType] = frozenset(
    {EmailEventType.invite_received, EmailEventType.security_alert}
)


class EmailService:
    def __init__(
        self,
        provider: AbstractEmailProvider | None = None,
        delivery_repo: EmailDeliveryRepository | None = None,
        prefs_repo: NotificationPreferencesRepository | None = None,
    ) -> None:
        self._provider = provider or build_email_provider()
        self._delivery_repo = delivery_repo or EmailDeliveryRepository()
        self._prefs_repo = prefs_repo or NotificationPreferencesRepository()

    async def send_email(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        recipient_email: str,
        event_type: EmailEventType,
        template_name: str,
        template_context: dict[str, object],
        subject: str,
    ) -> bool:
        """Render, check preferences, send, and log. Returns True on successful dispatch."""
        if not settings.email_enabled:
            _logger.debug("email.service.disabled", event_type=event_type)
            return False

        if event_type not in _MANDATORY_EVENT_TYPES:
            opted_in = await self._prefs_repo.is_email_enabled(
                session,
                organization_id=organization_id,
                user_id=user_id,
                event_type=event_type,
            )
            if not opted_in:
                _logger.debug(
                    "email.service.opted_out",
                    event_type=event_type,
                    user_id=str(user_id),
                )
                return False

        full_context = {
            "subject": subject,
            "frontend_base_url": str(settings.frontend_base_url).rstrip("/"),
            "org_name": template_context.get("org_name", ""),
            **template_context,
        }
        html_body = render_email_template(template_name, full_context)

        message = EmailMessage(
            to_address=recipient_email,
            subject=subject,
            html_body=html_body,
            from_address=settings.email_from_address,
            from_name=settings.email_from_name,
            reply_to=settings.email_reply_to,
        )

        log_id = await self._delivery_repo.create_log(
            session,
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            recipient_email=recipient_email,
            subject=subject,
            provider=self._provider.provider_name,
        )
        await session.flush()

        result = await self._provider.send(message)

        await self._delivery_repo.update_status(
            session,
            log_id=log_id,
            status=(
                EmailDeliveryStatus.sent if result.success else EmailDeliveryStatus.failed
            ),
            provider_message_id=result.provider_message_id,
            error_detail=result.error_detail,
        )

        if result.success:
            _logger.info(
                "email.service.sent",
                event_type=event_type,
                provider=self._provider.provider_name,
                to=recipient_email,
            )
        else:
            _logger.warning(
                "email.service.send_failed",
                event_type=event_type,
                provider=self._provider.provider_name,
                to=recipient_email,
                error=result.error_detail,
            )

        return result.success
