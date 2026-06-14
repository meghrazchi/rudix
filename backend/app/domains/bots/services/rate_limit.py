from __future__ import annotations

from math import floor
from time import time

from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger

logger = get_logger("bots.rate_limit")


class BotRateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Bot rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class BotRateLimitUnavailableError(Exception):
    pass


class BotRateLimitService:
    async def consume(
        self,
        *,
        provider: str,
        external_workspace_id: str,
        external_user_id: str,
    ) -> None:
        if not settings.is_rate_limit_active:
            return

        redis = redis_module.redis_client
        if redis is None:
            if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
                raise BotRateLimitUnavailableError("Rate limiter unavailable")
            logger.warning(
                "bots.rate_limit.redis_unavailable",
                provider=provider,
                external_workspace_id=external_workspace_id,
                external_user_id=external_user_id,
            )
            return

        window_seconds = settings.rate_limit_window_seconds
        window_bucket = floor(time() / window_seconds)
        key = (
            "rate_limit:v1:bot:"
            f"{provider}:workspace:{external_workspace_id}:"
            f"user:{external_user_id}:window:{window_bucket}"
        )
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
            ttl = await redis.ttl(key)
            if ttl <= 0:
                await redis.expire(key, window_seconds)
                ttl = window_seconds
            if count > settings.rate_limit_bot_requests:
                raise BotRateLimitExceededError(max(1, int(ttl)))
        except BotRateLimitExceededError:
            raise
        except Exception as exc:
            if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
                raise BotRateLimitUnavailableError("Rate limiter unavailable") from exc
            logger.warning(
                "bots.rate_limit.redis_error.degraded",
                provider=provider,
                external_workspace_id=external_workspace_id,
                external_user_id=external_user_id,
                error=exc.__class__.__name__,
            )
