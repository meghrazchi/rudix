from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import tiktoken
from tiktoken import Encoding

from app.core.config import settings


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


class ChunkingService:
    """Token-aware recursive chunking with stable metadata."""

    def __init__(
        self,
        *,
        chunk_size_tokens: int | None = None,
        chunk_overlap_tokens: int | None = None,
        embedding_model: str | None = None,
        index_version: str | None = None,
        tiny_chunk_min_tokens: int | None = None,
    ) -> None:
        self.chunk_size_tokens = chunk_size_tokens or settings.chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens or settings.chunk_overlap_tokens
        self.embedding_model = (embedding_model or settings.openai_embedding_model).strip()
        self.index_version = (index_version or settings.document_index_version).strip()
        self.tiny_chunk_min_tokens = tiny_chunk_min_tokens or max(1, min(32, self.chunk_size_tokens // 8))

        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if self.tiny_chunk_min_tokens < 1:
            raise ValueError("tiny_chunk_min_tokens must be at least 1")

        self._encoding = self._resolve_encoding(self.embedding_model)

    @staticmethod
    def _resolve_encoding(model_name: str) -> Encoding:
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

    def _encode_text(self, text: str) -> list[int]:
        return self._encoding.encode(text, disallowed_special=())

    def _dominant_page_number(self, token_window: Sequence[tuple[int, int]]) -> int | None:
        if not token_window:
            return None
        by_page: dict[int, int] = defaultdict(int)
        for page_number, _token in token_window:
            by_page[page_number] += 1
        # Prefer the most represented page and choose the earliest page on ties.
        return max(by_page.items(), key=lambda item: (item[1], -item[0]))[0]

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        ordered_pages = sorted(pages, key=lambda page: page.page_number)
        if not ordered_pages:
            return []

        separator_tokens = self._encode_text("\n\n")
        token_stream: list[tuple[int, int]] = []
        for page in ordered_pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            page_tokens = self._encode_text(page_text)
            if not page_tokens:
                continue
            if token_stream and separator_tokens:
                token_stream.extend((page.page_number, token) for token in separator_tokens)
            token_stream.extend((page.page_number, token) for token in page_tokens)

        if not token_stream:
            return []

        stride = self.chunk_size_tokens - self.chunk_overlap_tokens
        chunks: list[ChunkPayload] = []
        cursor = 0
        total_tokens = len(token_stream)

        while cursor < total_tokens:
            end = min(cursor + self.chunk_size_tokens, total_tokens)
            token_window = token_stream[cursor:end]
            tokens = [token for _page_number, token in token_window]
            chunk_text = self._encoding.decode(tokens).strip()
            token_count = len(tokens)
            is_last_window = end == total_tokens

            if not chunk_text:
                if is_last_window:
                    break
                cursor += stride
                continue

            if (
                is_last_window
                and chunks
                and token_count < self.tiny_chunk_min_tokens
            ):
                break

            chunks.append(
                ChunkPayload(
                    document_id=document_id,
                    page_number=self._dominant_page_number(token_window),
                    chunk_index=len(chunks),
                    text=chunk_text,
                    token_count=token_count,
                    embedding_model=self.embedding_model,
                    index_version=self.index_version,
                )
            )

            if is_last_window:
                break
            cursor += stride

        return chunks
