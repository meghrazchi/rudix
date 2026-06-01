from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.core.config import settings
from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.registry import get_registry

# Re-export for backward compatibility with callers that import from this module.
__all__ = ["ChunkPayload", "ChunkingService", "PageLike"]


class ChunkingService:
    """Delegates chunking to the strategy registry.

    Public API is unchanged from the original implementation; the default
    strategy (token_recursive) produces identical output.
    """

    def __init__(
        self,
        *,
        chunk_size_tokens: int | None = None,
        chunk_overlap_tokens: int | None = None,
        embedding_model: str | None = None,
        index_version: str | None = None,
        tiny_chunk_min_tokens: int | None = None,
    ) -> None:
        resolved_size = chunk_size_tokens or settings.chunk_size_tokens
        resolved_overlap = chunk_overlap_tokens or settings.chunk_overlap_tokens
        self.chunk_size_tokens = resolved_size
        self.chunk_overlap_tokens = resolved_overlap
        self.embedding_model = (embedding_model or settings.openai_embedding_model).strip()
        self.index_version = (index_version or settings.document_index_version).strip()
        tiny_min = tiny_chunk_min_tokens or max(1, min(32, resolved_size // 8))

        if resolved_overlap >= resolved_size:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")

        # Use model_construct to bypass Pydantic range validators: ChunkingService
        # accepts test-friendly sizes (e.g. 30 tokens) that are below the API-level
        # minimum enforced by ChunkingProfileConfig.  Overlap/size invariant is
        # checked explicitly above.
        self._profile = ChunkingProfileConfig.model_construct(
            strategy="token_recursive",
            chunk_size_tokens=resolved_size,
            chunk_overlap_tokens=resolved_overlap,
            min_tokens=tiny_min,
            language=None,
            strategy_options={},
        )

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        strategy = get_registry().resolve(
            self._profile,
            embedding_model=self.embedding_model,
            index_version=self.index_version,
        )
        return await strategy.chunk(document_id=document_id, pages=pages)
