from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.strategies._base import (
    dominant_page_number,
    encode_text,
    resolve_encoding,
)

STRATEGY_NAME = "paragraph_recursive"
STRATEGY_VERSION = "1.0"

_PARA_SPLIT = re.compile(r"\n{2,}")


class ParagraphRecursiveStrategy:
    """Chunk with paragraph-aligned boundaries and token-level overlap.

    The document is tokenized into a flat stream.  Paragraph end positions are
    recorded.  Each chunk window ends at the last paragraph boundary within
    [cursor, cursor + chunk_size_tokens].  If no boundary exists (an oversized
    single paragraph) the window falls back to the token limit.  Overlap is
    token-based: the next window starts *chunk_overlap_tokens* tokens before
    the previous window ended.
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

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        ordered_pages = sorted(pages, key=lambda p: p.page_number)
        if not ordered_pages:
            return []

        # Build a flat (page_number, token_id) stream and record the exclusive
        # end index of every paragraph so we can snap window boundaries to them.
        token_stream: list[tuple[int, int]] = []
        para_ends: list[int] = []  # sorted exclusive-end positions

        for page in ordered_pages:
            for para_text in _PARA_SPLIT.split(page.text):
                text = para_text.strip()
                if not text:
                    continue
                ids = encode_text(self._encoding, text)
                if not ids:
                    continue
                for tid in ids:
                    token_stream.append((page.page_number, tid))
                para_ends.append(len(token_stream))

        if not token_stream:
            return []

        total = len(token_stream)
        stride = self.chunk_size_tokens - self.chunk_overlap_tokens
        result: list[ChunkPayload] = []
        cursor = 0

        while cursor < total:
            max_end = min(cursor + self.chunk_size_tokens, total)

            # Find the last paragraph boundary at or before max_end.
            # bisect_right gives the index of the first para_end > max_end;
            # the one before it is the last para_end <= max_end.
            idx = bisect_right(para_ends, max_end) - 1
            if (
                idx >= 0
                and para_ends[idx] > cursor
                and para_ends[idx] - self.chunk_overlap_tokens > cursor
            ):
                # Snap to that paragraph boundary only when doing so still advances
                # the cursor (avoids infinite loop when the boundary is within the
                # overlap window of the current cursor position).
                end = para_ends[idx]
            else:
                # No usable paragraph boundary — break at the token limit.
                end = max_end

            window = token_stream[cursor:end]
            tokens = [t for _, t in window]
            chunk_text = self._encoding.decode(tokens).strip()
            token_count = len(tokens)
            is_last = end >= total

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
            cursor = end - self.chunk_overlap_tokens

        return result
