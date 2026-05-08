import os
from uuid import uuid4

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
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")

from app.core.config import settings
from app.models.enums import DocumentStatus, EvaluationRunStatus
from app.workers import document_tasks, evaluation_tasks
from app.workers.base_task import RudixTask, TransientTaskError
from app.workers.celery_app import celery_app


@pytest.fixture
def eager_celery() -> None:
    always_eager = celery_app.conf.task_always_eager
    eager_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = always_eager
        celery_app.conf.task_eager_propagates = eager_propagates


def test_celery_configuration_and_routes_are_wired() -> None:
    assert celery_app.conf.task_default_queue == settings.celery_task_default_queue
    assert celery_app.conf.task_routes["documents.process"]["queue"] == settings.celery_queue_documents_processing
    assert celery_app.conf.task_routes["documents.delete"]["queue"] == settings.celery_queue_documents_deletion
    assert celery_app.conf.task_routes["documents.reindex"]["queue"] == settings.celery_queue_documents_reindex
    assert celery_app.conf.task_routes["evaluations.run"]["queue"] == settings.celery_queue_evaluations

    registered = set(celery_app.tasks.keys())
    assert "documents.process" in registered
    assert "documents.delete" in registered
    assert "documents.reindex" in registered
    assert "evaluations.run" in registered


def test_retry_policy_retries_transient_failures(eager_celery: None) -> None:
    attempts = {"count": 0}
    task_name = f"tests.retry.{uuid4()}"

    @celery_app.task(bind=True, base=RudixTask, name=task_name)
    def flaky_task(self: RudixTask) -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientTaskError("temporary")
        return attempts["count"]

    result = flaky_task.delay().get(timeout=5)
    assert result == 3
    assert attempts["count"] == 3


def test_process_document_is_idempotent_when_already_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.indexed.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "set_document_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not update status")),
    )

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == "skipped"


def test_process_document_is_idempotent_when_already_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.processing.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "set_document_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not update status")),
    )

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == "skipped"


def test_process_document_extracts_and_sets_indexed_status(monkeypatch: pytest.MonkeyPatch) -> None:
    status_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.uploaded.value,
    )

    def _set_document_status(document_id: str, *, status: DocumentStatus, error_message: str | None = None) -> bool:
        del error_message
        status_calls.append((document_id, status.value))
        return True

    async def _extract_and_store(_: str) -> tuple[int, int, object]:
        class _Stats:
            pages_modified = 2

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 4,
                    "cleaning_pages_modified": 2,
                    "cleaning_null_bytes_removed": 1,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 3,
                    "cleaning_blank_lines_collapsed": 1,
                    "cleaning_chars_before": 120,
                    "cleaning_chars_after": 110,
                }

        return 4, 9, _Stats()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(document_tasks, "_extract_and_store_document_pages_async", _extract_and_store)

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == DocumentStatus.indexed.value
    assert result["page_count"] == 4
    assert result["chunk_count"] == 9
    assert result["cleaning_pages_modified"] == 2
    assert status_calls == [("doc-1", DocumentStatus.processing.value)]


def test_document_task_terminal_failure_marks_document_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _set_document_status(document_id: str, *, status: DocumentStatus, error_message: str | None = None) -> bool:
        captured["document_id"] = document_id
        captured["status"] = status.value
        captured["error_message"] = error_message or ""
        return True

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    document_tasks.process_document.on_terminal_failure(
        exc=RuntimeError("boom"),
        args=("doc-1",),
        kwargs={},
    )

    assert captured["document_id"] == "doc-1"
    assert captured["status"] == DocumentStatus.failed.value
    assert "boom" in captured["error_message"]


def test_evaluation_run_transitions_status(monkeypatch: pytest.MonkeyPatch) -> None:
    transitions: list[str] = []

    monkeypatch.setattr(
        evaluation_tasks,
        "get_evaluation_status",
        lambda _: EvaluationRunStatus.queued.value,
    )

    def _set_eval_status(
        evaluation_run_id: str,
        *,
        status: EvaluationRunStatus,
        mark_started: bool = False,
        mark_completed: bool = False,
    ) -> bool:
        transitions.append(status.value)
        return True

    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", _set_eval_status)

    result = evaluation_tasks.run_evaluation.run("eval-1")
    assert result["status"] == EvaluationRunStatus.completed.value
    assert transitions == [EvaluationRunStatus.running.value, EvaluationRunStatus.completed.value]
