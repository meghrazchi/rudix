from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.hashing import compute_chunk_hash
from app.domains.documents.chunking.protocol import ChunkPayload, ChunkStrategy, PageLike
from app.domains.documents.chunking.registry import (
    StrategyRegistry,
    UnknownStrategyError,
    get_registry,
)
from app.domains.documents.chunking.selector import (
    AdaptiveHybridSelector,
    DocumentSignals,
    SelectionResult,
    compute_document_signals,
)

__all__ = [
    "AdaptiveHybridSelector",
    "ChunkPayload",
    "ChunkStrategy",
    "ChunkingProfileConfig",
    "DocumentSignals",
    "PageLike",
    "SelectionResult",
    "StrategyRegistry",
    "UnknownStrategyError",
    "compute_chunk_hash",
    "compute_document_signals",
    "get_registry",
]
