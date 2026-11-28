"""Prometheus series for read-replica routing of reporting routes (0.8.0, R08-04).

``rudix_db_replica_lag_seconds`` itself lives in ``metrics_infra`` (S1); this module adds the
routing counter. Labels are fixed values: ``target`` is ``replica`` or ``primary``, ``reason``
is ``ok``, ``replica_unset``, ``lag_exceeded``, or ``sample_failed``.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import Counter

from app.core.metrics import is_metrics_enabled, registry

RouteTarget = Literal["replica", "primary"]
RouteReason = Literal["ok", "replica_unset", "lag_exceeded", "sample_failed"]

DB_REPLICA_ROUTED_TOTAL = Counter(
    "rudix_db_replica_routed_total",
    "Reporting sessions by the database they were routed to and why",
    ["target", "reason"],
    registry=registry,
)


def record_replica_route(target: RouteTarget, reason: RouteReason) -> None:
    if not is_metrics_enabled():
        return
    DB_REPLICA_ROUTED_TOTAL.labels(target=target, reason=reason).inc()
