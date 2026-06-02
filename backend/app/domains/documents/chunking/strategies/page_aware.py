from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.strategies._base import encode_text, resolve_encoding

STRATEGY_NAME = "page_aware"
STRATEGY_VERSION = "1.0"


class PageAwareStrategy:
    """Never merges content from different pages.

    Each page is emitted as one or more chunks.  When a page's token count
    fits within *chunk_size_tokens* the entire page becomes a single chunk.
    Long pages are split token-wise with configurable overlap, but the split
    never crosses a page boundary.

    This strategy is primarily intended for PDFs and OCR-derived documents
    where page provenance is important for citation accuracy.
    """

    name: str = STRATEGY_NAME
    version: str = STRATEGY_VERSION
    supported_file_types: frozenset[str] | None = frozenset({"pdf", "txt", "docx"})
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
    ) -> PageAwareStrategy:
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
        ordered = sorted(pages, key=lambda p: p.page_number)
        if not ordered:
            return []

        result: list[ChunkPayload] = []
        stride = self.chunk_size_tokens - self.chunk_overlap_tokens

        for page in ordered:
            text = page.text.strip()
            if not text:
                continue
            token_ids = encode_text(self._encoding, text)
            if not token_ids:
                continue

            section_path = f"page:{page.page_number}"

            if len(token_ids) <= self.chunk_size_tokens:
                result.append(
                    ChunkPayload(
                        document_id=document_id,
                        page_number=page.page_number,
                        chunk_index=len(result),
                        text=text,
                        token_count=len(token_ids),
                        embedding_model=self.embedding_model,
                        index_version=self.index_version,
                        strategy_name=STRATEGY_NAME,
                        strategy_version=STRATEGY_VERSION,
                        section_path=section_path,
                        block_type="paragraph",
                    )
                )
                continue

            # Page is too long — split token-wise within this page only.
            cursor = 0
            total = len(token_ids)
            page_chunks: list[ChunkPayload] = []

            while cursor < total:
                end = min(cursor + self.chunk_size_tokens, total)
                sub_tokens = token_ids[cursor:end]
                sub_text = self._encoding.decode(sub_tokens).strip()
                token_count = len(sub_tokens)
                is_last = end == total

                if not sub_text:
                    if is_last:
                        break
                    cursor += stride
                    continue

                if is_last and page_chunks and token_count < self.tiny_chunk_min_tokens:
                    break

                page_chunks.append(
                    ChunkPayload(
                        document_id=document_id,
                        page_number=page.page_number,
                        chunk_index=len(result) + len(page_chunks),
                        text=sub_text,
                        token_count=token_count,
                        embedding_model=self.embedding_model,
                        index_version=self.index_version,
                        strategy_name=STRATEGY_NAME,
                        strategy_version=STRATEGY_VERSION,
                        section_path=section_path,
                        block_type="paragraph",
                    )
                )

                if is_last:
                    break
                cursor += stride

            result.extend(page_chunks)

        return result
