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

    # anchor: C2

    # anchor: D1
