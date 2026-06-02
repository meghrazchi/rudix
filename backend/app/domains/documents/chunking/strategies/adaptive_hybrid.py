"""Adaptive hybrid chunking strategy (F210).

A meta-strategy that delegates to the best concrete strategy for each document,
selected by AdaptiveHybridSelector based on heuristic signals derived from the
page content and document metadata passed through strategy_options.

strategy_options keys consumed:
    file_type (str)          — "pdf" | "docx" | "txt" | "md"  (default "txt")
    ocr_applied (bool)       — True if OCR was run  (default False)
    force_strategy (str)     — bypass adaptive selection (admin/experiment override)
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.domains.documents.chunking.selector import (
    AdaptiveHybridSelector,
    SelectionResult,
    compute_document_signals,
)
from app.domains.documents.chunking.strategies._base import resolve_encoding

STRATEGY_NAME = "adaptive_hybrid"
STRATEGY_VERSION = "1.0"

_KEY_FILE_TYPE = "file_type"
_KEY_OCR_APPLIED = "ocr_applied"
_KEY_FORCE_STRATEGY = "force_strategy"


class AdaptiveHybridStrategy:
    """Select and delegate to the optimal chunking strategy per document.

    This strategy is registered under the name ``"adaptive_hybrid"``.
    Callers pass document context via ``strategy_options``; the selector then
    chooses page_aware, heading_aware, paragraph_recursive, or token_recursive.

    After ``chunk()`` returns, ``last_selection`` holds the ``SelectionResult``
    for the current call so the pipeline can extract reason codes for metadata
    storage without re-running the selector.
    """

    name: str = STRATEGY_NAME
    version: str = STRATEGY_VERSION
    supported_file_types: frozenset[str] | None = None
    supported_languages: frozenset[str] | None = None

    def __init__(
        self,
        *,
        profile: ChunkingProfileConfig,
        embedding_model: str,
        index_version: str,
    ) -> None:
        self._profile = profile
        self.embedding_model = embedding_model.strip()
        self.index_version = index_version.strip()

        opts = profile.strategy_options
        self._file_type: str = str(opts.get(_KEY_FILE_TYPE, "txt")).lower()
        self._ocr_applied: bool = bool(opts.get(_KEY_OCR_APPLIED, False))
        raw_force: object = opts.get(_KEY_FORCE_STRATEGY)
        self._force_strategy: str | None = str(raw_force) if raw_force else None
        self._encoding = resolve_encoding(self.embedding_model)
        self.last_selection: SelectionResult | None = None

    @classmethod
    def from_profile(
        cls,
        profile: ChunkingProfileConfig,
        embedding_model: str,
        index_version: str,
    ) -> AdaptiveHybridStrategy:
        return cls(
            profile=profile,
            embedding_model=embedding_model,
            index_version=index_version,
        )

    async def chunk(
        self,
        *,
        document_id: UUID,
        pages: Sequence[PageLike],
    ) -> list[ChunkPayload]:
        # Import here to break potential import cycles (registry ↔ strategies).
        from app.domains.documents.chunking.registry import get_registry

        signals = compute_document_signals(
            pages,
            file_type=self._file_type,
            ocr_applied=self._ocr_applied,
            language=self._profile.language,
            encoding=self._encoding,
        )

        selection = AdaptiveHybridSelector.select(
            signals, force_strategy=self._force_strategy
        )
        self.last_selection = selection

        # Build a concrete profile that reuses all size/overlap settings but
        # targets the resolved strategy.  strategy_options are cleared so the
        # concrete strategy doesn't see adaptive_hybrid-specific keys.
        concrete_profile = ChunkingProfileConfig.model_construct(
            strategy=selection.strategy,
            chunk_size_tokens=self._profile.chunk_size_tokens,
            chunk_overlap_tokens=self._profile.chunk_overlap_tokens,
            language=self._profile.language,
            min_tokens=self._profile.min_tokens,
            strategy_options={},
        )
        concrete = get_registry().resolve(
            concrete_profile,
            embedding_model=self.embedding_model,
            index_version=self.index_version,
        )
        return await concrete.chunk(document_id=document_id, pages=pages)
