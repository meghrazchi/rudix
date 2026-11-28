"""Operational beat tasks (0.8.0).

``ops.beat.heartbeat`` (R08-09, deferred from R02-03) runs every
``BEAT_HEARTBEAT_INTERVAL_SECONDS`` on the default queue. Each run sets
``rudix_beat_heartbeat_timestamp_seconds`` to the current Unix time and increments
``rudix_beat_heartbeats_total``, so the ``RudixBeatHeartbeatStale`` and
``RudixBeatHeartbeatMissing`` alerts (``infra/observability/prometheus/rules/beat.yml``) fire
when beat stops scheduling or no default-pool worker runs its tasks. The message expires
after one interval: a backlog of old heartbeats can never make a late worker look healthy.
The task touches no database, broker, or tenant data and is safe to run any number of times.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.core.logging import get_logger
from app.core.metrics_infra import record_beat_heartbeat
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

logger = get_logger("workers.ops")

BEAT_HEARTBEAT_TASK = "ops.beat.heartbeat"

# Indirection so tests can pin the clock.
clock: Callable[[], float] = time.time


def beat_heartbeat() -> float:
    """Record one heartbeat and return its Unix timestamp."""
    now = clock()
    record_beat_heartbeat(now)
    logger.debug("ops.beat.heartbeat", timestamp=round(now, 3))
    return now


@celery_app.task(name=BEAT_HEARTBEAT_TASK, bind=True, base=RudixTask, ignore_result=True)
def beat_heartbeat_task(self: RudixTask) -> float:
    """Beat liveness signal for Prometheus (see module docstring)."""
    return beat_heartbeat()
