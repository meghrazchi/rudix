"""Content and ACL hashing utilities for the connector SDK."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.domains.connectors.sdk.models import ExternalACL


def hash_text(text: str, *, encoding: str = "utf-8") -> str:
    """Return a lowercase SHA-256 hex digest of the given text."""
    return hashlib.sha256(text.encode(encoding)).hexdigest()


def hash_dict(data: Any) -> str:
    """Return a lowercase SHA-256 hex digest of a JSON-serialized dict.

    Keys are sorted to ensure the hash is deterministic regardless of insertion order.
    """
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def hash_acl(entries: list[ExternalACL]) -> str:
    """Return a deterministic SHA-256 hash over a list of ACL entries.

    Entries are sorted by (principal_type, principal_id, access_level) before
    hashing so that reordering does not produce a different hash.
    """
    normalized = sorted(
        (e.to_dict() for e in entries),
        key=lambda d: (d["principal_type"], d["principal_id"], d["access_level"]),
    )
    return hash_dict(normalized)
