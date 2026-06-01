from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.strategies._base import (
    TextUnit,
    dominant_page_number,
    encode_text,
    overlap_tail,
    resolve_encoding,
)

STRATEGY_NAME = "paragraph_recursive"
STRATEGY_VERSION = "1.0"

_PARA_SPLIT = re.compile(r"\n{2,}")


def _split_paragraphs(page_number: int, text: str) -> list[tuple[int, str]]:
    return [
        (page_number, p.strip())
        for p in _PARA_SPLIT.split(text)
        if p.strip()
    ]


class ParagraphRecursiveStrategy:
    """Chunk at paragraph boundaries, merging short paragraphs and splitting long ones.

    Complete paragraphs are greedily accumulated up to *chunk_size_tokens*.
    When the budget would be exceeded, the current buffer is emitted and the
    overlap tail (measured in tokens) is carried forward.  Single paragraphs
    that exceed the budget are split token-wise so every chunk stays within
    the embedding provider's limits.
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
    ) -> ParagraphRecursiveStrategy:
        return cls(
            chunk_size_tokens=profile.chunk_size_tokens,
            chunk_overlap_tokens=profile.chunk_overlap_tokens,
            embedding_model=embedding_model,
            index_version=index_version,
            tiny_chunk_min_tokens=profile.min_tokens,
        )

    def _token_split(self, unit: TextUnit) -> list[TextUnit]:
        """Split an oversized paragraph into fixed-window sub-units."""
        stride = self.chunk_size_tokens - self.chunk_overlap_tokens
        tokens = unit.token_ids
        result: list[TextUnit] = []
        cursor = 0
        while cursor < len(tokens):
            end = min(cursor + self.chunk_size_tokens, len(tokens))
            sub_tokens = tokens[cursor:end]
            sub_text = self._encoding.decode(sub_tokens).strip()
            if sub_text:
                result.append(TextUnit(unit.page_number, sub_text, list(sub_tokens)))
            if end == len(tokens):
                break
            cursor += stride
        return result

    def _make_payload(
        self,
        buffer: list[TextUnit],
        document_id: UUID,
        chunk_index: int,
    ) -> ChunkPayload:
        joined = "\n\n".join(u.text for u in buffer)
        tagged = [(u.page_number, t) for u in buffer for t in u.token_ids]
        return ChunkPayload(
            document_id=document_id,
            page_number=dominant_page_number(tagged),
            chunk_index=chunk_index,
            text=joined,
            token_count=len(tagged),
            embedding_model=self.embedding_model,
            index_version=self.index_version,
            strategy_name=STRATEGY_NAME,
            strategy_version=STRATEGY_VERSION,
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

        all_units: list[TextUnit] = []
        for page in ordered_pages:
            for pnum, text in _split_paragraphs(page.page_number, page.text):
                token_ids = encode_text(self._encoding, text)
                if token_ids:
                    all_units.append(TextUnit(pnum, text, token_ids))

        if not all_units:
            return []

        result: list[ChunkPayload] = []
        buffer: list[TextUnit] = []
        buffer_tokens = 0

        def flush() -> None:
            nonlocal buffer, buffer_tokens
            result.append(self._make_payload(buffer, document_id, len(result)))
            buffer = overlap_tail(buffer, self.chunk_overlap_tokens)
            buffer_tokens = sum(u.token_count for u in buffer)

        for unit in all_units:
            if unit.token_count > self.chunk_size_tokens:
                if buffer:
                    flush()
                for sub in self._token_split(unit):
                    result.append(
                        ChunkPayload(
                            document_id=document_id,
                            page_number=sub.page_number,
                            chunk_index=len(result),
                            text=sub.text,
                            token_count=sub.token_count,
                            embedding_model=self.embedding_model,
                            index_version=self.index_version,
                            strategy_name=STRATEGY_NAME,
                            strategy_version=STRATEGY_VERSION,
                        )
                    )
                continue

            if buffer_tokens + unit.token_count > self.chunk_size_tokens and buffer:
                flush()

            buffer.append(unit)
            buffer_tokens += unit.token_count

        if buffer:
            is_only_chunk = not result
            if is_only_chunk or buffer_tokens >= self.tiny_chunk_min_tokens:
                flush()

        return result
