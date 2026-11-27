"""Per-run ingestion options (R06-01).

Owned by chain S; evaluation code (A3) only sets ``vector_collection``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionOptions:
    pipeline_type: str = "document.process"
    # A ChunkingService-like object (``chunk()``, sizes, ``index_version``).
    chunking_service: Any = None
    profile_source: str = "system_default"
    # False for evaluation re-ingest: no status, graph, or DLP-warn writes on the document.
    persist_document_state: bool = True
    persist_document_pages: bool = True
    record_usage_event: bool = True
    # None writes to the default collection (QdrantService behaviour without the argument).
    vector_collection: str | None = None
