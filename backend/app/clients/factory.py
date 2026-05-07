from __future__ import annotations

from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance
from redis.asyncio import Redis

from app.core.config import QdrantDistance, Settings


def create_redis_client(config: Settings) -> Redis:
    return Redis.from_url(
        str(config.redis_url),
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=config.redis_socket_connect_timeout_seconds,
        socket_timeout=config.redis_socket_timeout_seconds,
        retry_on_timeout=True,
    )


def get_rabbitmq_host_port(config: Settings) -> tuple[str, int]:
    parsed = urlsplit(str(config.rabbitmq_url))
    host = parsed.hostname
    if host is None:
        raise ValueError("rabbitmq_url is missing host")
    port = parsed.port
    if port is None:
        port = 5671 if parsed.scheme == "amqps" else 5672
    return host, port


def create_minio_client(config: Settings) -> object:
    return boto3.client(
        "s3",
        endpoint_url=str(config.minio_endpoint),
        aws_access_key_id=config.minio_access_key,
        aws_secret_access_key=config.minio_secret_key.get_secret_value(),
        config=Config(
            connect_timeout=config.dependency_connect_timeout_seconds,
            read_timeout=config.dependency_read_timeout_seconds,
            retries={
                "mode": "standard",
                "total_max_attempts": config.dependency_max_retries + 1,
            },
            s3={"addressing_style": "path"},
        ),
    )


def create_qdrant_client(config: Settings) -> QdrantClient:
    return QdrantClient(
        url=str(config.qdrant_url),
        api_key=config.qdrant_api_key.get_secret_value() if config.qdrant_api_key else None,
        timeout=config.qdrant_timeout_seconds,
    )


def qdrant_distance_to_model(distance: QdrantDistance) -> Distance:
    mapping = {
        QdrantDistance.cosine: Distance.COSINE,
        QdrantDistance.dot: Distance.DOT,
        QdrantDistance.euclid: Distance.EUCLID,
        QdrantDistance.manhattan: Distance.MANHATTAN,
    }
    return mapping[distance]
