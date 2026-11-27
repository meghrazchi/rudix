from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.rate_limit.counter import (
    RateLimitDecision,
    RateLimitedBy,
    RateLimitOutcome,
    RateLimitScope,
    _build_key,
    _rate_limit_disabled,
    _scope_limit,
    consume_rate_limit,
)

__all__ = [
    "RateLimitDecision",
    "RateLimitOutcome",
    "RateLimitScope",
    "RateLimitedBy",
    "_build_key",
    "_rate_limit_disabled",
    "_scope_limit",
    "consume_rate_limit",
    "enforce_rate_limit",
]


def _route_path_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _http_429(
    *,
    scope: RateLimitScope,
    limit: int,
    retry_after: int,
    remaining: int,
    limited_by: RateLimitedBy | None = None,
) -> HTTPException:
    reset_epoch = int(time()) + retry_after
    headers = {
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(reset_epoch),
    }
    if limited_by is not None:
        headers["X-RateLimit-Scope"] = limited_by.value
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limit_exceeded",
            "message": f"Rate limit exceeded for {scope.value}",
            "retry_after_seconds": retry_after,
        },
        headers=headers,
    )


def _http_503_rate_limiter_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "rate_limiter_unavailable",
            "message": "Rate limiter unavailable",
        },
    )


async def _consume(
    scope: RateLimitScope, request: Request, principal: AuthenticatedPrincipal
) -> None:
    outcome = await consume_rate_limit(
        scope=scope, endpoint=_route_path_template(request), principal=principal
    )
    if outcome.decision == RateLimitDecision.limited:
        raise _http_429(
            scope=scope,
            limit=outcome.limit,
            retry_after=outcome.retry_after_seconds,
            remaining=outcome.remaining,
            limited_by=outcome.limited_by,
        )
    if outcome.decision == RateLimitDecision.unavailable:
        raise _http_503_rate_limiter_unavailable()


def enforce_rate_limit(
    scope: RateLimitScope,
) -> Callable[[Request, AuthenticatedPrincipal], Awaitable[None]]:
    async def dependency(
        request: Request,
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> None:
        await _consume(scope=scope, request=request, principal=principal)

    return dependency
