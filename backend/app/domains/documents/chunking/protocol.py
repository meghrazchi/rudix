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
