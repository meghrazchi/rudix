"""Queue wait and queue depth metrics (R06-04, R06-05)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
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
from celery.signals import before_task_publish, task_received
from kombu.transport.native_delayed_delivery import calculate_routing_key

from app.core import metrics_workers
from app.core.config import settings
from app.workers import queue_metrics
from app.workers.celery_app import celery_app
from app.workers.queue_metrics import (
    PUBLISHED_AT_HEADER,
    QueueDepthSampler,
    observe_received_request,
    queue_label,
    queue_wait_seconds,
    sample_queue_depths,
    stamp_published_at,
)


@pytest.fixture
def metrics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: True)


def _histogram_count(queue: str) -> float:
    for metric in metrics_workers.CELERY_QUEUE_WAIT_SECONDS.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count") and sample.labels.get("queue") == queue:
                return sample.value
    return 0.0


class FakeRequest:
    def __init__(self, headers: dict[str, Any], routing_key: str, eta: Any = None) -> None:
        self.request_dict = headers
        self.delivery_info = {"routing_key": routing_key}
        self.eta = eta


# ── publish stamp and wait ─────────────────────────────────────────────────────────────


def test_publish_stamp_is_overwritten_on_every_publish() -> None:
    headers: dict[str, Any] = {PUBLISHED_AT_HEADER: 1.0}
    stamp_published_at(headers, now=lambda: 1234.5)
    assert headers[PUBLISHED_AT_HEADER] == 1234.5
    stamp_published_at(None)  # protocol 1 or no headers: ignored


def test_before_task_publish_signal_stamps_headers() -> None:
    headers: dict[str, Any] = {}
    before_task_publish.send(sender="documents.process", headers=headers, body=())
    assert isinstance(headers[PUBLISHED_AT_HEADER], float)


def test_published_stamp_reaches_the_message_headers() -> None:
    message = celery_app.amqp.create_task_message("t-1", "documents.process", (), {})
    headers = dict(message.headers)
    before_task_publish.send(sender="documents.process", headers=headers, body=message.body)
    assert PUBLISHED_AT_HEADER in headers


def test_queue_label_strips_the_delay_prefix_and_bounds_cardinality() -> None:
    known = ["documents.processing", "default"]
    assert queue_label("documents.processing", known) == "documents.processing"
    delayed = calculate_routing_key(30, "documents.processing")
    assert queue_label(delayed, known) == "documents.processing"
    assert queue_label("someone.elses.queue", known) == "other"
    assert queue_label(None, known) == "other"
    assert queue_label("", known) == "other"


def test_queue_wait_uses_the_later_of_publication_and_eta() -> None:
    headers = {PUBLISHED_AT_HEADER: 100.0}
    assert queue_wait_seconds(headers, None, now=lambda: 112.5) == 12.5
    eta = datetime.fromtimestamp(150.0, tz=UTC)
    assert queue_wait_seconds(headers, eta, now=lambda: 152.0) == 2.0
    assert queue_wait_seconds(headers, eta.isoformat(), now=lambda: 152.0) == 2.0
    assert queue_wait_seconds(headers, "not a date", now=lambda: 112.0) == 12.0
    assert queue_wait_seconds({}, None) is None
    assert queue_wait_seconds({PUBLISHED_AT_HEADER: True}, None) is None
    assert queue_wait_seconds({PUBLISHED_AT_HEADER: "garbage"}, None) is None
    # Clock skew never yields a negative wait.
    assert queue_wait_seconds(headers, None, now=lambda: 90.0) == 0.0


def test_received_request_records_the_wait_histogram(metrics_on: None) -> None:
    before = _histogram_count("documents.processing")
    observe_received_request(
        FakeRequest({PUBLISHED_AT_HEADER: 10.0}, "documents.processing"), now=lambda: 13.0
    )
    assert _histogram_count("documents.processing") == before + 1
    # No stamp (a message published by an older release): nothing recorded.
    observe_received_request(FakeRequest({}, "documents.processing"))
    observe_received_request(object())
    assert _histogram_count("documents.processing") == before + 1


def test_task_received_signal_observes_and_never_raises(
    metrics_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _histogram_count("default")
    task_received.send(
        sender=None,
        request=FakeRequest({PUBLISHED_AT_HEADER: 1.0}, settings.celery_task_default_queue),
    )
    assert _histogram_count("default") == before + 1

    def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr(queue_metrics, "observe_received_request", _boom)
    task_received.send(sender=None, request=None)


def test_metrics_disabled_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: False)
    before = _histogram_count("evaluations")
    metrics_workers.record_queue_wait("evaluations", 1.0)
    metrics_workers.set_queue_depth("evaluations", 99, 1)
    assert _histogram_count("evaluations") == before


# ── depth sampling ─────────────────────────────────────────────────────────────────────


class FakeChannel:
    def __init__(self, depths: dict[str, tuple[int, int]], log: list[str]) -> None:
        self.depths = depths
        self.log = log
        self.closed = False

    def queue_declare(self, *, queue: str, passive: bool) -> tuple[str, int, int]:
        assert passive is True
        self.log.append(queue)
        if queue not in self.depths:
            self.closed = True
            raise RuntimeError("NOT_FOUND - no queue")
        depth, consumers = self.depths[queue]
        return queue, depth, consumers

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, depths: dict[str, tuple[int, int]]) -> None:
        self.depths = depths
        self.channels: list[FakeChannel] = []
        self.declared: list[str] = []

    def channel(self) -> FakeChannel:
        channel = FakeChannel(self.depths, self.declared)
        self.channels.append(channel)
        return channel

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _gauge(gauge: Any, queue: str) -> float:
    return float(gauge.labels(queue=queue)._value.get())


def test_sample_sets_depth_and_survives_a_missing_queue(metrics_on: None) -> None:
    connection = FakeConnection({"default": (3, 2), "rudix.dead_letter": (1, 1)})
    result = sample_queue_depths(connection, ["default", "missing.queue", "rudix.dead_letter"])
    assert result == {"default": 3, "missing.queue": None, "rudix.dead_letter": 1}
    assert connection.declared == ["default", "missing.queue", "rudix.dead_letter"]
    assert len(connection.channels) == 2  # a 404 closes the channel; a new one continues
    assert all(channel.closed for channel in connection.channels)
    assert _gauge(metrics_workers.CELERY_QUEUE_DEPTH, "default") == 3
    assert _gauge(metrics_workers.CELERY_QUEUE_CONSUMERS, "default") == 2
    assert _gauge(metrics_workers.CELERY_QUEUE_DEPTH, "rudix.dead_letter") == 1


class FakeTimer:
    def __init__(self) -> None:
        self.calls: list[tuple[float, Any, tuple[Any, ...]]] = []
        self.cancelled = False

    def call_repeatedly(self, secs: float, fun: Any, args: tuple[Any, ...], priority: int) -> Any:
        self.calls.append((secs, fun, args))
        return self

    def cancel(self) -> None:
        self.cancelled = True


class FakeApp:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def connection_for_read(self) -> Any:
        if isinstance(self.connection, Exception):
            raise self.connection
        return self.connection


class FakeConsumer:
    def __init__(self, connection: Any) -> None:
        self.timer = FakeTimer()
        self.app = FakeApp(connection)


def test_sampler_bootstep_runs_on_the_consumer_timer(
    metrics_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "celery_queue_type", "quorum")
    names = {name: (0, 1) for name in queue_metrics.sampled_queue_names(settings)}
    consumer = FakeConsumer(FakeConnection(names))
    step = QueueDepthSampler(consumer)
    monkeypatch.setattr(settings, "worker_sample_queue_depth", False)
    assert step.include_if(consumer) is False
    monkeypatch.setattr(settings, "worker_sample_queue_depth", True)
    assert step.include_if(consumer) is True

    step.start(consumer)
    [(secs, fun, args)] = consumer.timer.calls
    assert secs == settings.worker_queue_sample_interval_seconds
    result = fun(*args)
    assert set(result) == set(names) and settings.celery_dead_letter_queue in result
    step.stop(consumer)
    assert consumer.timer.cancelled and step.tref is None
    step.stop(consumer)  # idempotent


def test_sampler_swallows_broker_errors() -> None:
    step = QueueDepthSampler(FakeConsumer(OSError("broker down")))
    assert step.sample(FakeConsumer(OSError("broker down"))) == {}
