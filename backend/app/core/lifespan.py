from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.minio_client import close_minio, init_minio
from app.clients.qdrant_client import close_qdrant, init_qdrant
from app.clients.rabbitmq_client import close_rabbitmq, init_rabbitmq
from app.clients.redis_client import close_redis, init_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await init_redis()
        init_rabbitmq()
        init_qdrant()
        init_minio()
        yield
    finally:
        await close_redis()
        close_rabbitmq()
        close_qdrant()
        close_minio()
