"""Celery tasks for transactional email delivery."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

_logger = get_logger("worker.email")


async def _send_email_async(
    *,
    organization_id: str,
    user_id: str,
    recipient_email: str,
    event_type: str,
    template_name: str,
    template_context: dict[str, Any],
    subject: str,
) -> None:
    from app.db.session import SessionLocal
    from app.domains.email.services.email_service import EmailService
    from app.models.enums import EmailEventType

    org_uuid = UUID(organization_id)
    user_uuid = UUID(user_id)
    email_event_type = EmailEventType(event_type)

    service = EmailService()
    async with SessionLocal() as session:
        async with session.begin():
            success = await service.send_email(
                session,
                organization_id=org_uuid,
                user_id=user_uuid,
                recipient_email=recipient_email,
                event_type=email_event_type,
                template_name=template_name,
                template_context=template_context,
                subject=subject,
            )

    if not success:
        _logger.error(
            "email.send.failed",
            event_type=event_type,
            recipient_email=recipient_email,
            organization_id=organization_id,
        )
        raise TransientTaskError(
            f"Email provider returned failure for {event_type} to {recipient_email}"
        )

    _logger.info(
        "email.send.success",
        event_type=event_type,
        recipient_email=recipient_email,
        organization_id=organization_id,
    )


@celery_app.task(
    bind=True,
    base=RudixTask,
    name="app.workers.email_tasks.send_transactional_email",
    queue="email",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(TransientTaskError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    ignore_result=True,
)
def send_transactional_email(
    self: Any,
    *,
    organization_id: str,
    user_id: str,
    recipient_email: str,
    event_type: str,
    template_name: str,
    template_context: dict[str, Any],
    subject: str,
) -> None:
    """Dispatch a single transactional email. Retried on provider failure."""
    _logger.info(
        "email.task.started",
        event_type=event_type,
        recipient_email=recipient_email,
        organization_id=organization_id,
    )
    try:
        run_async(
            _send_email_async(
                organization_id=organization_id,
                user_id=user_id,
                recipient_email=recipient_email,
                event_type=event_type,
                template_name=template_name,
                template_context=template_context,
                subject=subject,
            )
        )
    except TransientTaskError:
        raise
    except Exception as exc:
        _logger.warning(
            "email.task.unexpected_error",
            event_type=event_type,
            recipient_email=recipient_email,
            organization_id=organization_id,
            error=str(exc),
            exc_info=True,
        )


def dispatch_email(
    *,
    organization_id: str,
    user_id: str,
    recipient_email: str,
    event_type: str,
    template_name: str,
    template_context: dict[str, Any],
    subject: str,
) -> None:
    """Non-blocking helper: enqueues the email task. Silently swallows dispatch errors."""
    from app.core.config import settings

    if not settings.email_enabled:
        return

    try:
        send_transactional_email.apply_async(
            kwargs={
                "organization_id": organization_id,
                "user_id": user_id,
                "recipient_email": recipient_email,
                "event_type": event_type,
                "template_name": template_name,
                "template_context": template_context,
                "subject": subject,
            }
        )
        _logger.info(
            "email.task.queued",
            event_type=event_type,
            recipient_email=recipient_email,
            organization_id=organization_id,
        )
    except Exception:
        _logger.warning(
            "email.task.dispatch_failed",
            event_type=event_type,
            recipient_email=recipient_email,
            user_id=user_id,
        )
