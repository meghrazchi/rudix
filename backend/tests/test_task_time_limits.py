"""Task time limits, child recycling, and the consumer-timeout check (R06-03)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

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

from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
from pydantic import ValidationError

from app.core import metrics_workers
from app.core.config import Settings, settings
from app.core.document_errors import decode_document_error
from app.core.settings.enums import Environment
from app.core.settings.worker_platform import (
    DEFAULT_TASK_TIME_LIMITS,
    TaskTimeLimit,
    merge_task_time_limits,
)
from app.core.settings.workers import WorkersSettings
from app.workers import base_task, document_tasks
from app.workers import celery_app as celery_app_module
from app.workers.celery_app import celery_app
from app.workers.ingestion import tasks as ingest_tasks
from app.workers.ingestion.stages.base import StageName
from app.workers.status_tracking import FailureMarkOutcome, FailureMarkResult
from app.workers.time_limits import (
    ConsumerTimeoutConfigError,
    build_task_annotations,
    check_consumer_timeout,
    hard_limits_over_consumer_timeout,
    time_limit_conf,
    time_limit_error_code,
)


def _config(**overrides: Any) -> Settings:
    return settings.model_copy(update=overrides)


# ── settings and annotations ───────────────────────────────────────────────────────────


def test_defaults_cover_every_stage_task_and_stay_below_the_consumer_timeout() -> None:
    limits = settings.celery_task_time_limits
    for stage in ("extract", "clean_detect", "dlp", "chunk", "embed", "index", "finalize"):
        assert f"documents.ingest.{stage}" in limits
    assert limits["documents.ingest.extract"].hard > limits["documents.ingest.embed"].hard
    assert limits["documents.graph_extract"].hard > limits["documents.ingest.embed"].hard
    assert limits["evaluations.run"].soft >= 1500
    assert hard_limits_over_consumer_timeout(settings) == []
    assert settings.celery_task_default_soft_time_limit == 300
    assert settings.celery_task_default_time_limit == 360
    assert settings.celery_broker_consumer_timeout_seconds == 1800


def test_configured_limits_merge_over_the_defaults() -> None:
    merged = merge_task_time_limits(
        {"evaluations.run": {"soft": 10, "hard": 20}, " x.y ": {"soft": 1, "hard": 2}}
    )
    assert merged["evaluations.run"] == TaskTimeLimit(soft=10, hard=20)
    assert merged["x.y"] == TaskTimeLimit(soft=1, hard=2)
    assert (
        merged["documents.ingest.extract"].soft
        == DEFAULT_TASK_TIME_LIMITS["documents.ingest.extract"]["soft"]
    )


def test_limit_validation_rejects_bad_values() -> None:
    with pytest.raises(ValidationError):
        TaskTimeLimit(soft=20, hard=20)
    with pytest.raises(ValueError):
        merge_task_time_limits(["not", "a", "dict"])
    with pytest.raises(ValueError):
        merge_task_time_limits({"": {"soft": 1, "hard": 2}})
    with pytest.raises(ValidationError):
        WorkersSettings(celery_task_default_soft_time_limit=400, celery_task_default_time_limit=300)


def test_limits_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CELERY_TASK_TIME_LIMITS", '{"documents.ingest.embed": {"soft": 50, "hard": 70}}'
    )
    monkeypatch.setenv("CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB", "1048576")
    parsed = Settings()
    assert parsed.celery_task_time_limits["documents.ingest.embed"] == TaskTimeLimit(
        soft=50, hard=70
    )
    assert parsed.celery_task_time_limits["documents.ingest.extract"].hard == 1620
    assert parsed.celery_worker_max_memory_per_child_kb == 1048576


def test_annotations_carry_the_configured_limits() -> None:
    annotations = celery_app.conf.task_annotations
    for name, limit in settings.celery_task_time_limits.items():
        assert annotations[name] == {"soft_time_limit": limit.soft, "time_limit": limit.hard}
    assert "*" not in annotations
    extract = celery_app.tasks["documents.ingest.extract"]
    expected = settings.celery_task_time_limits["documents.ingest.extract"]
    assert (extract.soft_time_limit, extract.time_limit) == (expected.soft, expected.hard)
    embed = celery_app.tasks["documents.ingest.embed"]
    assert embed.time_limit == settings.celery_task_time_limits["documents.ingest.embed"].hard
    assert celery_app.conf.task_soft_time_limit == settings.celery_task_default_soft_time_limit
    assert celery_app.conf.task_time_limit == settings.celery_task_default_time_limit
    assert celery_app.conf.worker_max_tasks_per_child == settings.celery_worker_max_tasks_per_child


def test_time_limit_conf_maps_zero_recycling_to_off() -> None:
    conf = time_limit_conf(
        _config(celery_worker_max_tasks_per_child=0, celery_worker_max_memory_per_child_kb=0)
    )
    assert conf["worker_max_tasks_per_child"] is None
    assert conf["worker_max_memory_per_child"] is None
    conf = time_limit_conf(_config(celery_worker_max_memory_per_child_kb=512_000))
    assert conf["worker_max_tasks_per_child"] == 200
    assert conf["worker_max_memory_per_child"] == 512_000
    custom = _config(celery_task_time_limits={"a.task": TaskTimeLimit(soft=1, hard=2)})
    assert build_task_annotations(custom) == {"a.task": {"soft_time_limit": 1, "time_limit": 2}}


# ── consumer timeout check ─────────────────────────────────────────────────────────────


def _too_long() -> Settings:
    limits = dict(settings.celery_task_time_limits)
    limits["evaluations.run"] = TaskTimeLimit(soft=1700, hard=1900)
    return _config(celery_task_time_limits=limits)


def test_consumer_timeout_check_fails_when_a_hard_limit_exceeds_it() -> None:
    config = _too_long().model_copy(update={"environment": Environment.production})
    assert hard_limits_over_consumer_timeout(config) == [("evaluations.run", 1900)]
    with pytest.raises(ConsumerTimeoutConfigError, match=r"evaluations\.run=1900s"):
        check_consumer_timeout(config)
    staging = config.model_copy(update={"environment": Environment.staging})
    with pytest.raises(ConsumerTimeoutConfigError):
        check_consumer_timeout(staging)


def test_consumer_timeout_check_counts_the_default_limit_and_warns_outside_production() -> None:
    config = _config(celery_broker_consumer_timeout_seconds=360)
    assert ("<default>", 360) in hard_limits_over_consumer_timeout(config)
    check_consumer_timeout(config)  # test environment: warning only
    check_consumer_timeout(settings)  # nothing to report


def test_worker_init_handler_stops_the_worker_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _too_long().model_copy(update={"environment": Environment.production})
    monkeypatch.setattr(celery_app_module, "settings", config)
    with pytest.raises(SystemExit):
        celery_app_module._check_worker_limits()
    monkeypatch.setattr(celery_app_module, "settings", settings)
    celery_app_module._check_worker_limits()


# ── failure recording ──────────────────────────────────────────────────────────────────


def test_time_limit_error_codes() -> None:
    assert time_limit_error_code(SoftTimeLimitExceeded()) == "task_soft_time_limit"
    assert time_limit_error_code(TimeLimitExceeded(10)) == "task_time_limit"
    assert time_limit_error_code(RuntimeError("x")) is None
    assert base_task._safe_error_code(RuntimeError("x")) == "RuntimeError"


@pytest.fixture
def captured_jobs(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    jobs: list[Any] = []

    async def _insert(_factory: Any, job: Any) -> None:
        jobs.append(job)

    monkeypatch.setattr(base_task, "_insert_failed_job", _insert)
    return jobs


@pytest.fixture
def document_failures(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from app.workers import email_helper, notification_helper

    marks: list[dict[str, Any]] = []

    def _mark(document_id: str, **kwargs: Any) -> FailureMarkResult:
        marks.append({"document_id": document_id, **kwargs})
        return FailureMarkResult(FailureMarkOutcome.updated, "failed")

    monkeypatch.setattr(document_tasks, "mark_document_failed", _mark)
    monkeypatch.setattr(document_tasks, "log_document_event", lambda **kw: None)
    monkeypatch.setattr(document_tasks, "_record_worker_audit", lambda **kw: None)
    monkeypatch.setattr(notification_helper, "emit_notification", lambda **kw: None)
    monkeypatch.setattr(email_helper, "emit_upload_failure_email", lambda **kw: None)
    return marks


def _fail(task: Any, exc: Exception, kwargs: dict[str, Any]) -> None:
    task.push_request(id="task-1", retries=0, delivery_info={"routing_key": "documents.processing"})
    try:
        task.on_failure(exc, "task-1", (), kwargs, None)
    finally:
        task.pop_request()


def test_soft_time_limit_on_a_stage_task_records_failed_job_and_fails_the_document(
    captured_jobs: list[Any],
    document_failures: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        metrics_workers, "record_task_time_limit", lambda task, kind: counted.append((task, kind))
    )
    org, document = uuid4(), uuid4()
    task = ingest_tasks.STAGE_TASKS[StageName.extract]
    _fail(
        task,
        SoftTimeLimitExceeded(),
        {
            "document_id": str(document),
            "organization_id": str(org),
            "run_id": "run-1",
            "claim_token": "claim-1",
        },
    )

    [job] = captured_jobs
    assert job.error_code == "task_soft_time_limit"
    assert job.task_name == "documents.process"
    assert job.organization_id == org and job.entity_id == document
    assert job.metadata_json == {"stage": "extract", "run_id": "run-1"}
    [mark] = document_failures
    assert mark["document_id"] == str(document)
    assert mark["owner_task_id"] == "claim-1"
    _, details = decode_document_error(mark["error_message"])
    assert details is not None
    assert details["code"] == "task_soft_time_limit"
    assert details["stage"] == "extract"
    assert details["retryable"] is True
    assert counted == [("documents.ingest.extract", "soft")]


def test_hard_time_limit_on_the_process_task_records_task_time_limit(
    captured_jobs: list[Any], document_failures: list[dict[str, Any]]
) -> None:
    org, document = uuid4(), uuid4()
    _fail(
        document_tasks.process_document,
        TimeLimitExceeded(1620),
        {"document_id": str(document), "organization_id": str(org)},
    )
    [job] = captured_jobs
    assert job.error_code == "task_time_limit"
    _, details = decode_document_error(document_failures[0]["error_message"])
    assert details is not None and details["code"] == "task_time_limit"
    assert details["stage"] == "unknown"


def test_existing_error_details_are_kept(
    captured_jobs: list[Any], document_failures: list[dict[str, Any]]
) -> None:
    exc = SoftTimeLimitExceeded()
    exc.error_details = {  # type: ignore[attr-defined]
        "stage": "ocr",
        "code": "OCR_TIMEOUT",
        "category": "infrastructure",
        "retryable": False,
        "message": "OCR took too long",
    }
    _fail(
        document_tasks.process_document,
        exc,
        {"document_id": str(uuid4())} | {"organization_id": str(uuid4())},
    )
    _, details = decode_document_error(document_failures[0]["error_message"])
    assert details is not None and details["code"] == "OCR_TIMEOUT"
    assert captured_jobs[0].error_code == "task_soft_time_limit"


def test_other_failures_keep_the_exception_class_as_error_code(
    captured_jobs: list[Any], document_failures: list[dict[str, Any]]
) -> None:
    _fail(
        document_tasks.process_document,
        RuntimeError("boom"),
        {"document_id": str(uuid4()), "organization_id": str(uuid4())},
    )
    assert captured_jobs[0].error_code == "RuntimeError"
    _, details = decode_document_error(document_failures[0]["error_message"])
    assert details is not None and details["code"] == "UNEXPECTED_ERROR"


def test_failed_job_queue_drops_the_delayed_delivery_prefix(captured_jobs: list[Any]) -> None:
    # Quorum mode: a task retried with a countdown is delivered with a 28-bit delay prefix on
    # its routing key; the FailedJob row must name the queue, not the prefixed key.
    from app.workers import email_tasks

    task = email_tasks.send_transactional_email
    prefixed = "0." * 27 + "1.email"
    for routing_key, expected in ((prefixed, "email"), ("email", "email"), (None, None)):
        task.push_request(id="task-q", retries=1, delivery_info={"routing_key": routing_key})
        try:
            task.on_failure(
                RuntimeError("boom"), "task-q", (), {"organization_id": str(uuid4())}, None
            )
        finally:
            task.pop_request()
        assert captured_jobs[-1].queue_name == expected
    assert base_task._delivered_queue(None) is None


def test_time_limit_counter_records_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: True)
    before = metrics_workers.CELERY_TASK_TIME_LIMIT_TOTAL.labels(
        task="t.limit", kind="hard"
    )._value.get()
    metrics_workers.record_task_time_limit("t.limit", "hard")
    after = metrics_workers.CELERY_TASK_TIME_LIMIT_TOTAL.labels(task="t.limit", kind="hard")
    assert after._value.get() == before + 1


def test_forked_child_drops_the_inherited_loop_and_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import session as db_session_module
    from app.workers import async_runtime

    disposed: list[bool] = []

    async def _dispose(close: bool = True) -> None:
        disposed.append(close)

    async def _neo4j() -> None:
        return None

    inherited = async_runtime.get_worker_loop()
    monkeypatch.setattr(db_session_module, "engine", SimpleNamespace(dispose=_dispose))
    monkeypatch.setattr(celery_app_module, "init_neo4j", _neo4j)
    monkeypatch.setattr(celery_app_module, "init_sentry", lambda **_: None)
    celery_app_module._initialize_worker()
    assert disposed == [False]
    assert async_runtime.get_worker_loop() is not inherited
    assert not inherited.is_closed()  # the parent's loop is left alone
