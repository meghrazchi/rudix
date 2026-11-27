"""Ingestion and worker settings introduced in 0.6.0 (R06-xx).

Each later work package adds its fields directly after its ``# anchor: <task>`` marker.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.settings.worker_platform import (
    QueueType,
    TaskTimeLimit,
    WorkerPoolKind,
    merge_task_time_limits,
)

_MIB = 1024 * 1024


class WorkersSettings(BaseModel):
    # R06-01 (S1): staged ingestion.
    # A running stage row whose heartbeat is older than this may be leased by another task.
    ingest_stage_lease_seconds: int = Field(default=900, ge=10, le=86_400)
    # Chunks per embedding batch in the embed stage (one artifact part and upsert per batch).
    ingest_embed_batch_chunks: int = Field(default=96, ge=1, le=2048)
    # Upper bound for one compressed stage artifact part.
    ingest_artifact_max_part_bytes: int = Field(default=8 * _MIB, ge=64 * 1024, le=64 * _MIB)

    # anchor: S2
    # R06-01 part 2: ``chain`` runs each stage as its own Celery task; ``inline`` keeps the
    # single-task runner of 0.6.0 part 1 for one milestone.
    ingest_pipeline_mode: Literal["chain", "inline"] = "chain"
    # A stage refreshes ``documents.processing_started_at`` (the reaper's clock) at its
    # start and after every N artifact parts or embed batches.
    ingest_heartbeat_every_parts: int = Field(default=20, ge=1, le=10_000)
    # documents.stage_artifacts.purge deletes artifacts older than this for documents that
    # are not processing (runs that failed for good or were abandoned).
    ingest_stage_artifact_ttl_hours: int = Field(default=72, ge=1, le=24 * 365)
    # Transactional outbox relay (beat task outbox.relay).
    outbox_relay_interval_seconds: int = Field(default=5, ge=1, le=3600)
    outbox_relay_batch_size: int = Field(default=100, ge=1, le=10_000)
    outbox_max_attempts: int = Field(default=10, ge=1, le=1000)

    # anchor: A1

    # anchor: A2

    # anchor: A3

    # anchor: B1

    # anchor: C1
    # R06-03: time limits and child recycling. CELERY_TASK_TIME_LIMITS is a JSON object
    # {task name: {"soft": s, "hard": s}} merged over DEFAULT_TASK_TIME_LIMITS; other tasks
    # use the two defaults. Every hard limit must stay below the broker consumer timeout.
    celery_task_time_limits: dict[str, TaskTimeLimit] = Field(
        default_factory=lambda: merge_task_time_limits(None)
    )
    celery_task_default_soft_time_limit: int = Field(default=300, ge=1, le=7 * 86_400)
    celery_task_default_time_limit: int = Field(default=360, ge=2, le=7 * 86_400)
    # 0 turns recycling off (Celery's default). Memory is resident KiB per child process.
    celery_worker_max_tasks_per_child: int = Field(default=200, ge=0, le=1_000_000)
    celery_worker_max_memory_per_child_kb: int = Field(default=0, ge=0, le=256 * 1024 * 1024)
    # Must equal RabbitMQ's consumer_timeout (infra/rabbitmq/rabbitmq.conf, in ms there).
    celery_broker_consumer_timeout_seconds: int = Field(default=1800, ge=60, le=7 * 86_400)

    # R06-04: worker pools (app.workers.pools). *_QUEUES is comma separated; unset derives the
    # pool's queues from the CELERY_QUEUE_* settings. *_MAX_TASKS_PER_CHILD unset uses
    # CELERY_WORKER_MAX_TASKS_PER_CHILD.
    worker_pool_ingest_queues: str | None = None
    worker_pool_ingest_concurrency: int = Field(default=2, ge=1, le=256)
    worker_pool_ingest_pool: WorkerPoolKind = "prefork"
    worker_pool_ingest_max_tasks_per_child: int | None = Field(default=None, ge=0)
    worker_pool_graph_queues: str | None = None
    worker_pool_graph_concurrency: int = Field(default=2, ge=1, le=256)
    worker_pool_graph_pool: WorkerPoolKind = "prefork"
    worker_pool_graph_max_tasks_per_child: int | None = Field(default=None, ge=0)
    worker_pool_sync_queues: str | None = None
    worker_pool_sync_concurrency: int = Field(default=2, ge=1, le=256)
    worker_pool_sync_pool: WorkerPoolKind = "prefork"
    worker_pool_sync_max_tasks_per_child: int | None = Field(default=None, ge=0)
    worker_pool_eval_queues: str | None = None
    worker_pool_eval_concurrency: int = Field(default=1, ge=1, le=256)
    worker_pool_eval_pool: WorkerPoolKind = "prefork"
    worker_pool_eval_max_tasks_per_child: int | None = Field(default=None, ge=0)
    worker_pool_default_queues: str | None = None
    worker_pool_default_concurrency: int = Field(default=2, ge=1, le=256)
    worker_pool_default_pool: WorkerPoolKind = "prefork"
    worker_pool_default_max_tasks_per_child: int | None = Field(default=None, ge=0)
    # The dead-letter consumer bootstep runs only where this is true; ``python -m
    # app.workers.pools default`` sets it unless the environment already does.
    worker_consume_dead_letter: bool = False
    # Queue depth sampler bootstep (main process); the default pool sets it like the above.
    worker_sample_queue_depth: bool = False

    # R06-05: queue type and dead-lettering. ``classic`` keeps the 0.5.0 declarations.
    # ``quorum`` declares every task queue as a quorum queue with a delivery limit and a
    # dead-letter exchange; existing classic queues cannot be redeclared, so a cut-over uses
    # new CELERY_QUEUE_* names (runbook docs/27).
    celery_queue_type: QueueType = "classic"
    celery_delivery_limit: int = Field(default=5, ge=1, le=1000)
    celery_dead_letter_exchange: str = Field(default="rudix.dlx", min_length=1, max_length=64)
    celery_dead_letter_queue: str = Field(default="rudix.dead_letter", min_length=1, max_length=64)
    # Quorum mode publishes through this topic exchange: Celery's native delayed delivery
    # (countdown and ETA retries) does not support direct exchanges.
    celery_quorum_exchange: str = Field(default="rudix.tasks", min_length=1, max_length=64)
    celery_queue_email: str = Field(default="email", min_length=1, max_length=64)
    # Interval of the QueueDepthSampler bootstep (queue depth gauges, default pool).
    worker_queue_sample_interval_seconds: int = Field(default=30, ge=5, le=3600)

    @field_validator("celery_task_time_limits", mode="before")
    @classmethod
    def _merge_task_time_limits(cls, value: Any) -> dict[str, TaskTimeLimit]:
        return merge_task_time_limits(value)

    @field_validator(
        "celery_dead_letter_exchange",
        "celery_dead_letter_queue",
        "celery_quorum_exchange",
        "celery_queue_email",
    )
    @classmethod
    def _validate_broker_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "exchange and queue names may contain only letters, numbers, '.', '-', and '_'"
            )
        return cleaned

    @model_validator(mode="after")
    def _default_soft_below_hard(self) -> WorkersSettings:
        if self.celery_task_default_soft_time_limit >= self.celery_task_default_time_limit:
            raise ValueError(
                "CELERY_TASK_DEFAULT_SOFT_TIME_LIMIT must be below CELERY_TASK_DEFAULT_TIME_LIMIT"
            )
        return self

    # anchor: C2

    # anchor: D1
