"""Retention and partition maintenance metrics (R04-09).

* ``rudix_retention_rows_deleted_total{table}``: rows removed by ``maintenance.retention.purge``.
* ``rudix_partition_missing{table}``: 1 when a partitioned table has no partition for next
  month, 0 once it exists. Only tables that are already partitioned report a sample; no
  application table is partitioned today, so the gauge has no samples until a conversion.

Kept out of ``app.core.metrics`` (already over the module size guideline); both use the same
registry.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge

from app.core.metrics import is_metrics_enabled, registry

logger = logging.getLogger(__name__)

RETENTION_ROWS_DELETED_TOTAL = Counter(
    "rudix_retention_rows_deleted_total",
    "Rows deleted by the retention purge task, by table",
    ["table"],
    registry=registry,
)

PARTITION_MISSING = Gauge(
    "rudix_partition_missing",
    "1 when a partitioned table has no partition for next month, else 0",
    ["table"],
    registry=registry,
)


def record_retention_rows_deleted(table: str, count: int) -> None:
    if count <= 0 or not is_metrics_enabled():
        return
    try:
        RETENTION_ROWS_DELETED_TOTAL.labels(table=table).inc(count)
    except Exception as exc:  # pragma: no cover - prometheus_client does not raise here
        logger.debug("metrics.record_retention_rows_deleted_failed: %s", exc)


def set_partition_missing(table: str, missing: bool) -> None:
    if not is_metrics_enabled():
        return
    try:
        PARTITION_MISSING.labels(table=table).set(1 if missing else 0)
    except Exception as exc:  # pragma: no cover - prometheus_client does not raise here
        logger.debug("metrics.set_partition_missing_failed: %s", exc)
