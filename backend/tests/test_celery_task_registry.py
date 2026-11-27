import importlib
import os
import pkgutil
from typing import Any

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

import app.workers as workers_pkg
from app.core.config import settings
from app.workers.celery_app import celery_app


def _task_modules() -> list[str]:
    # Import every module under app.workers so a task defined outside a *_tasks module
    # is still registered and caught by the include/route checks below.
    all_names = [
        f"{workers_pkg.__name__}.{m.name}" for m in pkgutil.iter_modules(workers_pkg.__path__)
    ]
    for name in all_names:
        importlib.import_module(name)
    return sorted(name for name in all_names if name.endswith("_tasks"))


def _app_tasks() -> dict[str, Any]:
    _task_modules()
    return {
        name: task
        for name, task in celery_app.tasks.items()
        if not name.startswith("celery.")
        and str(getattr(task, "__module__", "")).startswith("app.workers.")
    }


def test_every_task_module_is_in_celery_include() -> None:
    modules = _task_modules()
    assert len(modules) >= 6
    include = set(celery_app.conf.include)
    assert [m for m in modules if m not in include] == []


def test_every_app_task_module_is_included() -> None:
    include = set(celery_app.conf.include)
    tasks = _app_tasks()
    assert tasks
    assert [n for n, t in tasks.items() if t.__module__ not in include] == []


def test_every_app_task_has_explicit_route() -> None:
    routes = celery_app.conf.task_routes
    assert [n for n in _app_tasks() if n not in routes] == []


def test_routes_target_declared_queues() -> None:
    queues = {q.name for q in celery_app.conf.task_queues}
    for name, route in celery_app.conf.task_routes.items():
        assert route["queue"] in queues, name
        assert route["routing_key"] == route["queue"], name


def test_beat_schedule_tasks_are_registered_and_routed() -> None:
    tasks = _app_tasks()
    routes = celery_app.conf.task_routes
    entries = list(celery_app.conf.beat_schedule.values())
    assert entries
    for entry in entries:
        assert entry["task"] in tasks
        assert entry["task"] in routes


def test_new_routes() -> None:
    routes = celery_app.conf.task_routes
    expected = {
        "documents.graph_reindex": settings.celery_queue_documents_reindex,
        "documents.backfill": settings.celery_queue_documents_reindex,
        "safety_evals.run": settings.celery_queue_evaluations,
        "agents.approvals.expire": settings.celery_task_default_queue,
    }
    for name, queue in expected.items():
        assert routes[name] == {"queue": queue, "routing_key": queue}


def test_safety_eval_task_registered_via_include() -> None:
    _task_modules()
    assert "safety_evals.run" in celery_app.tasks
