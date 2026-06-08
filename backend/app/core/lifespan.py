from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.clamav_client import close_clamav, init_clamav
from app.clients.minio_client import close_minio, init_minio
from app.clients.qdrant_client import close_qdrant, init_qdrant
from app.clients.rabbitmq_client import close_rabbitmq, init_rabbitmq
from app.clients.redis_client import close_redis, init_redis
from app.core.langfuse_tracer import init_langfuse, shutdown_langfuse
from app.core.sentry import init_sentry


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        init_sentry(runtime="api")
        init_langfuse(runtime="api")
        await init_redis()
        init_rabbitmq()
        init_qdrant()
        init_minio()
        init_clamav()
        yield
    finally:
        await close_redis()
        close_rabbitmq()
        close_qdrant()
        close_minio()
        close_clamav()
        shutdown_langfuse()
