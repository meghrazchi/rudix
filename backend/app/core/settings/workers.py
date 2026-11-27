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
    # R06-02: the extract stage streams the stored object to a temporary file in reads of
    # this size (never one whole-object read) and extracts PDF and TXT from that file.
    ingest_download_chunk_bytes: int = Field(default=_MIB, ge=4096, le=64 * _MIB)
    # Directory of those temporary files; None means the system temporary directory. It
    # must hold the largest accepted upload per concurrently processing worker task.
    ingest_temp_dir: str | None = None
    # TXT files are decoded in sections of at most this many characters (page-like
    # sections numbered 1..n); a file shorter than one section stays a single section.
    ingest_text_segment_chars: int = Field(default=200_000, ge=1_000, le=50_000_000)
    # Documentation and test bound only: the peak memory one extract stage run is designed
    # to stay under, independent of the file size. Nothing enforces it at runtime.
    ingest_memory_ceiling_mb: int = Field(default=512, ge=64, le=65_536)
    # R06-06: embed batches of one stage run (and provider batches inside one
    # ``EmbeddingService.embed_chunks`` call) that run concurrently. 1 keeps the sequential
    # behaviour of 0.5.0.
    embedding_max_concurrent_batches: int = Field(default=1, ge=1, le=32)
    # Scrolls of one reuse lookup: a further scroll for the still-missing hashes runs only
    # when the previous page came back full (copies of a text in other documents). 1 = one
    # scroll per batch.
    embedding_reuse_max_lookups: int = Field(default=3, ge=1, le=16)
    # R06-07: timeouts of the async Qdrant clients. Search None means QDRANT_TIMEOUT_SECONDS
    # (the 2 s request-path budget); writes get a longer one for large batches.
    qdrant_search_timeout_seconds: float | None = Field(default=None, ge=0.1, le=60.0)
    qdrant_write_timeout_seconds: float = Field(default=30.0, ge=1.0, le=600.0)
    # Collection tuning, applied only when a collection is created. None leaves the Qdrant
    # server default. Evaluate on staging with the accuracy gate before setting any of
    # them (docs/27 "Vector writes and memory").
    qdrant_hnsw_m: int | None = Field(default=None, ge=0, le=1024)
    qdrant_hnsw_ef_construct: int | None = Field(default=None, ge=4, le=4096)
    qdrant_hnsw_payload_m: int | None = Field(default=None, ge=0, le=1024)
    qdrant_hnsw_on_disk: bool | None = None
    qdrant_vectors_on_disk: bool | None = None
    qdrant_on_disk_payload: bool | None = None
    qdrant_scalar_quantization: bool | None = None
    qdrant_quantization_quantile: float | None = Field(default=None, ge=0.5, le=1.0)
    qdrant_quantization_always_ram: bool | None = None
    qdrant_shard_number: int | None = Field(default=None, ge=1, le=1024)
    qdrant_replication_factor: int | None = Field(default=None, ge=1, le=64)
    # True stores the parent chunk's text on every child point (the 0.5.0 payload). False
    # omits it; vector retrieval then reads parent text from document_chunks by id.
    qdrant_store_parent_text: bool = True

    # anchor: A2
    # R06-08: Qdrant alias that retrieval reads. None (default) is legacy mode: reads and
    # writes use QDRANT_COLLECTION directly, as before 0.6.0. When set, generations named
    # ``{QDRANT_COLLECTION}_{model_slug}_v{n}`` sit behind the alias; ``scripts/
    # vector_index.py adopt`` registers the existing collection as generation 1.
    qdrant_collection_alias: str | None = Field(
        default=None, min_length=2, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    # How long the generation registry (active and building generation) is cached per
    # process before it is read again from vector_index_generations.
    vector_index_registry_cache_seconds: float = Field(default=30.0, ge=0.0, le=3600.0)
    # A swapped-out generation stays retired (readable, rollback target) this long before
    # drop-retired may delete its collection.
    qdrant_retired_grace_hours: int = Field(default=168, ge=0, le=24 * 365)
    # The daily beat entry vector-index-drop-retired acts only when this is true.
    vector_index_auto_drop_retired: bool = False
    # Documents per page of vector_index.build (one cursor step per document).
    vector_index_build_batch_documents: int = Field(default=50, ge=1, le=10_000)
    # Pages one vector_index.build delivery runs before it re-enqueues itself.
    vector_index_build_max_pages_per_task: int = Field(default=20, ge=1, le=10_000)

    # anchor: A3

    # anchor: B1
    # R06-09: documents.chunks.backfill_tenant fills document_chunks.organization_id,
    # fts_config and fts_vector in batches by primary key, one short transaction each.
    chunk_backfill_batch_size: int = Field(default=1000, ge=1, le=50_000)
    chunk_backfill_lock_timeout_ms: int = Field(default=2000, ge=100, le=60_000)
    chunk_backfill_statement_timeout_ms: int = Field(default=30_000, ge=1000, le=600_000)
    # Keyword search: query fts_vector with the question's configuration (false keeps the
    # English generated column); scope by the chunk tenant column (auto uses it once no
    # NULL organization_id remains, checked once per process); rank at most this many
    # matches (0 ranks every match, the pre-0.6.0 behaviour).
    keyword_search_multilingual: bool = False
    keyword_search_tenant_column: Literal["auto", "on", "off"] = "auto"
    keyword_search_candidate_limit: int = Field(default=1000, ge=0, le=100_000)
    # R06-10: graph rows per UNWIND write transaction, and extraction LLM batches in flight
    # per document (1 keeps the sequential behaviour).
    graph_write_batch_size: int = Field(default=200, ge=1, le=10_000)
    entity_extraction_max_concurrent_batches: int = Field(default=1, ge=1, le=32)
    relation_extraction_max_concurrent_batches: int = Field(default=1, ge=1, le=32)

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
    # R06-11: connector sync at tenant scale. A running run whose heartbeat is older than
    # this may be leased by another task and is re-enqueued by connectors.sync.reap.
    connector_sync_stale_seconds: int = Field(default=600, ge=30, le=86_400)
    # Cancellation is checked before each page and every N items inside a page.
    connector_sync_cancel_check_items: int = Field(default=50, ge=1, le=100_000)
    # Items requested per provider page (adapters may return fewer or more).
    connector_sync_page_size: int = Field(default=100, ge=1, le=10_000)
    # Due jobs claimed per schedule poll (one FOR UPDATE SKIP LOCKED query).
    connector_sync_poll_batch_size: int = Field(default=100, ge=1, le=10_000)
    # Concurrent queued or running runs per organization / per connection; 0 = no cap.
    connector_sync_max_concurrent_per_org: int = Field(default=0, ge=0, le=10_000)
    connector_sync_max_concurrent_per_connection: int = Field(default=0, ge=0, le=10_000)
    # Countdown before a run held back by a cap is tried again.
    connector_sync_cap_retry_seconds: int = Field(default=60, ge=1, le=86_400)
    # Provider Retry-After up to this many seconds is slept inside the run (with
    # heartbeats) and the same page retried; longer ones checkpoint and re-enqueue.
    connector_sync_max_inline_backoff_seconds: int = Field(default=60, ge=0, le=3600)
    connector_sync_max_inline_retries: int = Field(default=5, ge=0, le=100)
    # Items tombstoned per transaction at the end of a full sync.
    connector_sync_tombstone_batch_size: int = Field(default=500, ge=1, le=100_000)
    # connectors.sync.reap beat interval.
    connector_sync_reap_interval_seconds: int = Field(default=120, ge=10, le=86_400)
