from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike

STRATEGY_NAME = "hierarchical"
STRATEGY_VERSION = "1.0"

# Default multiplier for parent size when not explicitly set in strategy_options.
_DEFAULT_PARENT_SIZE_MULTIPLIER = 3


@dataclass
class _PageWrapper:
    """Minimal PageLike wrapping a single text string for child re-chunking."""

    page_number: int
    text: str


class HierarchicalStrategy:
    """Two-level chunking: large parent chunks for context, small children for retrieval.

    Each parent chunk is re-chunked by the child strategy.  Only child chunks
    (chunk_level=1) are embedded and upserted to the vector store; parent chunks
    (chunk_level=0) are persisted to PostgreSQL so that citation expansion can
    display richer context without re-fetching the source document.

    Configuration via ``strategy_options`` in the profile:

    * ``parent_strategy`` (str, default ``"token_recursive"``) — strategy used
      to create the large parent chunks.
    * ``parent_chunk_size_tokens`` (int) — token budget for parent windows.
      Defaults to ``chunk_size_tokens x 3`` (capped at 3000 unless set).
    * ``parent_chunk_overlap_tokens`` (int, default ``0``) — overlap for parent
      windows.  Set to 0 so parent boundaries are stable and non-overlapping.

    The child strategy always uses the top-level profile settings
    (``chunk_size_tokens``, ``chunk_overlap_tokens``).
    """

    name: str = STRATEGY_NAME
    version: str = STRATEGY_VERSION
    supported_file_types: frozenset[str] | None = None
    supported_languages: frozenset[str] | None = None

    def __init__(
        self,
        *,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
        parent_chunk_size_tokens: int,
        parent_chunk_overlap_tokens: int = 0,
        parent_strategy_name: str = "token_recursive",
        embedding_model: str,
        index_version: str,
        tiny_chunk_min_tokens: int | None = None,
    ) -> None:
        if chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if parent_chunk_size_tokens <= chunk_size_tokens:
            raise ValueError("parent_chunk_size_tokens must be larger than chunk_size_tokens")
        if parent_chunk_overlap_tokens >= parent_chunk_size_tokens:
            raise ValueError(
                "parent_chunk_overlap_tokens must be smaller than parent_chunk_size_tokens"
            )
        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.parent_chunk_size_tokens = parent_chunk_size_tokens
        self.parent_chunk_overlap_tokens = parent_chunk_overlap_tokens
        self.parent_strategy_name = parent_strategy_name
        self.embedding_model = embedding_model.strip()
        self.index_version = index_version.strip()
        self.tiny_chunk_min_tokens = tiny_chunk_min_tokens or max(
            1, min(32, chunk_size_tokens // 8)
        )

    @classmethod
    def from_profile(
        cls,
        profile: ChunkingProfileConfig,
        embedding_model: str,
        index_version: str,
    ) -> HierarchicalStrategy:
        opts = profile.strategy_options
        default_parent_size = min(profile.chunk_size_tokens * _DEFAULT_PARENT_SIZE_MULTIPLIER, 3000)
        parent_size = int(opts.get("parent_chunk_size_tokens", default_parent_size))
        parent_overlap = int(opts.get("parent_chunk_overlap_tokens", 0))
        parent_strategy = str(opts.get("parent_strategy", "token_recursive"))
        return cls(
            chunk_size_tokens=profile.chunk_size_tokens,
            chunk_overlap_tokens=profile.chunk_overlap_tokens,
            parent_chunk_size_tokens=parent_size,
            parent_chunk_overlap_tokens=parent_overlap,
            parent_strategy_name=parent_strategy,
            embedding_model=embedding_model,
            index_version=index_version,
            tiny_chunk_min_tokens=profile.min_tokens,
        )

    def _build_parent_strategy(self) -> object:
        """Construct the parent-level strategy instance."""
        from app.domains.documents.chunking.registry import get_registry

        parent_profile = ChunkingProfileConfig.model_construct(
            strategy=self.parent_strategy_name,
            chunk_size_tokens=self.parent_chunk_size_tokens,
            chunk_overlap_tokens=self.parent_chunk_overlap_tokens,
            min_tokens=None,
            language=None,
            strategy_options={},
        )
        return get_registry().resolve(
            parent_profile,
            embedding_model=self.embedding_model,
            index_version=self.index_version,
        )

    def _build_child_strategy(self) -> object:
        """Construct the child-level strategy instance (uses token_recursive)."""
        from app.domains.documents.chunking.strategies.token_recursive import (
            TokenRecursiveStrategy,
        )

        return TokenRecursiveStrategy(
            chunk_size_tokens=self.chunk_size_tokens,
            chunk_overlap_tokens=self.chunk_overlap_tokens,
            embedding_model=self.embedding_model,
            index_version=self.index_version,
            tiny_chunk_min_tokens=self.tiny_chunk_min_tokens,
        )

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        parent_strategy = self._build_parent_strategy()
        child_strategy = self._build_child_strategy()

        parent_raw = await parent_strategy.chunk(document_id=document_id, pages=pages)
        if not parent_raw:
            return []

        result: list[ChunkPayload] = []
        chunk_index = 0

        for parent_raw_payload in parent_raw:
            parent_chunk_index = chunk_index
            chunk_index += 1

            parent_page = _PageWrapper(
                page_number=parent_raw_payload.page_number or 1,
                text=parent_raw_payload.text,
            )
            child_raw = await child_strategy.chunk(
                document_id=document_id,
                pages=[parent_page],
            )

            child_count = len(child_raw)

            result.append(
                ChunkPayload(
                    document_id=document_id,
                    page_number=parent_raw_payload.page_number,
                    chunk_index=parent_chunk_index,
                    text=parent_raw_payload.text,
                    token_count=parent_raw_payload.token_count,
                    embedding_model=self.embedding_model,
                    index_version=self.index_version,
                    strategy_name=STRATEGY_NAME,
                    strategy_version=STRATEGY_VERSION,
                    section_path=parent_raw_payload.section_path,
                    block_type=parent_raw_payload.block_type,
                    chunk_level=0,
                    parent_chunk_index=None,
                    child_count=child_count if child_count > 0 else None,
                )
            )

            for raw_child in child_raw:
                result.append(
                    ChunkPayload(
                        document_id=document_id,
                        page_number=raw_child.page_number,
                        chunk_index=chunk_index,
                        text=raw_child.text,
                        token_count=raw_child.token_count,
                        embedding_model=self.embedding_model,
                        index_version=self.index_version,
                        strategy_name=STRATEGY_NAME,
                        strategy_version=STRATEGY_VERSION,
                        section_path=parent_raw_payload.section_path,
                        block_type=raw_child.block_type,
                        chunk_level=1,
                        parent_chunk_index=parent_chunk_index,
                        child_count=None,
                    )
                )
                chunk_index += 1

        return result
