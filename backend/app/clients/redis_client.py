from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis | None = None


async def init_redis() -> None:
    global redis_client
    redis_client = Redis.from_url(str(settings.redis_url), encoding="utf-8", decode_responses=True)


async def close_redis() -> None:
    if redis_client is not None:
        await redis_client.aclose()


async def check_redis_health() -> bool:
    if redis_client is None:
        return False
    try:
        response = await redis_client.ping()
        return bool(response)
    except Exception:
        return False
