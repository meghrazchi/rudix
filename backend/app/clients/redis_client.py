from urllib.parse import urlsplit, urlunsplit

from redis.asyncio import Redis

from app.clients.factory import create_redis_client
from app.core.config import settings
from app.core.logging import get_logger

redis_client: Redis | None = None
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
        await redis_client.aclose()
        redis_client = None
        raise


async def close_redis() -> None:
    if redis_client is not None:
        logger.info("redis.close")
        await redis_client.aclose()


async def check_redis_health() -> bool:
    if redis_client is None:
        return False
    try:
        response = await redis_client.ping()
        return bool(response)
    except Exception:
        return False
