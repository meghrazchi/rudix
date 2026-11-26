"""R02-13: dead modules stay deleted and legacy 501 routes are marked deprecated."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

UPLOAD_URL_PATH = "/api/v1/documents/upload-url"
CHAT_MESSAGES_PATH = "/api/v1/chat/sessions/{session_id}/messages"

DELETED_MODULES = [
    "app.domains.admin.services.usage_service",
    "app.domains.auth.services.auth_service",
    "app.domains.chat.services.retrieval_service",
    "app.domains.documents.services.document_service",
    "app.domains.documents.services.extraction_service",
    "app.domains.documents.services.storage_service",
    "app.domains.evaluations.services.evaluation_service",
    "app.auth.refresh_token_store",
]


@pytest.mark.parametrize("module_path", DELETED_MODULES)
def test_dead_module_is_removed(module_path: str) -> None:
    assert importlib.util.find_spec(module_path) is None


def _assert_deprecation(schema: dict) -> None:
    paths = schema["paths"]
    assert paths[UPLOAD_URL_PATH]["post"]["deprecated"] is True
    assert paths[CHAT_MESSAGES_PATH]["post"]["deprecated"] is True
    assert not paths[CHAT_MESSAGES_PATH]["get"].get("deprecated", False)


def test_runtime_openapi_marks_legacy_routes_deprecated() -> None:
    from app.main import app

    _assert_deprecation(app.openapi())


def test_committed_openapi_marks_legacy_routes_deprecated() -> None:
    path = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
    _assert_deprecation(json.loads(path.read_text(encoding="utf-8")))
