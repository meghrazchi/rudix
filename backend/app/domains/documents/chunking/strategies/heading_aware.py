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
from app.domains.documents.chunking.strategies.blocks import (
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_TABLE,
    Block,
    SectionTracker,
    dominant_block_type,
    parse_blocks,
)

STRATEGY_NAME = "heading_aware"
STRATEGY_VERSION = "1.0"

# Block types that should be kept whole if they fit within the token budget.
_ATOMIC_TYPES = {BLOCK_TABLE, BLOCK_CODE, BLOCK_LIST}


class HeadingAwareStrategy:
    """Chunks at heading boundaries and preserves tables, code blocks, and lists.

    The algorithm:
    1. Parse all pages into typed blocks (heading, paragraph, table, code, list).
    2. Track the current heading hierarchy as a section path
       (e.g., ``Policy > Leave > Annual Leave``).
    3. Accumulate blocks greedily.  When a new heading is encountered the
       current buffer is flushed so each chunk starts fresh under its section.
    4. Tables, code blocks, and lists are treated as atomic: they are never
       split unless they individually exceed *chunk_size_tokens*.
    5. Each emitted chunk records ``section_path`` (heading context) and
       ``block_type`` (dominant content type of that chunk).

    Overlap is token-based: the next window starts *chunk_overlap_tokens*
    tokens before the previous window ended.  Since heading flushes reset the
    cursor, overlap only applies within a section, preventing heading text
    from contaminating the previous section's chunk.
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
    ) -> HeadingAwareStrategy:
        return cls(
            chunk_size_tokens=profile.chunk_size_tokens,
            chunk_overlap_tokens=profile.chunk_overlap_tokens,
            embedding_model=embedding_model,
            index_version=index_version,
            tiny_chunk_min_tokens=profile.min_tokens,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _token_split_block(
        self, block: Block, section_path: str | None, document_id: UUID, start_index: int
    ) -> list[ChunkPayload]:
        """Token-wise split of an oversized block, preserving page and section."""
        stride = self.chunk_size_tokens - self.chunk_overlap_tokens
        token_ids = encode_text(self._encoding, block.text)
        result: list[ChunkPayload] = []
        cursor = 0
        total = len(token_ids)
        while cursor < total:
            end = min(cursor + self.chunk_size_tokens, total)
            sub_tokens = token_ids[cursor:end]
            sub_text = self._encoding.decode(sub_tokens).strip()
            if sub_text:
                result.append(
                    ChunkPayload(
                        document_id=document_id,
                        page_number=block.page_number,
                        chunk_index=start_index + len(result),
                        text=sub_text,
                        token_count=len(sub_tokens),
                        embedding_model=self.embedding_model,
                        index_version=self.index_version,
                        strategy_name=STRATEGY_NAME,
                        strategy_version=STRATEGY_VERSION,
                        section_path=section_path,
                        block_type=block.block_type,
                    )
                )
            if end == total:
                break
            cursor += stride
        return result

    def _emit_buffer(
        self,
        buf_blocks: list[Block],
        buf_token_stream: list[tuple[int, int]],
        section_path: str | None,
        document_id: UUID,
        chunk_index: int,
    ) -> ChunkPayload:
        joined = "\n\n".join(b.text for b in buf_blocks)
        tokens = [t for _, t in buf_token_stream]
        return ChunkPayload(
            document_id=document_id,
            page_number=dominant_page_number(buf_token_stream),
            chunk_index=chunk_index,
            text=joined,
            token_count=len(tokens),
            embedding_model=self.embedding_model,
            index_version=self.index_version,
            strategy_name=STRATEGY_NAME,
            strategy_version=STRATEGY_VERSION,
            section_path=section_path or None,
            block_type=dominant_block_type(buf_blocks),
        )

    # ------------------------------------------------------------------
    # Main chunking
    # ------------------------------------------------------------------

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        ordered = sorted(pages, key=lambda p: p.page_number)
        if not ordered:
            return []

        # 1. Parse all pages into blocks and build a flat token stream
        #    tracking block boundaries for overlap-aware splits.
        all_blocks: list[Block] = []
        for page in ordered:
            text = page.text.strip()
            if text:
                all_blocks.extend(parse_blocks(page.page_number, text))

        if not all_blocks:
            return []

        # 2. Process blocks sequentially.
        result: list[ChunkPayload] = []
        tracker = SectionTracker()

        # Buffer: accumulated blocks + their tagged token stream
        buf_blocks: list[Block] = []
        buf_tokens: list[tuple[int, int]] = []  # (page_number, token_id)
        buf_section: str | None = None

        def flush(carry_tokens: int = 0) -> None:
            nonlocal buf_blocks, buf_tokens, buf_section
            if not buf_blocks:
                return
            result.append(
                self._emit_buffer(buf_blocks, buf_tokens, buf_section, document_id, len(result))
            )
            # Carry *carry_tokens* worth of tokens forward for overlap.
            if carry_tokens > 0 and buf_tokens:
                carry_start = max(0, len(buf_tokens) - carry_tokens)
                overlap_tokens = buf_tokens[carry_start:]
                # Rebuild buf_blocks from the overlap token range.
                # Simplest: record the overlap as a synthetic block.
                overlap_text = self._encoding.decode([t for _, t in overlap_tokens]).strip()
                if overlap_text:
                    # Determine which block the overlap falls in.
                    page_num = dominant_page_number(overlap_tokens) or buf_blocks[-1].page_number
                    overlap_block = Block(
                        page_number=page_num,
                        text=overlap_text,
                        block_type=buf_blocks[-1].block_type,
                    )
                    buf_blocks = [overlap_block]
                    buf_tokens = list(overlap_tokens)
                    return
            buf_blocks = []
            buf_tokens = []

        for block in all_blocks:
            # ── Heading: flush current buffer at section boundary ──────────
            if block.block_type == BLOCK_HEADING:
                flush()  # no overlap at heading boundaries
                tracker.update(block.heading_level or 1, block.text)
                buf_section = tracker.path or None
                # Add the heading text itself to the new buffer so it provides
                # context for the content that follows.
                heading_ids = encode_text(self._encoding, block.text)
                if heading_ids:
                    buf_blocks.append(block)
                    buf_tokens.extend((block.page_number, t) for t in heading_ids)
                continue

            block_ids = encode_text(self._encoding, block.text)
            block_token_count = len(block_ids)
            if not block_ids:
                continue

            block_section = tracker.path or None

            # ── Oversized atomic blocks (tables, code, large lists) ────────
            if block_token_count > self.chunk_size_tokens:
                if buf_blocks:
                    flush()
                result.extend(
                    self._token_split_block(block, block_section, document_id, len(result))
                )
                continue

            # ── Would overflow the current buffer ─────────────────────────
            if len(buf_tokens) + block_token_count > self.chunk_size_tokens and buf_blocks:
                flush(carry_tokens=self.chunk_overlap_tokens)
                # Update section tracking for carry-over buffer
                if not buf_section:
                    buf_section = block_section

            buf_blocks.append(block)
            buf_tokens.extend((block.page_number, t) for t in block_ids)
            buf_section = buf_section or block_section

        # Always emit trailing buffer: heading sections with only a short paragraph
        # must not be silently dropped.
        if buf_blocks:
            flush()

        return result
