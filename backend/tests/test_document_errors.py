import os

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
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.core.document_errors import (
    build_document_error_details,
    decode_document_error,
    encode_document_error,
)


def test_encode_decode_document_error_round_trip() -> None:
    details = build_document_error_details(
        stage="index",
        code="QDRANT_UPSERT_FAILED",
        category="infrastructure",
        retryable=True,
        message="qdrant timeout",
    )
    encoded = encode_document_error(details)

    message, decoded = decode_document_error(encoded)
    assert message == "qdrant timeout"
    assert decoded == details


def test_decode_document_error_accepts_plain_text() -> None:
    message, details = decode_document_error("simple error")
    assert message == "simple error"
    assert details is None
