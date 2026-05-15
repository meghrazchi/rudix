import os

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

from app.workers import base_task
from app.workers.base_task import RudixTask


def test_task_failure_capture_smoke_calls_sentry_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    captures: list[dict[str, str | None]] = []

    def _capture(
        exc: Exception,
        *,
        runtime: str,
        request_id: str | None = None,
        user_id: str | None = None,
        organization_id: str | None = None,
        task_name: str | None = None,
        task_id: str | None = None,
    ) -> None:
        del exc
        captures.append(
            {
                "runtime": runtime,
                "request_id": request_id,
                "user_id": user_id,
                "organization_id": organization_id,
                "task_name": task_name,
                "task_id": task_id,
            }
        )

    monkeypatch.setattr(base_task, "capture_sentry_exception", _capture)

    task = RudixTask()
    task.name = "tests.task.failure"
    task.on_failure(
        RuntimeError("boom"),
        "task-id-1",
        tuple(),
        {
            "request_id": "req_1",
            "organization_id": "org_1",
            "user_id": "user_1",
        },
        None,
    )

    assert captures == [
        {
            "runtime": "worker",
            "request_id": "req_1",
            "user_id": "user_1",
            "organization_id": "org_1",
            "task_name": "tests.task.failure",
            "task_id": "task-id-1",
        }
    ]
