from __future__ import annotations

from math import floor
from time import time

from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger

_logger = get_logger("mcp.rate_limit")


class MCPRateLimitExceededError(Exception):
    def __init__(
        self,
        *,
        retry_after_seconds: int,
        limit: int,
        remaining: int,
    ) -> None:
        super().__init__("MCP rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds
        self.limit = limit
        self.remaining = remaining


class MCPRateLimiterUnavailableError(Exception):
    pass


def _build_key(
    *,
    tool_name: str,
    user_id: str,
    organization_id: str,
    window_bucket: int,
) -> str:
    return (
        f"rate_limit:v1:mcp:tool:{tool_name}:"
        f"org:{organization_id}:user:{user_id}:window:{window_bucket}"
    )


async def enforce_mcp_rate_limit(
    *,
    principal: AuthenticatedPrincipal,
    tool_name: str,
) -> None:
    if not settings.mcp_rate_limit_enabled or not settings.is_rate_limit_active:
        return

    limit = settings.mcp_rate_limit_requests
    window_seconds = settings.mcp_rate_limit_window_seconds
    window_bucket = floor(time() / window_seconds)

    organization_id = principal.organization_id or "none"
    key = _build_key(
        tool_name=tool_name,
        user_id=principal.user_id,
        organization_id=organization_id,
        window_bucket=window_bucket,
    )

    redis = redis_module.redis_client
    if redis is None:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise MCPRateLimiterUnavailableError("MCP rate limiter unavailable")
        _logger.warning(
            "mcp.rate_limit.redis_unavailable",
            tool_name=tool_name,
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
            _logger.info(
                "mcp.rate_limit.exceeded",
                tool_name=tool_name,
                user_id=principal.user_id,
                organization_id=organization_id,
                limit=limit,
                retry_after_seconds=int(ttl),
            )
            raise MCPRateLimitExceededError(
                retry_after_seconds=max(1, int(ttl)),
                limit=limit,
                remaining=remaining,
            )
    except MCPRateLimitExceededError:
        raise
    except Exception as exc:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            _logger.error(
                "mcp.rate_limit.redis_error",
                tool_name=tool_name,
                user_id=principal.user_id,
                organization_id=organization_id,
                error=exc.__class__.__name__,
            )
            raise MCPRateLimiterUnavailableError("MCP rate limiter unavailable") from exc

        _logger.warning(
            "mcp.rate_limit.redis_error.degraded",
            tool_name=tool_name,
            user_id=principal.user_id,
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )
