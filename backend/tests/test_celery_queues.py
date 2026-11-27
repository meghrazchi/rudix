"""Queue declarations per queue type (R06-05)."""

from __future__ import annotations

import os
from typing import Any

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
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

import pytest
from celery import Celery
from celery.utils.quorum_queues import detect_quorum_queues
from kombu import Queue
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.settings.workers import WorkersSettings
from app.workers.celery_app import TASK_ROUTES, celery_app
from app.workers.queues import (
    build_task_queues,
    current_queue_for_task,
    dead_letter_queue,
    queue_conf,
    sampled_queue_names,
    task_queue_names,
)


def _config(**overrides: Any) -> Settings:
    return settings.model_copy(update=overrides)


def _quorum(**overrides: Any) -> Settings:
    return _config(celery_queue_type="quorum", **overrides)


def _declarations_0_5_0(config: Settings) -> tuple[Queue, ...]:
    """The 0.5.0 / S2 ``_task_queues()`` body, kept verbatim for the equality check."""
    names = [
        config.celery_task_default_queue,
        config.celery_queue_documents_processing,
        config.celery_queue_documents_deletion,
        config.celery_queue_documents_reindex,
        config.celery_queue_evaluations,
        config.celery_queue_connector_sync,
        "email",
        config.celery_queue_documents_embedding,
        config.celery_queue_documents_graph,
    ]
    return tuple(Queue(name, routing_key=name) for name in dict.fromkeys(names))


def test_classic_mode_declares_todays_queues_unchanged() -> None:
    assert settings.celery_queue_type == "classic"
    assert build_task_queues(settings) == _declarations_0_5_0(settings)
    assert tuple(celery_app.conf.task_queues) == _declarations_0_5_0(settings)
    for queue in build_task_queues(settings):
        assert queue.queue_arguments is None
    assert queue_conf(settings) == {
        "task_default_exchange": "rudix",
        "task_default_exchange_type": "direct",
    }
    assert celery_app.conf.task_default_exchange == "rudix"
    assert celery_app.conf.task_default_exchange_type == "direct"
    assert celery_app.conf.task_default_queue_type == "classic"


def test_classic_mode_with_a_distinct_embedding_queue() -> None:
    config = _config(celery_queue_documents_embedding="documents.embedding")
    assert build_task_queues(config) == _declarations_0_5_0(config)
    assert "documents.embedding" in task_queue_names(config)


def test_quorum_mode_declares_quorum_queues_with_dead_lettering() -> None:
    config = _quorum(celery_delivery_limit=7)
    task_queues = build_task_queues(config)
    assert [q.name for q in task_queues] == task_queue_names(config)
    # Never a task queue: a worker without -Q would execute dead-lettered messages.
    assert "rudix.dead_letter" not in [q.name for q in task_queues]
    for queue in task_queues:
        assert queue.queue_arguments == {
            "x-queue-type": "quorum",
            "x-delivery-limit": 7,
            "x-dead-letter-exchange": "rudix.dlx",
            "x-dead-letter-routing-key": "rudix.dead_letter",
        }
        assert queue.exchange.name == "rudix.tasks"
        assert queue.exchange.type == "topic"
        assert queue.routing_key == queue.name
        assert queue.durable
    dlq = dead_letter_queue(config)
    assert dlq.name == "rudix.dead_letter"
    assert dlq.exchange.name == "rudix.dlx" and dlq.exchange.type == "direct"
    assert dlq.routing_key == "rudix.dead_letter"
    assert dlq.queue_arguments == {"x-queue-type": "quorum"}


def test_quorum_mode_sets_the_celery_options_quorum_queues_need() -> None:
    conf = queue_conf(_quorum())
    assert conf["task_default_exchange"] == "rudix.tasks"
    assert conf["task_default_exchange_type"] == "topic"
    assert conf["task_default_queue_type"] == "quorum"
    assert conf["task_create_missing_queue_type"] == "quorum"
    assert conf["task_create_missing_queue_exchange_type"] == "topic"
    assert conf["worker_detect_quorum_queues"] is True
    assert conf["broker_native_delayed_delivery_queue_type"] == "quorum"


def test_celery_detects_the_quorum_declarations() -> None:
    """Celery's own detector (global QoS off, native delayed delivery) sees the queues."""
    config = _quorum()
    app = Celery("quorum-probe", broker="memory://", set_as_current=False)
    app.conf.update(task_queues=build_task_queues(config), **queue_conf(config))
    assert detect_quorum_queues(app, "amqp") == (True, config.celery_task_default_queue)
    classic = Celery("classic-probe", broker="memory://", set_as_current=False)
    classic.conf.update(task_queues=build_task_queues(settings), **queue_conf(settings))
    assert detect_quorum_queues(classic, "amqp") == (False, "")


def test_quorum_cut_over_uses_the_configured_names() -> None:
    config = _quorum(
        celery_task_default_queue="default.q",
        celery_queue_documents_processing="documents.processing.q",
        celery_queue_email="email.q",
        celery_dead_letter_queue="rudix.dead_letter.q",
    )
    names = [q.name for q in build_task_queues(config)]
    assert names[0] == "default.q"
    assert "documents.processing.q" in names and "email.q" in names
    assert "rudix.dead_letter.q" not in names
    assert sampled_queue_names(config)[-1] == "rudix.dead_letter.q"
    assert "rudix.dead_letter" not in sampled_queue_names(settings)


def test_agents_queue_is_declared_when_configured() -> None:
    class _WithAgents:
        def __getattr__(self, name: str) -> Any:
            if name == "celery_queue_agents":
                return "agents"
            return getattr(settings, name)

    names = task_queue_names(_WithAgents())  # type: ignore[arg-type]
    assert names[-1] == "agents"


def test_email_route_follows_its_setting() -> None:
    route = TASK_ROUTES["app.workers.email_tasks.send_transactional_email"]
    assert route == {"queue": settings.celery_queue_email, "routing_key": "email"}
    from app.workers.email_tasks import send_transactional_email

    # No task-level queue: it would override the route (and is deprecated in Celery 5.7).
    assert getattr(send_transactional_email, "queue", None) is None


def test_broker_names_are_validated() -> None:
    with pytest.raises(ValidationError):
        WorkersSettings(celery_dead_letter_queue="bad name!")
    assert WorkersSettings(celery_dead_letter_exchange=" x.dlx ").celery_dead_letter_exchange == (
        "x.dlx"
    )
    with pytest.raises(ValidationError):
        WorkersSettings(celery_queue_type="stream")


def test_failed_job_retry_follows_the_current_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.interfaces.http import failed_jobs
    from app.workers import celery_app as celery_app_module

    assert current_queue_for_task("documents.process", "old.queue", "default") == (
        settings.celery_queue_documents_processing
    )
    assert current_queue_for_task("legacy.task", "stored.q", "default") == "stored.q"
    assert current_queue_for_task("legacy.task", None, "default") == "default"

    sent: list[tuple[str, dict[str, Any], str]] = []
    monkeypatch.setattr(
        failed_jobs.celery_app,
        "send_task",
        lambda name, kwargs, queue: sent.append((name, kwargs, queue)),
    )
    # A route renamed by a cut-over: the stored queue of an older FailedJob is not used.
    monkeypatch.setitem(
        celery_app_module.TASK_ROUTES,
        "documents.process",
        {"queue": "documents.processing.q", "routing_key": "documents.processing.q"},
    )
    job = SimpleNamespace(
        organization_id=uuid4(),
        id=uuid4(),
        entity_id=uuid4(),
        entity_type="document",
        task_name="documents.process",
        queue_name="documents.processing",
    )
    failed_jobs._dispatch_retry(job)  # type: ignore[arg-type]
    [(name, kwargs, queue)] = sent
    assert (name, queue) == ("documents.process", "documents.processing.q")
    assert kwargs["document_id"] == str(job.entity_id)
