"""Prometheus metrics for the realtime event stream (R07-07).

Registered on the shared registry of ``app.core.metrics``. Labels are the fixed event types
and outcomes, never ids or request data.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge

from app.core.metrics import is_metrics_enabled, registry

logger = logging.getLogger(__name__)

REALTIME_CONNECTIONS = Gauge(
    "rudix_realtime_connections",
    "Open realtime event streams in this process",
    registry=registry,
)
# outcome: published, failed (Redis error), unavailable (no Redis client), skipped (no async
# context to publish from).
REALTIME_EVENTS_PUBLISHED_TOTAL = Counter(
    "rudix_realtime_events_published_total",
    "Realtime events published to Redis by type and outcome",
    ["type", "outcome"],
    registry=registry,
)
REALTIME_EVENTS_DELIVERED_TOTAL = Counter(
    "rudix_realtime_events_delivered_total",
    "Realtime events written to a client stream by type",
    ["type"],
    registry=registry,
)
REALTIME_RECONNECTS_TOTAL = Counter(
    "rudix_realtime_reconnects_total",
    "Realtime streams opened with a Last-Event-ID header",
    registry=registry,
)


def record_realtime_published(event_type: str, outcome: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        REALTIME_EVENTS_PUBLISHED_TOTAL.labels(type=event_type, outcome=outcome).inc()
    except Exception as exc:  # pragma: no cover - prometheus label errors only
        logger.debug("metrics.realtime_published_failed: %s", exc)


def record_realtime_delivered(event_type: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        REALTIME_EVENTS_DELIVERED_TOTAL.labels(type=event_type).inc()
    except Exception as exc:  # pragma: no cover - prometheus label errors only
        logger.debug("metrics.realtime_delivered_failed: %s", exc)


def record_realtime_reconnect() -> None:
    if is_metrics_enabled():
        REALTIME_RECONNECTS_TOTAL.inc()


def realtime_connection_opened() -> None:
    if is_metrics_enabled():
        REALTIME_CONNECTIONS.inc()


def realtime_connection_closed() -> None:
    if is_metrics_enabled():
        REALTIME_CONNECTIONS.dec()
