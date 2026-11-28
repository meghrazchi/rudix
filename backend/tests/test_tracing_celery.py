"""Celery trace propagation through message headers (R08-10).

A task is published through kombu's in-memory transport; the message carries
``traceparent``; an in-thread worker (``celery.contrib.testing.worker.start_worker``) runs it
and the consumer span continues the publisher's trace as a child of the publish span.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from app.core import tracing
from app.core.tracing_context import operation_span
from app.workers import celery_app as celery_module
from tests.tracing_support import tracing_session

TASK_NAME = "tests.tracing.echo"
QUEUE = "tracing-test"


def _celery_app() -> Celery:
    app = Celery("tracing-test", broker="memory://", backend="cache+memory://")
    app.conf.update(
        task_default_queue=QUEUE,
        task_serializer="json",
        accept_content=["json"],
        broker_connection_retry_on_startup=False,
    )
    return app


def test_publish_carries_traceparent_and_worker_span_is_a_child() -> None:
    app = _celery_app()
    done = threading.Event()
    seen: dict[str, Any] = {}

    @app.task(name=TASK_NAME)
    def echo(value: str) -> str:
        context = trace.get_current_span().get_span_context()
        seen["trace_id"] = context.trace_id
        done.set()
        return value

    with tracing_session("worker") as exporter:
        with operation_span("rudix.test.request", kind=SpanKind.SERVER) as parent:
            assert parent is not None
            echo.apply_async(args=["hello"], queue=QUEUE)
            request_trace_id = parent.get_span_context().trace_id

        # The message on the broker carries the W3C context.
        with app.connection_for_read() as conn:
            queue = conn.SimpleQueue(QUEUE)
            message = queue.get(timeout=2)
            traceparent = message.headers.get("traceparent")
            assert traceparent is not None
            assert traceparent.split("-")[1] == format(request_trace_id, "032x")
            message.requeue()
            queue.close()

        with start_worker(app, queues=[QUEUE], perform_ping_check=False, pool="solo"):
            assert done.wait(10), "worker did not run the task"

    spans = exporter.get_finished_spans()
    publish = next(s for s in spans if s.kind == SpanKind.PRODUCER)
    run = next(s for s in spans if s.kind == SpanKind.CONSUMER)
    assert publish.context.trace_id == request_trace_id
    assert run.context.trace_id == request_trace_id == seen["trace_id"]
    assert run.parent is not None and run.parent.span_id == publish.context.span_id
    assert run.attributes is not None
    assert run.attributes.get("celery.task_name") == TASK_NAME
    assert run.attributes.get("celery.action") == "run"
    # Task arguments never reach the exported attributes.
    for span in (publish, run):
        assert "hello" not in str(dict(span.attributes or {}))


def test_worker_process_init_installs_tracing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tracing, "init_tracing", lambda runtime: calls.append(runtime) or True)
    celery_module._init_worker_tracing()
    assert calls == ["worker"]

    def broken(runtime: str) -> bool:
        raise RuntimeError(runtime)

    monkeypatch.setattr(tracing, "init_tracing", broken)
    with caplog.at_level(logging.WARNING):
        celery_module._init_worker_tracing()
    assert any("worker.tracing_init_failed" in r.getMessage() for r in caplog.records)


def test_worker_shutdown_flushes_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    shutdown = MagicMock()
    monkeypatch.setattr(tracing, "shutdown_tracing", shutdown)
    monkeypatch.setattr("app.workers.async_runtime.run_async", MagicMock())
    monkeypatch.setattr("app.clients.qdrant_client.close_qdrant", MagicMock())
    monkeypatch.setattr(celery_module, "_mark_metrics_process_dead", MagicMock())
    celery_module._shutdown_worker()
    shutdown.assert_called_once_with()


def test_worker_disabled_tracing_is_a_no_op() -> None:
    assert tracing.tracer_provider() is None
    celery_module._init_worker_tracing()  # TRACING_ENABLED=false in tests
    assert tracing.tracer_provider() is None
