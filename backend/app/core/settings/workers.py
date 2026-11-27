"""Ingestion and worker settings introduced in 0.6.0 (R06-xx).

Each later work package adds its fields directly after its ``# anchor: <task>`` marker.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
