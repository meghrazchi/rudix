"""Queue wait and queue depth metrics (R06-04, R06-05; C1).

- ``before_task_publish`` stamps every published task with ``rudix_published_at`` (Unix
  seconds, publisher clock); every publish, retries included, overwrites it.
- ``task_received`` observes ``rudix_celery_queue_wait_seconds{queue}`` = receive time minus
  the later of the publication time and the ETA. It fires in the worker's main process, the
  one that serves ``WORKER_METRICS_PORT``; ``task_prerun`` runs in a prefork child whose
  registry that server never reads. With ``acks_late`` and prefetch multiplier 1 a message is
  received only when a child is free, so receive time is the start of execution.
- ``QueueDepthSampler`` is a consumer bootstep (main process, enabled by
  ``WORKER_SAMPLE_QUEUE_DEPTH``, which the default pool sets) that runs a passive
  ``queue_declare`` per queue every ``WORKER_QUEUE_SAMPLE_INTERVAL_SECONDS`` and sets
  ``rudix_celery_queue_depth{queue}`` and ``rudix_celery_queue_consumers{queue}``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from celery import bootsteps  # type: ignore[import-untyped]
from celery.signals import before_task_publish, task_received  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_queue_wait, set_queue_depth
from app.workers.queues import sampled_queue_names, strip_delay_prefix

logger = get_logger("worker.queue_metrics")

PUBLISHED_AT_HEADER = "rudix_published_at"
OTHER_QUEUE_LABEL = "other"


def stamp_published_at(headers: Any, now: Callable[[], float] = time.time) -> None:
    if isinstance(headers, dict):
        headers[PUBLISHED_AT_HEADER] = round(now(), 6)


def queue_label(routing_key: Any, known: Iterable[str]) -> str:
    if not isinstance(routing_key, str) or not routing_key:
        return OTHER_QUEUE_LABEL
    # The delay prefix is stripped so the label stays one of the queue names.
    name = strip_delay_prefix(routing_key)
    return name if name in set(known) else OTHER_QUEUE_LABEL


def _as_timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def queue_wait_seconds(
    headers: dict[str, Any], eta: Any, now: Callable[[], float] = time.time
) -> float | None:
    """Wait from publication (or the ETA, when later) to now; ``None`` without a stamp."""
    published = _as_timestamp(headers.get(PUBLISHED_AT_HEADER))
    if published is None:
        return None
    start = published
    eta_ts = _as_timestamp(eta)
    if eta_ts is not None and eta_ts > start:
        start = eta_ts
    return max(now() - start, 0.0)


def observe_received_request(request: Any, now: Callable[[], float] = time.time) -> None:
    """Record the queue wait of a received worker request (``celery.worker.request``)."""
    headers = getattr(request, "request_dict", None)
    if not isinstance(headers, dict):
        return
    wait = queue_wait_seconds(headers, getattr(request, "eta", None), now=now)
    if wait is None:
        return
    delivery_info = getattr(request, "delivery_info", None) or {}
    label = queue_label(delivery_info.get("routing_key"), sampled_queue_names(settings))
    record_queue_wait(label, wait)


@before_task_publish.connect
def _on_before_task_publish(*_: object, headers: Any = None, **__: object) -> None:
    stamp_published_at(headers)


@task_received.connect
def _on_task_received(*_: object, request: Any = None, **__: object) -> None:
    try:
        observe_received_request(request)
    except Exception as exc:  # metrics never fail a delivery
        logger.debug("queue_metrics.wait_failed", error_type=type(exc).__name__)


def sample_queue_depths(connection: Any, names: Iterable[str]) -> dict[str, int | None]:
    """Passive ``queue_declare`` per queue; a missing queue (404 closes the channel) is
    reported as ``None`` and sampling continues on a new channel."""
    results: dict[str, int | None] = {}
    channel = connection.channel()
    try:
        for name in names:
            try:
                _, depth, consumers = channel.queue_declare(queue=name, passive=True)
            except Exception as exc:
                results[name] = None
                logger.warning(
                    "workers.queue_depth_unavailable", queue=name, error_type=type(exc).__name__
                )
                _close_quietly(channel)
                channel = connection.channel()
                continue
            results[name] = int(depth)
            set_queue_depth(name, int(depth), int(consumers))
    finally:
        _close_quietly(channel)
    return results


def _close_quietly(channel: Any) -> None:
    try:
        channel.close()
    except Exception as exc:
        logger.debug("queue_metrics.channel_close_failed", error_type=type(exc).__name__)


class QueueDepthSampler(bootsteps.StartStopStep):  # type: ignore[misc]
    """Consumer bootstep sampling queue depth on the consumer's timer (main process)."""

    requires = ("celery.worker.consumer.tasks:Tasks",)

    def __init__(self, parent: Any, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.tref: Any = None

    def include_if(self, parent: Any) -> bool:
        return bool(settings.worker_sample_queue_depth)

    def start(self, parent: Any) -> None:
        self.tref = parent.timer.call_repeatedly(
            settings.worker_queue_sample_interval_seconds, self.sample, (parent,), priority=10
        )

    def stop(self, parent: Any) -> None:
        if self.tref is not None:
            self.tref.cancel()
            self.tref = None

    def sample(self, parent: Any) -> dict[str, int | None]:
        try:
            with parent.app.connection_for_read() as connection:
                return sample_queue_depths(connection, sampled_queue_names(settings))
        except Exception as exc:
            logger.warning("workers.queue_depth_sample_failed", error_type=type(exc).__name__)
            return {}
