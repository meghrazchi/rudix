"""Plan question quota enforcement and usage recording for chat transports.

Both ``POST /chat`` and the ``/chat/ws`` pipeline call these helpers so the
quota check, the denial signal, and the usage counter stay identical across
transports.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import record_chat_quota_denied
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service

ChatTransport = Literal["http", "ws"]

PLAN_LIMIT_EXCEEDED_CODE = "plan_limit_exceeded"
_SAFE_DENIAL_FIELDS = ("quota_type", "retryable", "next_reset_at")


def _is_plan_limit_denial(exc: HTTPException) -> bool:
    detail = exc.detail
    return isinstance(detail, dict) and detail.get("code") == PLAN_LIMIT_EXCEEDED_CODE


async def ensure_chat_quota(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    transport: ChatTransport,
) -> None:
    """Raise the plan-limit ``HTTPException`` (403) when the question quota is exhausted.

    Read-only (R05-02): an expired window counts as zero here and is reset by the
    ``record_chat_usage`` increment in the final write, not by the check.
    """
    try:
        await plan_enforcement_service.ensure_within_limit(
            db_session,
            organization_id=organization_id,
            quota_type=QuotaType.questions,
            requested_amount=1,
            resource="chat questions",
            guidance="Upgrade your plan or reduce chat volume.",
            reset_expired=False,
        )
    except HTTPException as exc:
        if _is_plan_limit_denial(exc):
            record_chat_quota_denied(transport)
        raise


def chat_quota_denial(exc: HTTPException) -> dict[str, object] | None:
    """Return the client-safe subset of a plan-limit denial, or ``None`` for other errors."""
    detail = exc.detail
    if not isinstance(detail, dict) or not _is_plan_limit_denial(exc):
        return None
    return {field: detail.get(field) for field in _SAFE_DENIAL_FIELDS}


async def record_chat_usage(db_session: AsyncSession, *, organization_id: UUID) -> None:
    """Record one answered chat question against the organisation's quota."""
    await plan_enforcement_service.record_usage(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.questions,
        amount=1,
    )
