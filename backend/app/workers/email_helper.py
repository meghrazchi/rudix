"""Thin sync wrapper for dispatching transactional emails from Celery worker tasks."""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger

_logger = get_logger("worker.email_helper")


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _lookup_user_email_async(user_id: UUID) -> str | None:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import User

    async with SessionLocal() as session:
        result = await session.execute(select(User.email).where(User.id == user_id))
        return result.scalar_one_or_none()


async def _lookup_document_name_async(document_id: str) -> str | None:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.document import Document

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        return None

    async with SessionLocal() as session:
        result = await session.execute(
            select(Document.original_filename).where(Document.id == doc_uuid)
        )
        return result.scalar_one_or_none()


def emit_upload_failure_email(
    *,
    organization_id: str | None,
    user_id: str | None,
    document_id: str | None,
    error_summary: str | None = None,
) -> None:
    """Dispatch upload-failure email from a Celery task. Silently swallows errors."""
    from app.core.config import settings

    if not settings.email_enabled:
        return

    org_uuid = _parse_optional_uuid(organization_id)
    user_uuid = _parse_optional_uuid(user_id)
    if org_uuid is None or user_uuid is None:
        return

    from app.workers.async_runtime import run_async
    from app.workers.email_tasks import dispatch_email

    try:
        recipient_email = run_async(_lookup_user_email_async(user_uuid))
        doc_name = run_async(_lookup_document_name_async(document_id)) if document_id else None
    except Exception:
        _logger.warning("email_helper.lookup_failed", user_id=user_id)
        return

    if not recipient_email:
        return

    doc_url = (
        f"{str(settings.frontend_base_url).rstrip('/')}/documents?highlight={document_id}"
        if document_id
        else None
    )

    dispatch_email(
        organization_id=str(org_uuid),
        user_id=str(user_uuid),
        recipient_email=recipient_email,
        event_type="upload_failed",
        template_name="upload_failure.html",
        subject="Document processing failed",
        template_context={
            "document_name": doc_name or document_id or "Unknown",
            "error_summary": error_summary,
            "document_url": doc_url,
        },
    )


def emit_connector_sync_failure_email(
    *,
    organization_id: str | None,
    user_id: str | None,
    connector_name: str | None = None,
    error_summary: str | None = None,
    failed_at: str | None = None,
) -> None:
    """Dispatch connector-sync-failure email from a Celery task. Silently swallows errors."""
    from app.core.config import settings

    if not settings.email_enabled:
        return

    org_uuid = _parse_optional_uuid(organization_id)
    user_uuid = _parse_optional_uuid(user_id)
    if org_uuid is None or user_uuid is None:
        return

    from app.workers.async_runtime import run_async
    from app.workers.email_tasks import dispatch_email

    try:
        recipient_email = run_async(_lookup_user_email_async(user_uuid))
    except Exception:
        _logger.warning("email_helper.lookup_failed", user_id=user_id)
        return

    if not recipient_email:
        return

    connector_url = f"{str(settings.frontend_base_url).rstrip('/')}/admin/connectors"

    dispatch_email(
        organization_id=str(org_uuid),
        user_id=str(user_uuid),
        recipient_email=recipient_email,
        event_type="connector_sync_failed",
        template_name="connector_sync_failure.html",
        subject=f"Connector sync failed: {connector_name or 'connector'}",
        template_context={
            "connector_name": connector_name,
            "error_summary": error_summary,
            "failed_at": failed_at,
            "connector_url": connector_url,
        },
    )
