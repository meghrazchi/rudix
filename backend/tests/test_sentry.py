import os
from types import SimpleNamespace
from typing import Any

import pytest

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
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from app.core import sentry as sentry_module
from app.core.config import Environment


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    payload: dict[str, Any] = {
        "sentry_dsn": "https://public@example.com/1",
        "environment": Environment.test,
        "sentry_error_sample_rate": None,
        "sentry_traces_sample_rate": None,
        "sentry_profiles_sample_rate": None,
        "sentry_release": None,
        "api_version": "0.1.0",
    }
    payload.update(overrides)
    monkeypatch.setattr(sentry_module, "settings", SimpleNamespace(**payload))


def test_init_sentry_is_noop_when_dsn_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    init_calls: list[dict[str, Any]] = []
    set_tag_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(sentry_module, "_initialized_runtimes", set())
    monkeypatch.setattr(sentry_module.sentry_sdk, "init", lambda **kwargs: init_calls.append(kwargs))
    monkeypatch.setattr(sentry_module.sentry_sdk, "set_tag", lambda key, value: set_tag_calls.append((key, value)))
    _patch_settings(monkeypatch, sentry_dsn=None)

    initialized = sentry_module.init_sentry(runtime="api")

    assert initialized is False
    assert init_calls == []
    assert set_tag_calls == []


def test_init_sentry_uses_environment_aware_sample_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    init_calls: list[dict[str, Any]] = []
    set_tag_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(sentry_module, "_initialized_runtimes", set())
    monkeypatch.setattr(sentry_module.sentry_sdk, "init", lambda **kwargs: init_calls.append(kwargs))
    monkeypatch.setattr(sentry_module.sentry_sdk, "set_tag", lambda key, value: set_tag_calls.append((key, value)))
    _patch_settings(monkeypatch, environment=Environment.staging)

    initialized = sentry_module.init_sentry(runtime="worker")

    assert initialized is True
    assert len(init_calls) == 1
    assert init_calls[0]["sample_rate"] == 1.0
    assert init_calls[0]["traces_sample_rate"] == 0.2
    assert init_calls[0]["profiles_sample_rate"] == 0.0
    assert set_tag_calls == [("runtime", "worker")]


def test_init_sentry_fails_safe_when_sdk_init_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sentry_module, "_initialized_runtimes", set())
    monkeypatch.setattr(sentry_module.sentry_sdk, "init", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad dsn")))
    monkeypatch.setattr(sentry_module.sentry_sdk, "set_tag", lambda key, value: None)
    _patch_settings(monkeypatch)

    initialized = sentry_module.init_sentry(runtime="api")

    assert initialized is False


def test_redaction_masks_secrets_and_document_content() -> None:
    event = {
        "message": "api_key=abcd token=abc123",
        "request": {
            "headers": {
                "authorization": "Bearer super-secret",
                "x-request-id": "req_123",
            },
            "data": {"text": "very sensitive source document text"},
        },
        "extra": {
            "document_text": "private snippet",
            "debug_note": "password=hunter2",
        },
    }

    redacted = sentry_module._before_send(event, hint={})

    assert redacted is not None
    assert redacted["request"]["headers"]["authorization"] == "***"
    assert redacted["request"]["data"] == "<redacted:request_data>"
    assert redacted["extra"]["document_text"] == "<redacted:document_text>"
    assert "hunter2" not in redacted["extra"]["debug_note"]
    assert "abc123" not in redacted["message"]
