"""Prometheus metrics for ingestion and workers introduced in 0.6.0 (R06-xx).

Uses the shared ``registry`` of ``app.core.metrics``. Each later work package adds its
metrics and helpers directly after its ``# anchor: <task>`` marker. Labels are fixed
names, never request or document data.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Histogram

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
# R06-06: chunks of an embed batch whose vector was reused from the vector index (hit) or
# sent to the embedding provider (miss).
EMBEDDING_CACHE_HITS_TOTAL = Counter(
    "rudix_embedding_cache_hits_total",
    "Embed-stage chunks by vector reuse outcome (hit = reused, miss = embedded)",
    ["outcome"],
    registry=registry,
)


def record_embedding_cache(hits: int, misses: int) -> None:
    if not is_metrics_enabled():
        return
    try:
        if hits:
            EMBEDDING_CACHE_HITS_TOTAL.labels(outcome="hit").inc(hits)
        if misses:
            EMBEDDING_CACHE_HITS_TOTAL.labels(outcome="miss").inc(misses)
    except Exception as exc:
        logger.debug("metrics.embedding_cache_failed: %s", exc)


# anchor: A2
# R06-08: fraction of indexed documents (all organisations) a building generation holds.
# Metrics only; the admin API reports the caller's organisation and never this value.
REINDEX_PROGRESS = Gauge(
    "rudix_reindex_progress",
    "Fraction of indexed documents written to a building vector index generation",
    ["generation"],
    registry=registry,
)


def record_reindex_progress(generation: int, done: int, total: int) -> None:
    if not is_metrics_enabled():
        return
    try:
        fraction = 1.0 if total <= 0 else min(max(done / total, 0.0), 1.0)
        REINDEX_PROGRESS.labels(generation=str(int(generation))).set(fraction)
    except Exception as exc:
        logger.debug("metrics.reindex_progress_failed: %s", exc)


# anchor: A3

# anchor: B1
# R06-09: chunk rows the tenant backfill updated. R06-10: graph UNWIND write transactions,
# by kind (entity, alias, evidence, relation) and outcome (written, failed).
CHUNK_BACKFILL_ROWS_TOTAL = Counter(
    "rudix_chunk_backfill_rows_total",
    "document_chunks rows given organization_id and fts_vector by the tenant backfill",
    registry=registry,
)
GRAPH_WRITE_BATCHES_TOTAL = Counter(
    "rudix_graph_write_batches_total",
    "Neo4j batched write transactions by kind and outcome",
    ["kind", "outcome"],
    registry=registry,
)


def record_chunk_backfill_rows(count: int) -> None:
    if count <= 0 or not is_metrics_enabled():
        return
    try:
        CHUNK_BACKFILL_ROWS_TOTAL.inc(count)
    except Exception as exc:
        logger.debug("metrics.chunk_backfill_rows_failed: %s", exc)


def record_graph_write_batch(kind: str, outcome: str) -> None:
    _inc(GRAPH_WRITE_BATCHES_TOTAL, kind=kind, outcome=outcome)


# anchor: C1
# R06-03, R06-05 and queue metrics. ``queue`` is a configured queue name (or ``other``),
# never a routing key with a delay prefix. Both queue metrics are recorded in the worker's
# main process (task_received signal, sampler timer), which serves WORKER_METRICS_PORT.
CELERY_QUEUE_WAIT_SECONDS = Histogram(
    "rudix_celery_queue_wait_seconds",
    "Seconds from publication (or ETA) to a worker receiving the task, by queue",
    ["queue"],
    buckets=(0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
    registry=registry,
)
CELERY_QUEUE_DEPTH = Gauge(
    "rudix_celery_queue_depth",
    "Ready messages per queue from a passive queue_declare (dead-letter queue included)",
    ["queue"],
    registry=registry,
)
CELERY_QUEUE_CONSUMERS = Gauge(
    "rudix_celery_queue_consumers",
    "Consumers per queue from a passive queue_declare",
    ["queue"],
    registry=registry,
)
# kind: soft or hard.
CELERY_TASK_TIME_LIMIT_TOTAL = Counter(
    "rudix_celery_task_time_limit_total",
    "Tasks stopped by their soft or hard time limit",
    ["task", "kind"],
    registry=registry,
)
# outcome: recorded, duplicate, no_tenant, malformed, error.
DEAD_LETTER_MESSAGES_TOTAL = Counter(
    "rudix_dead_letter_messages_total",
    "Messages read from the dead-letter queue, by outcome",
    ["outcome"],
    registry=registry,
)


def record_queue_wait(queue: str, seconds: float) -> None:
    if not is_metrics_enabled():
        return
    try:
        CELERY_QUEUE_WAIT_SECONDS.labels(queue=queue).observe(max(seconds, 0.0))
    except Exception as exc:
        logger.debug("metrics.record_queue_wait_failed: %s", exc)


def set_queue_depth(queue: str, depth: int, consumers: int) -> None:
    if not is_metrics_enabled():
        return
    try:
        CELERY_QUEUE_DEPTH.labels(queue=queue).set(depth)
        CELERY_QUEUE_CONSUMERS.labels(queue=queue).set(consumers)
    except Exception as exc:
        logger.debug("metrics.set_queue_depth_failed: %s", exc)


def record_task_time_limit(task: str, kind: str) -> None:
    _inc(CELERY_TASK_TIME_LIMIT_TOTAL, task=task, kind=kind)


def record_dead_letter_message(outcome: str) -> None:
    _inc(DEAD_LETTER_MESSAGES_TOTAL, outcome=outcome)


# anchor: C2

# anchor: D1
# R06-11: provider rate limits seen by a sync run (outcome: inline = slept and retried the
# page, requeued = checkpointed and re-enqueued with the Retry-After countdown), runs held
# back or re-enqueued (reason: org_cap, connection_cap, lease_held, stale), and pages
# committed.
CONNECTOR_SYNC_RATE_LIMITED_TOTAL = Counter(
    "rudix_connector_sync_rate_limited_total",
    "Provider rate limits hit by connector sync runs, by provider and outcome",
    ["provider", "outcome"],
    registry=registry,
)
CONNECTOR_SYNC_DEFERRED_TOTAL = Counter(
    "rudix_connector_sync_deferred_total",
    "Connector sync runs deferred or re-enqueued, by reason",
    ["reason"],
    registry=registry,
)
CONNECTOR_SYNC_PAGES_TOTAL = Counter(
    "rudix_connector_sync_pages_total",
    "Connector sync pages committed, by provider and sync mode (full, incremental)",
    ["provider", "mode"],
    registry=registry,
)


def record_connector_sync_rate_limited(provider: str | None, outcome: str) -> None:
    _inc(CONNECTOR_SYNC_RATE_LIMITED_TOTAL, provider=provider or "unknown", outcome=outcome)


def record_connector_sync_deferred(reason: str) -> None:
    _inc(CONNECTOR_SYNC_DEFERRED_TOTAL, reason=reason)


def record_connector_sync_page(provider: str | None, mode: str) -> None:
    _inc(CONNECTOR_SYNC_PAGES_TOTAL, provider=provider or "unknown", mode=mode)
