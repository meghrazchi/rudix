from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from math import floor
from time import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger

logger = get_logger("auth.rate_limit")


class RateLimitScope(StrEnum):
    upload = "upload"
    chat = "chat"
    evaluation = "evaluation"
    delete = "delete"
    admin = "admin"


def _scope_limit(scope: RateLimitScope) -> int:
    mapping = {
        RateLimitScope.upload: settings.rate_limit_upload_requests,
        RateLimitScope.chat: settings.rate_limit_chat_requests,
        RateLimitScope.evaluation: settings.rate_limit_evaluation_requests,
        RateLimitScope.delete: settings.rate_limit_delete_requests,
        RateLimitScope.admin: settings.rate_limit_admin_requests,
    }
    return mapping[scope]


def _route_path_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _build_key(*, scope: RateLimitScope, endpoint: str, user_id: str, organization_id: str, window: int) -> str:
    sanitized_endpoint = endpoint.replace(" ", "_")
    return (
        f"rate_limit:v1:{scope.value}:{sanitized_endpoint}:"
        f"org:{organization_id}:user:{user_id}:window:{window}"
    )


def _rate_limit_disabled() -> bool:
    return not settings.is_rate_limit_active


def _http_429(*, scope: RateLimitScope, limit: int, retry_after: int, remaining: int) -> HTTPException:
    reset_epoch = int(time()) + retry_after
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limit_exceeded",
            "message": f"Rate limit exceeded for {scope.value}",
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, remaining)),
            "X-RateLimit-Reset": str(reset_epoch),
        },
    )


def _http_503_rate_limiter_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "rate_limiter_unavailable",
            "message": "Rate limiter unavailable",
        },
    )


async def _consume(scope: RateLimitScope, request: Request, principal: AuthenticatedPrincipal) -> None:
    if _rate_limit_disabled():
        return

    limit = _scope_limit(scope)
    window_seconds = settings.rate_limit_window_seconds
    window_bucket = floor(time() / window_seconds)

    endpoint = _route_path_template(request)
    organization_id = principal.organization_id or "none"
    key = _build_key(
        scope=scope,
        endpoint=endpoint,
        user_id=principal.user_id,
        organization_id=organization_id,
        window=window_bucket,
    )

    redis = redis_module.redis_client
    if redis is None:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise _http_503_rate_limiter_unavailable()
        logger.warning(
            "rate_limit.redis_unavailable",
            scope=scope.value,
            endpoint=endpoint,
            user_id=principal.user_id,
            organization_id=organization_id,
        )
        return

    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        ttl = await redis.ttl(key)
        if ttl <= 0:
            await redis.expire(key, window_seconds)
            ttl = window_seconds

        remaining = limit - int(count)
        if count > limit:
            logger.info(
                "rate_limit.exceeded",
                scope=scope.value,
                endpoint=endpoint,
                user_id=principal.user_id,
                organization_id=organization_id,
                limit=limit,
                retry_after_seconds=int(ttl),
            )
            raise _http_429(
                scope=scope,
                limit=limit,
                retry_after=max(1, int(ttl)),
                remaining=remaining,
            )
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            logger.error(
                "rate_limit.redis_error",
                scope=scope.value,
                endpoint=endpoint,
                user_id=principal.user_id,
                organization_id=organization_id,
                error=exc.__class__.__name__,
            )
            raise _http_503_rate_limiter_unavailable() from exc

        logger.warning(
            "rate_limit.redis_error.degraded",
            scope=scope.value,
            endpoint=endpoint,
            user_id=principal.user_id,
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )


def enforce_rate_limit(scope: RateLimitScope) -> Callable[[Request, AuthenticatedPrincipal], Awaitable[None]]:
    async def dependency(
        request: Request,
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> None:
        await _consume(scope=scope, request=request, principal=principal)

    return dependency
