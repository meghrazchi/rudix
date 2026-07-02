from __future__ import annotations

import hashlib
from math import floor
from time import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.public_contact.schemas import (
    PublicContactSubmissionRequest,
    PublicContactSubmissionResponse,
)
from app.domains.public_contact.service import PublicContactService

router = APIRouter(prefix="/contact", tags=["public-contact"])

_service = PublicContactService()
_logger = get_logger("public_contact.http")


def _request_id(request: Request) -> str | None:
    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str) and state_request_id.strip():
        return state_request_id
    header_request_id = request.headers.get("x-request-id")
    return header_request_id.strip() if header_request_id else None


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first[:128]
    if request.client is None:
        return None
    return request.client.host[:128]


def _client_rate_limit_key(request: Request) -> str:
    identifier = _client_ip(request) or "unknown"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    bucket = floor(time() / settings.rate_limit_window_seconds)
    return f"rate_limit:v1:contact:{digest}:window:{bucket}"


def _rate_limit_response(*, retry_after: int, remaining: int) -> HTTPException:
    reset_epoch = int(time()) + retry_after
    limit = settings.rate_limit_contact_requests
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limit_exceeded",
            "message": "Rate limit exceeded for contact submissions",
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, remaining)),
            "X-RateLimit-Reset": str(reset_epoch),
        },
    )


async def _enforce_public_contact_rate_limit(request: Request) -> None:
    if not settings.is_rate_limit_active:
        return

    redis = redis_module.redis_client
    if redis is None:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "rate_limiter_unavailable",
                    "message": "Rate limiter unavailable",
                },
            )
        _logger.warning("public_contact.rate_limit.redis_unavailable")
        return

    key = _client_rate_limit_key(request)
    window_seconds = settings.rate_limit_window_seconds
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        ttl = await redis.ttl(key)
        if ttl <= 0:
            await redis.expire(key, window_seconds)
            ttl = window_seconds
        remaining = settings.rate_limit_contact_requests - int(count)
        if count > settings.rate_limit_contact_requests:
            raise _rate_limit_response(retry_after=max(1, int(ttl)), remaining=remaining)
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "rate_limiter_unavailable",
                    "message": "Rate limiter unavailable",
                },
            ) from exc
        _logger.warning(
            "public_contact.rate_limit.redis_error",
            error=exc.__class__.__name__,
        )


@router.post("", response_model=PublicContactSubmissionResponse, status_code=201)
async def create_contact_submission(
    payload: PublicContactSubmissionRequest,
    request: Request,
    _: Annotated[None, Depends(_enforce_public_contact_rate_limit)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublicContactSubmissionResponse:
    outcome = await _service.submit(
        db_session,
        payload=payload,
        request_id=_request_id(request),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db_session.commit()
    await db_session.refresh(outcome.submission)

    if outcome.failure_reason == "not_configured":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact email delivery is not configured",
        )
    if outcome.failure_reason == "send_failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Contact email delivery failed",
        )

    return PublicContactSubmissionResponse(
        submission_id=str(outcome.submission.id),
        email_status="sent",
    )
