import os
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError
from qdrant_client.http.models import Distance

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")

from app.clients import factory, minio_client, qdrant_client
from app.core.config import AuthProvider, QdrantDistance, Settings


def _settings(**overrides: Any) -> Settings:
    payload = {
        "api_base_url": "http://localhost:8000",
        "frontend_base_url": "http://localhost:3000",
        "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app",
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "documents",
        "minio_endpoint": "http://localhost:9000",
        "minio_access_key": "minioadmin",
        "minio_secret_key": "minioadmin",
        "minio_bucket": "documents",
        "rabbitmq_url": "amqp://guest:guest@localhost:5672//",
        "redis_url": "redis://localhost:6379/0",
        "openai_api_key": "sk-test",
        "auth_provider": AuthProvider.clerk,
        "clerk_jwks_url": "https://example.com/.well-known/jwks.json",
    }
    payload.update(overrides)
    return Settings(_env_file=None, **payload)


def test_create_redis_client_uses_configured_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    class DummyRedis:
        @staticmethod
        def from_url(url: str, **kwargs: Any) -> object:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return sentinel

    monkeypatch.setattr(factory, "Redis", DummyRedis)
    settings = _settings(
        redis_socket_connect_timeout_seconds=3.5,
        redis_socket_timeout_seconds=4.5,
    )

    redis = factory.create_redis_client(settings)

    assert redis is sentinel
    assert captured["url"] == "redis://localhost:6379/0"
    assert captured["kwargs"]["socket_connect_timeout"] == 3.5
    assert captured["kwargs"]["socket_timeout"] == 4.5
    assert captured["kwargs"]["retry_on_timeout"] is True


def test_get_rabbitmq_host_port_resolves_default_ports() -> None:
    amqp_settings = _settings(rabbitmq_url="amqp://guest:guest@rabbitmq//")
    amqps_settings = _settings(rabbitmq_url="amqps://guest:guest@rabbitmq//")

    assert factory.get_rabbitmq_host_port(amqp_settings) == ("rabbitmq", 5672)
    assert factory.get_rabbitmq_host_port(amqps_settings) == ("rabbitmq", 5671)


def test_create_minio_client_builds_shared_timeout_and_retry_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_boto3_client(service_name: str, **kwargs: Any) -> object:
        captured["service_name"] = service_name
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(factory, "boto3", SimpleNamespace(client=fake_boto3_client))
    settings = _settings(
        dependency_connect_timeout_seconds=1.25,
        dependency_read_timeout_seconds=2.5,
        dependency_max_retries=3,
    )

    client = factory.create_minio_client(settings)

    assert client is sentinel
    assert captured["service_name"] == "s3"
    config = captured["kwargs"]["config"]
    assert config.connect_timeout == 1.25
    assert config.read_timeout == 2.5
    assert config.retries["total_max_attempts"] == 4
    assert config.s3["addressing_style"] == "path"


def test_qdrant_distance_mapping_covers_all_supported_values() -> None:
    assert factory.qdrant_distance_to_model(QdrantDistance.cosine) == Distance.COSINE
    assert factory.qdrant_distance_to_model(QdrantDistance.dot) == Distance.DOT
    assert factory.qdrant_distance_to_model(QdrantDistance.euclid) == Distance.EUCLID
    assert factory.qdrant_distance_to_model(QdrantDistance.manhattan) == Distance.MANHATTAN


def test_ensure_minio_bucket_creates_bucket_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeMinio:
        def head_bucket(self, **_: Any) -> None:
            calls.append("head_bucket")
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

        def create_bucket(self, **_: Any) -> None:
            calls.append("create_bucket")

    monkeypatch.setattr(
        minio_client,
        "settings",
        SimpleNamespace(minio_bucket="documents", minio_endpoint="http://localhost:9000"),
    )
    monkeypatch.setattr(minio_client, "minio_client", FakeMinio())

    minio_client.ensure_minio_bucket()

    assert calls == ["head_bucket", "create_bucket"]


def test_ensure_minio_bucket_does_not_create_when_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeMinio:
        def head_bucket(self, **_: Any) -> None:
            calls.append("head_bucket")

        def create_bucket(self, **_: Any) -> None:
            calls.append("create_bucket")

    monkeypatch.setattr(
        minio_client,
        "settings",
        SimpleNamespace(minio_bucket="documents", minio_endpoint="http://localhost:9000"),
    )
    monkeypatch.setattr(minio_client, "minio_client", FakeMinio())

    minio_client.ensure_minio_bucket()

    assert calls == ["head_bucket"]


def test_ensure_qdrant_collection_creates_collection_if_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeQdrant:
        def collection_exists(self, _: str) -> bool:
            calls.append("collection_exists")
            return False

        def create_collection(self, **_: Any) -> None:
            calls.append("create_collection")

    monkeypatch.setattr(
        qdrant_client,
        "settings",
        SimpleNamespace(
            qdrant_collection="documents",
            qdrant_vector_size=1536,
            qdrant_distance=QdrantDistance.cosine,
        ),
    )
    monkeypatch.setattr(qdrant_client, "qdrant_client", FakeQdrant())

    qdrant_client.ensure_qdrant_collection()

    assert calls == ["collection_exists", "create_collection"]


def test_ensure_qdrant_collection_raises_on_schema_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeVectors:
        size = 1024
        distance = Distance.DOT

    class FakeParams:
        vectors = FakeVectors()

    class FakeConfig:
        params = FakeParams()

    class FakeCollectionInfo:
        config = FakeConfig()

    class FakeQdrant:
        def collection_exists(self, _: str) -> bool:
            return True

        def get_collection(self, _: str) -> FakeCollectionInfo:
            return FakeCollectionInfo()

    monkeypatch.setattr(
        qdrant_client,
        "settings",
        SimpleNamespace(
            qdrant_collection="documents",
            qdrant_vector_size=1536,
            qdrant_distance=QdrantDistance.cosine,
        ),
    )
    monkeypatch.setattr(qdrant_client, "qdrant_client", FakeQdrant())

    with pytest.raises(RuntimeError, match="Existing Qdrant collection does not match"):
        qdrant_client.ensure_qdrant_collection()
