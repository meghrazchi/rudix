"""Shared Prometheus gauges for production infrastructure (0.8.0).

Registered on the shared registry of ``app.core.metrics`` so ``/metrics`` exports them. S1
declares the series; B1 (WebSocket connections), B2 (beat heartbeat), A2 (backup freshness),
and C2 (replica lag) set them and may add setters below. Names and labels never change.

``multiprocess_mode`` is explicit on every gauge so prefork workers aggregate them correctly
once multiprocess collection is enabled (B2): ``livesum`` for counts held by live processes,
``max`` for timestamps and lag. Labels are fixed values, never ids or request data.
"""

from __future__ import annotations

from prometheus_client import Gauge

from app.core.metrics import is_metrics_enabled, registry

CHAT_WS_CONNECTIONS = Gauge(
    "rudix_chat_ws_connections",
    "Open chat WebSocket connections in this process",
    registry=registry,
    multiprocess_mode="livesum",
)
BEAT_HEARTBEAT_TIMESTAMP_SECONDS = Gauge(
    "rudix_beat_heartbeat_timestamp_seconds",
    "Unix time of the last Celery beat heartbeat task run",
    registry=registry,
    multiprocess_mode="max",
)
# kind: postgres, qdrant, objects, neo4j (contract 5.2.9).
BACKUP_LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "rudix_backup_last_success_timestamp_seconds",
    "Unix time of the last successful backup by kind, read from the backup marker",
    ["kind"],
    registry=registry,
    multiprocess_mode="max",
)
DB_REPLICA_LAG_SECONDS = Gauge(
    "rudix_db_replica_lag_seconds",
    "Last sampled replication lag of the reporting read replica in seconds",
    registry=registry,
    multiprocess_mode="max",
)


def set_chat_ws_connections(count: int) -> None:
    if not is_metrics_enabled():
        return
    CHAT_WS_CONNECTIONS.set(max(0, count))


def chat_ws_connection_opened() -> None:
    """B1: one chat WebSocket accepted in this process (``livesum`` across processes)."""
    if not is_metrics_enabled():
        return
    CHAT_WS_CONNECTIONS.inc()


def chat_ws_connection_closed() -> None:
    """B1: one accepted chat WebSocket ended in this process."""
    if not is_metrics_enabled():
        return
    CHAT_WS_CONNECTIONS.dec()


def set_beat_heartbeat_timestamp(timestamp_seconds: float) -> None:
    if not is_metrics_enabled():
        return
    BEAT_HEARTBEAT_TIMESTAMP_SECONDS.set(timestamp_seconds)


def set_backup_last_success_timestamp(kind: str, timestamp_seconds: float) -> None:
    if not is_metrics_enabled():
        return
    BACKUP_LAST_SUCCESS_TIMESTAMP_SECONDS.labels(kind=kind).set(timestamp_seconds)


def set_db_replica_lag_seconds(lag_seconds: float) -> None:
    if not is_metrics_enabled():
        return
    DB_REPLICA_LAG_SECONDS.set(max(0.0, lag_seconds))
