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

    # anchor: A3

    # anchor: B1

    # anchor: C1

    # anchor: C2

    # anchor: D1
