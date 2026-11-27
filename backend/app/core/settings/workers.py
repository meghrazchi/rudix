"""Ingestion and worker settings introduced in 0.6.0 (R06-xx).

Each later work package adds its fields directly after its ``# anchor: <task>`` marker.
"""

from __future__ import annotations

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

    # anchor: A1

    # anchor: A2

    # anchor: A3

    # anchor: B1

    # anchor: C1

    # anchor: C2

    # anchor: D1
