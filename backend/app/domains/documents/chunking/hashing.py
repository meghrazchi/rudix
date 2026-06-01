from __future__ import annotations

import hashlib
import unicodedata


def compute_chunk_hash(text: str) -> str:
    """Return a SHA-256 hex digest of the chunk text.

    Input is NFC-normalized and stripped so the same logical text always
    produces the same hash regardless of minor whitespace or normalization
    differences between indexing runs.
    """
    normalized = unicodedata.normalize("NFC", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
