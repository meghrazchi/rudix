from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class PageLike(Protocol):
    page_number: int
    text: str


@dataclass(frozen=True)
class ChunkPayload:
    document_id: UUID
    page_number: int | None
    chunk_index: int
    text: str
    token_count: int
    embedding_model: str
    index_version: str
    strategy_name: str = "token_recursive"
    strategy_version: str = "1.0"
    section_path: str | None = None
    block_type: str | None = None
    # Hierarchical parent-child fields (F211).
    # chunk_level=0 means flat chunk or parent; chunk_level=1 means child (embedded for retrieval).
    # parent_chunk_index references the parent's chunk_index within the same document+version.
    # child_count is set on parent payloads to record how many children were produced.
    chunk_level: int = 0
    parent_chunk_index: int | None = None
    child_count: int | None = None


class ChunkStrategy(Protocol):
    """Protocol that all chunking strategy implementations must satisfy."""

    name: str
    version: str
    supported_file_types: frozenset[str] | None
    supported_languages: frozenset[str] | None

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]: ...
