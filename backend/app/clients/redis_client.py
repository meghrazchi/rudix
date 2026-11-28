from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from redis.asyncio import Redis

from app.clients.factory import create_redis_client
from app.core.config import settings
from app.core.logging import get_logger

redis_client: Redis | None = None
# R08-05: cached values only (``REDIS_CACHE_URL``); ``None`` means they share ``redis_client``.
# Every state key (rate limits, semaphores, tickets, resume buffer, realtime, usage touch,
# cache version keys) stays on ``redis_client``.
cache_redis_client: Redis | None = None
logger = get_logger("clients.redis")


def _sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


async def init_redis() -> None:
    global redis_client
    redis_client = create_redis_client(settings)
    try:
        await redis_client.ping()
        logger.info(
            "redis.init.success",
            url=_sanitize_url(str(settings.redis_url)),
            socket_connect_timeout_seconds=settings.redis_socket_connect_timeout_seconds,
            socket_timeout_seconds=settings.redis_socket_timeout_seconds,
        )
    except Exception as exc:
        logger.error(
            "redis.init.failed",
            url=_sanitize_url(str(settings.redis_url)),
            error=exc.__class__.__name__,
            exc_info=exc,
        )
        redis_any = cast(Any, redis_client)
        await redis_any.aclose()
        redis_client = None
        raise


async def close_redis() -> None:
    if redis_client is not None:
        logger.info("redis.close")
        redis_any = cast(Any, redis_client)
        await redis_any.aclose()


async def init_cache_redis() -> None:
    """R08-05: connect the cached-values Redis when ``REDIS_CACHE_URL`` is set (else no-op)."""
    global cache_redis_client
    url = settings.redis_cache_url
    if url is None:
        cache_redis_client = None
        return
    client = create_redis_client(settings, url=str(url))
    try:
        await client.ping()
    except Exception as exc:
        logger.error(
            "redis.cache.init.failed",
            url=_sanitize_url(str(url)),
            error=exc.__class__.__name__,
        )
        await cast(Any, client).aclose()
        cache_redis_client = None
        raise
    cache_redis_client = client
    logger.info("redis.cache.init.success", url=_sanitize_url(str(url)))


async def close_cache_redis() -> None:
    global cache_redis_client
    client = cache_redis_client
    cache_redis_client = None
    if client is not None:
        logger.info("redis.cache.close")
        await cast(Any, client).aclose()


async def check_cache_redis_health() -> bool:
    """Readiness of the cached-values Redis; reconnects after a degraded boot."""
    if cache_redis_client is None:
        try:
            await init_cache_redis()
        except Exception:
            return False
    client = cache_redis_client
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except Exception:
        return False


async def check_redis_health() -> bool:
    if redis_client is None:
        # Degraded boot (R04-12): reconnect from the readiness probe so the API
        # recovers once Redis is back, without a restart.
        try:
            await init_redis()
        except Exception:
            return False
    client = redis_client
    if client is None:
        return False
    try:
        response = await client.ping()
        return bool(response)
    except Exception:
        return False
