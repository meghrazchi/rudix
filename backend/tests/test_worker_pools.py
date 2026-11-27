"""Worker pools per queue (R06-04)."""

from __future__ import annotations

import os
import sys
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

from app.core.config import Settings, settings
from app.core.settings.worker_platform import parse_queue_list
from app.workers import pools
from app.workers.pools import (
    POOL_NAMES,
    PoolConfigError,
    PoolSpec,
    build_worker_argv,
    build_worker_env,
    pool_spec,
)
from app.workers.queues import task_queue_names


def _config(**overrides: Any) -> Settings:
    return settings.model_copy(update=overrides)


def test_five_pools_with_default_queues() -> None:
    assert POOL_NAMES == ("ingest", "graph", "sync", "eval", "default")
    specs = {name: pool_spec(name, settings) for name in POOL_NAMES}
    assert specs["ingest"].queues == (
        "documents.processing",
        "documents.deletion",
        "documents.reindex",
    )
    assert specs["graph"].queues == ("documents.graph",)
    assert specs["sync"].queues == ("connectors.sync",)
    assert specs["eval"].queues == ("evaluations",)
    assert specs["default"].queues == ("default", "email")
    assert specs["eval"].concurrency == 1
    assert all(spec.pool == "prefork" for spec in specs.values())
    assert all(spec.max_tasks_per_child == 200 for spec in specs.values())


def test_pools_together_consume_every_declared_queue() -> None:
    consumed = {queue for name in POOL_NAMES for queue in pool_spec(name, settings).queues}
    assert consumed == set(task_queue_names(settings))


def test_pool_settings_override_queues_concurrency_and_recycling() -> None:
    config = _config(
        worker_pool_ingest_queues=" documents.processing , documents.embedding,,",
        worker_pool_ingest_concurrency=6,
        worker_pool_ingest_max_tasks_per_child=0,
        worker_pool_graph_max_tasks_per_child=50,
        worker_pool_sync_pool="threads",
        worker_pool_sync_concurrency=1,
    )
    ingest = pool_spec("ingest", config)
    assert ingest.queues == ("documents.processing", "documents.embedding")
    assert ingest.concurrency == 6
    assert ingest.max_tasks_per_child is None
    assert pool_spec("graph", config).max_tasks_per_child == 50
    assert pool_spec("sync", config).pool == "threads"


def test_embedding_queue_joins_the_ingest_pool_when_separate() -> None:
    config = _config(celery_queue_documents_embedding="documents.embedding")
    assert "documents.embedding" in pool_spec("ingest", config).queues


def test_threads_pool_needs_concurrency_one() -> None:
    config = _config(worker_pool_graph_pool="threads", worker_pool_graph_concurrency=4)
    with pytest.raises(PoolConfigError, match="WORKER_POOL_GRAPH_POOL=threads"):
        pool_spec("graph", config)


def test_unknown_pool_is_rejected() -> None:
    with pytest.raises(PoolConfigError, match="unknown worker pool"):
        pool_spec("gpu", settings)


def test_worker_argv() -> None:
    spec = PoolSpec(
        name="ingest",
        queues=("documents.processing", "documents.deletion"),
        concurrency=3,
        pool="prefork",
        max_tasks_per_child=200,
    )
    assert build_worker_argv(spec) == [
        "celery",
        "-A",
        "app.workers.celery_app:celery_app",
        "worker",
        "-Q",
        "documents.processing,documents.deletion",
        "--concurrency",
        "3",
        "--pool",
        "prefork",
        "-n",
        "ingest@%h",
        "--loglevel=INFO",
        "--max-tasks-per-child",
        "200",
    ]
    no_recycle = PoolSpec("eval", ("evaluations",), 1, "prefork", None)
    argv = build_worker_argv(no_recycle, loglevel="DEBUG")
    assert "--max-tasks-per-child" not in argv
    assert argv[-1] == "--loglevel=DEBUG"


def test_only_the_default_pool_runs_the_main_process_bootsteps() -> None:
    env = build_worker_env("default", {"PATH": "/bin"})
    assert env["WORKER_CONSUME_DEAD_LETTER"] == "true"
    assert env["WORKER_SAMPLE_QUEUE_DEPTH"] == "true"
    assert env["PATH"] == "/bin"
    other = build_worker_env("ingest", {})
    assert other["WORKER_CONSUME_DEAD_LETTER"] == "false"
    assert other["WORKER_SAMPLE_QUEUE_DEPTH"] == "false"
    explicit = build_worker_env("default", {"WORKER_CONSUME_DEAD_LETTER": "false"})
    assert explicit["WORKER_CONSUME_DEAD_LETTER"] == "false"


def test_main_execs_celery_with_the_pool_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        pools.os, "execvpe", lambda file, args, env: calls.append((file, list(args), env))
    )
    monkeypatch.setenv("WORKER_LOG_LEVEL", "WARNING")
    assert pools.main(["graph"]) == 0
    [(file, argv, env)] = calls
    assert file == sys.executable
    assert argv[:3] == [sys.executable, "-m", "celery"]
    assert argv[argv.index("-Q") + 1] == "documents.graph"
    assert argv[argv.index("-n") + 1] == "graph@%h"
    assert "--loglevel=WARNING" in argv
    assert env["WORKER_CONSUME_DEAD_LETTER"] == "false"


def test_main_usage_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pools.os, "execvpe", lambda *a: pytest.fail("must not exec"))
    assert pools.main([]) == 2
    assert "usage" in capsys.readouterr().err
    assert pools.main(["nope"]) == 2
    assert "unknown worker pool" in capsys.readouterr().err


def test_parse_queue_list() -> None:
    assert parse_queue_list(None) == []
    assert parse_queue_list("a, b,a,,c ") == ["a", "b", "c"]
