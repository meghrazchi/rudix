from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.registry import get_registry
from app.domains.documents.chunking.selector import SelectionResult

# Re-export for backward compatibility with callers that import from this module.
__all__ = ["ChunkPayload", "ChunkingService", "PageLike"]


class ChunkingService:
    """Delegates chunking to the strategy registry.

    Public API is unchanged from the original implementation; the default
    strategy (token_recursive) produces identical output.

    document_context passed to chunk() is merged into strategy_options so
    strategies like adaptive_hybrid can access file_type / ocr_applied.
    After each chunk() call, last_adaptive_selection is populated when the
    resolved strategy exposes a SelectionResult on its last_selection attribute.
    """

    def __init__(
        self,
        *,
        strategy: str | None = None,
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
            strategy=strategy or "token_recursive",
            chunk_size_tokens=resolved_size,
            chunk_overlap_tokens=resolved_overlap,
            min_tokens=tiny_min,
            language=None,
            strategy_options={},
        )

        self.last_adaptive_selection: SelectionResult | None = None

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
        document_context: dict[str, Any] | None = None,
    ) -> list[ChunkPayload]:
        """Chunk *pages* using the configured strategy.

        document_context is merged into strategy_options before strategy
        resolution so that adaptive_hybrid (and any future context-aware
        strategy) can access file_type and ocr_applied without changing the
        ChunkStrategy protocol.
        """
        if document_context:
            merged_opts = {**self._profile.strategy_options, **document_context}
            profile = ChunkingProfileConfig.model_construct(
                strategy=self._profile.strategy,
                chunk_size_tokens=self._profile.chunk_size_tokens,
                chunk_overlap_tokens=self._profile.chunk_overlap_tokens,
                language=self._profile.language,
                min_tokens=self._profile.min_tokens,
                strategy_options=merged_opts,
            )
        else:
            profile = self._profile

        resolved_strategy = get_registry().resolve(
            profile,
            embedding_model=self.embedding_model,
            index_version=self.index_version,
        )
        chunks = await resolved_strategy.chunk(document_id=document_id, pages=pages)

        # Capture adaptive selection metadata without importing the strategy class
        # (avoids potential circular imports at module load time).
        raw_selection = getattr(resolved_strategy, "last_selection", None)
        self.last_adaptive_selection = raw_selection if isinstance(raw_selection, SelectionResult) else None

        return chunks
