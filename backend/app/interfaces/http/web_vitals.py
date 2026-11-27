"""First-party browser Web Vitals ingest (R07-11).

Unauthenticated, like the public contact form. Samples go to Prometheus histograms only:
nothing is stored in the database and neither IP addresses nor values are logged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger
from app.core.metrics_frontend import record_web_vital, record_web_vitals_outcome
from app.domains.analytics.schemas.web_vitals import WebVitalsBatchRequest
from app.interfaces.http.public_contact import _client_ip
from app.rate_limit import sliding_window

_logger = get_logger("web_vitals.http")

_RATE_LIMIT_WINDOW_SECONDS = 60
# Used when the batch could not be read (rejected, rate limited) so no name is known.
_UNKNOWN_METRIC = "all"


class _WebVitalsRoute(APIRoute):
    """Counts bodies rejected by validation before the handler runs."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                record_web_vitals_outcome(names=[_UNKNOWN_METRIC], outcome="rejected")
                raise

        return handler


router = APIRouter(prefix="/telemetry", tags=["telemetry"], route_class=_WebVitalsRoute)


def _require_ingest_enabled() -> None:
    if not settings.web_vitals_ingest_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _rate_limit_key(request: Request) -> str:
    identifier = _client_ip(request) or "unknown"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"rate_limit:v2:{{web_vitals:{digest}}}:web_vitals"


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "rate_limiter_unavailable", "message": "Rate limiter unavailable"},
    )


async def _enforce_rate_limit(request: Request) -> None:
    """Per-IP limit with the contact form's Redis failure behaviour."""
    if not settings.is_rate_limit_active:
        return

    redis = redis_module.redis_client
    if redis is None:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise _unavailable()
        _logger.warning("web_vitals.rate_limit.redis_unavailable")
        return

    limit = settings.web_vitals_rate_limit_per_minute
    try:
        result = await sliding_window.check(
            redis,
            user_key=_rate_limit_key(request),
            user_limit=limit,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )
    except Exception as exc:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise _unavailable() from exc
        _logger.warning("web_vitals.rate_limit.redis_error", error=exc.__class__.__name__)
        return

    if not result.allowed:
        record_web_vitals_outcome(names=[_UNKNOWN_METRIC], outcome="rate_limited")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit_exceeded",
                "message": "Rate limit exceeded for telemetry",
                "retry_after_seconds": result.retry_after_seconds,
            },
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.post(
    "/web-vitals",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Receive browser Web Vitals samples",
    responses={
        404: {"description": "Ingest is disabled (WEB_VITALS_INGEST_ENABLED=false)."},
        429: {"description": "Per-client rate limit exceeded."},
    },
)
async def ingest_web_vitals(
    payload: WebVitalsBatchRequest,
    _enabled: Annotated[None, Depends(_require_ingest_enabled)],
    _limited: Annotated[None, Depends(_enforce_rate_limit)],
) -> Response:
    for sample in payload.samples:
        record_web_vital(name=sample.name, value=sample.value, route=sample.route)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
