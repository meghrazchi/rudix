from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.strategies._base import (
    dominant_page_number,
    encode_text,
    resolve_encoding,
)

STRATEGY_NAME = "token_fixed"
STRATEGY_VERSION = "1.0"


class TokenFixedStrategy:
    """Fixed-size sliding-window chunker without inter-page separator tokens.

    Pages are concatenated directly so chunk boundaries depend only on the raw
    token positions, not on inserted whitespace.  This makes chunk sizes fully
    predictable and is useful for benchmarking or simple uniform documents.

    Overlap works identically to token_recursive: the next window starts
    *chunk_overlap_tokens* tokens before the previous window ended.
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
        embedding_model: str,
        index_version: str,
        tiny_chunk_min_tokens: int | None = None,
    ) -> None:
        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.embedding_model = embedding_model.strip()
        self.index_version = index_version.strip()
        self.tiny_chunk_min_tokens = tiny_chunk_min_tokens or max(
            1, min(32, self.chunk_size_tokens // 8)
        )
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if self.tiny_chunk_min_tokens < 1:
            raise ValueError("tiny_chunk_min_tokens must be at least 1")
        self._encoding = resolve_encoding(self.embedding_model)

    @classmethod
    def from_profile(
        cls,
        profile: ChunkingProfileConfig,
        embedding_model: str,
        index_version: str,
    ) -> TokenFixedStrategy:
        return cls(
            chunk_size_tokens=profile.chunk_size_tokens,
            chunk_overlap_tokens=profile.chunk_overlap_tokens,
            embedding_model=embedding_model,
            index_version=index_version,
            tiny_chunk_min_tokens=profile.min_tokens,
        )

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        ordered_pages = sorted(pages, key=lambda p: p.page_number)
        if not ordered_pages:
            return []

        # Flat token stream: no separator tokens between pages.
        token_stream: list[tuple[int, int]] = []
        for page in ordered_pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            for token in encode_text(self._encoding, page_text):
                token_stream.append((page.page_number, token))

        if not token_stream:
            return []

        stride = self.chunk_size_tokens - self.chunk_overlap_tokens
        result: list[ChunkPayload] = []
        cursor = 0
        total = len(token_stream)

        while cursor < total:
            end = min(cursor + self.chunk_size_tokens, total)
            window = token_stream[cursor:end]
            tokens = [t for _, t in window]
            chunk_text = self._encoding.decode(tokens).strip()
            token_count = len(tokens)
            is_last = end == total

            if not chunk_text:
                if is_last:
                    break
                cursor += stride
                continue

            if is_last and result and token_count < self.tiny_chunk_min_tokens:
                break

            result.append(
                ChunkPayload(
                    document_id=document_id,
                    page_number=dominant_page_number(window),
                    chunk_index=len(result),
                    text=chunk_text,
                    token_count=token_count,
                    embedding_model=self.embedding_model,
                    index_version=self.index_version,
                    strategy_name=STRATEGY_NAME,
                    strategy_version=STRATEGY_VERSION,
                )
            )

            if is_last:
                break
            cursor += stride

        return result
