"""Prometheus metrics for ingestion and workers introduced in 0.6.0 (R06-xx).

Uses the shared ``registry`` of ``app.core.metrics``. Each later work package adds its
metrics and helpers directly after its ``# anchor: <task>`` marker. Labels are fixed
names, never request or document data.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Histogram

from app.core.metrics import is_metrics_enabled, registry

logger = logging.getLogger(__name__)

# R06-01 (S1): one observation per ingestion stage run. ``outcome`` is completed, skipped
# (the stage row was already completed for this run), or failed.
INGEST_STAGE_OUTCOMES = ("completed", "skipped", "failed")
INGEST_STAGE_SECONDS = Histogram(
    "rudix_ingest_stage_seconds",
    "Duration of one ingestion stage run in seconds, by stage and outcome",
    ["stage", "outcome"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0),
    registry=registry,
)


def record_ingest_stage(stage: str, outcome: str, seconds: float) -> None:
    """Observe one stage run; a no-op when ``METRICS_ENABLED`` is false."""
    if not is_metrics_enabled():
        return
    try:
        INGEST_STAGE_SECONDS.labels(stage=stage, outcome=outcome).observe(max(seconds, 0.0))
    except Exception as exc:
        logger.debug("metrics.record_ingest_stage_failed: %s", exc)


# anchor: S2
# R06-01 part 2: stage task outcomes in chain mode (completed, skipped, superseded,
# lease_held, rerun_producer), outbox publications, and tenant mismatches.
INGEST_STAGE_TASKS_TOTAL = Counter(
    "rudix_ingest_stage_tasks_total",
    "Ingestion stage task deliveries by stage and outcome (chain mode)",
    ["stage", "outcome"],
    registry=registry,
)
# outcome: published (immediate), relayed (beat), deferred (publish failed, row pending),
# failed (gave up after OUTBOX_MAX_ATTEMPTS), duplicate (dedupe key existed).
OUTBOX_MESSAGES_TOTAL = Counter(
    "rudix_outbox_messages_total",
    "Transactional outbox rows by task and outcome",
    ["task", "outcome"],
    registry=registry,
)
WORKER_TENANT_MISMATCH_TOTAL = Counter(
    "rudix_worker_tenant_mismatch_total",
    "Tasks stopped because their entity belongs to another organisation",
    ["task"],
    registry=registry,
)


def _inc(counter: Counter, **labels: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        counter.labels(**labels).inc()
    except Exception as exc:
        logger.debug("metrics.worker_counter_failed: %s", exc)


def record_ingest_stage_task(stage: str, outcome: str) -> None:
    _inc(INGEST_STAGE_TASKS_TOTAL, stage=stage, outcome=outcome)


def record_outbox_message(task: str, outcome: str) -> None:
    _inc(OUTBOX_MESSAGES_TOTAL, task=task, outcome=outcome)


def record_worker_tenant_mismatch(task: str) -> None:
    _inc(WORKER_TENANT_MISMATCH_TOTAL, task=task)


# anchor: A1

# anchor: A2

# anchor: A3

# anchor: B1

# anchor: C1

# anchor: C2

# anchor: D1
