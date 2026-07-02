from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.email.providers.base import AbstractEmailProvider, EmailMessage
from app.domains.email.providers.factory import build_email_provider
from app.domains.email.services.template_service import render_email_template
from app.domains.public_contact.schemas import PublicContactSubmissionRequest
from app.models.contact import ContactSubmission

_logger = get_logger("public_contact.service")


@dataclass(frozen=True)
class ContactSubmissionOutcome:
    submission: ContactSubmission
    sent: bool
    failure_reason: str | None


class PublicContactService:
    def __init__(
        self,
        provider_factory: Callable[[], AbstractEmailProvider] = build_email_provider,
    ) -> None:
        self._provider_factory = provider_factory

    async def submit(
        self,
        session: AsyncSession,
        *,
        payload: PublicContactSubmissionRequest,
        request_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ContactSubmissionOutcome:
        receiver_email = _normalize_receiver(settings.contact_receiver_email)
        submission = ContactSubmission(
            full_name=payload.full_name,
            work_email=payload.work_email,
            company=payload.company,
            role_title=payload.role_title,
            use_case=payload.use_case,
            team_size=payload.team_size,
            message=payload.message,
            consent_accepted=payload.consent_accepted,
            source=payload.source,
            receiver_email=receiver_email,
            email_status="pending",
            request_id=request_id,
            ip_address=ip_address,
            user_agent=_truncate(user_agent, 512),
        )
        session.add(submission)
        await session.flush()

        if receiver_email is None:
            submission.email_status = "skipped"
            submission.email_error = "contact_receiver_email_not_configured"
            _logger.warning("public_contact.receiver_not_configured", request_id=request_id)
            await session.flush()
            return ContactSubmissionOutcome(
                submission=submission,
                sent=False,
                failure_reason="not_configured",
            )

        if not settings.email_enabled:
            submission.email_status = "skipped"
            submission.email_error = "email_disabled"
            _logger.warning("public_contact.email_disabled", request_id=request_id)
            await session.flush()
            return ContactSubmissionOutcome(
                submission=submission,
                sent=False,
                failure_reason="not_configured",
            )

        try:
            provider = self._provider_factory()
        except ValueError as exc:
            submission.email_status = "failed"
            submission.email_error = exc.__class__.__name__
            _logger.warning(
                "public_contact.provider_not_configured",
                request_id=request_id,
                error=exc.__class__.__name__,
            )
            await session.flush()
            return ContactSubmissionOutcome(
                submission=submission,
                sent=False,
                failure_reason="send_failed",
            )

        submission.email_provider = provider.provider_name
        result = await provider.send(
            EmailMessage(
                to_address=receiver_email,
                subject=_subject(payload),
                html_body=_html_body(payload, request_id=request_id),
                text_body=_text_body(payload, request_id=request_id),
                from_address=settings.email_from_address,
                from_name=settings.email_from_name,
                reply_to=payload.work_email,
                headers={"X-Rudix-Contact-Submission-ID": str(submission.id)},
            )
        )

        submission.provider_message_id = result.provider_message_id
        if result.success:
            submission.email_status = "sent"
            submission.email_error = None
            _logger.info(
                "public_contact.email_sent",
                submission_id=str(submission.id),
                provider=provider.provider_name,
            )
            await session.flush()
            return ContactSubmissionOutcome(submission=submission, sent=True, failure_reason=None)

        submission.email_status = "failed"
        submission.email_error = _truncate(result.error_detail, 2000) or "provider_send_failed"
        _logger.warning(
            "public_contact.email_failed",
            submission_id=str(submission.id),
            provider=provider.provider_name,
            error="provider_send_failed",
        )
        await session.flush()
        return ContactSubmissionOutcome(
            submission=submission,
            sent=False,
            failure_reason="send_failed",
        )


def _normalize_receiver(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip().lower()
    return trimmed or None


def _truncate(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    return value[:max_length]


def _subject(payload: PublicContactSubmissionRequest) -> str:
    company = payload.company[:80]
    return f"Rudix contact request from {company}"


def _html_body(payload: PublicContactSubmissionRequest, *, request_id: str | None) -> str:
    return render_email_template(
        "contact_submission.html",
        {
            "subject": _subject(payload),
            "frontend_base_url": str(settings.frontend_base_url).rstrip("/"),
            "org_name": "Rudix",
            "full_name": payload.full_name,
            "work_email": payload.work_email,
            "company": payload.company,
            "role_title": payload.role_title,
            "use_case": payload.use_case,
            "team_size": payload.team_size,
            "message": payload.message,
            "source": payload.source,
            "request_id": request_id,
        },
    )


def _text_body(payload: PublicContactSubmissionRequest, *, request_id: str | None) -> str:
    lines = [
        "New Rudix contact request",
        "",
        f"Name: {payload.full_name}",
        f"Work email: {payload.work_email}",
        f"Company: {payload.company}",
        f"Role/title: {payload.role_title}",
        f"Use case: {payload.use_case}",
        f"Team size: {payload.team_size}",
        f"Source: {payload.source}",
        f"Request ID: {request_id or 'n/a'}",
        "",
        "Message:",
        payload.message,
    ]
    return "\n".join(lines)
