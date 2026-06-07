"""Metadata normalization utilities for the connector SDK."""

from __future__ import annotations

from typing import Any


def normalize_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip None values and flatten one level of nesting from a raw metadata dict.

    Provider adapters often get JSON blobs with many optional fields. This helper
    removes None-valued keys so the stored metadata stays compact and consistent.
    """
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, dict):
            flattened = {f"{key}.{k}": v for k, v in value.items() if v is not None}
            result.update(flattened)
        else:
            result[key] = value
    return result


def build_metadata(**kwargs: Any) -> dict[str, Any]:
    """Build a metadata dict from keyword arguments, omitting None values.

    Intended as a concise alternative to constructing the dict manually:

        build_metadata(author="alice", labels=["bug"], priority=None)
        # → {"author": "alice", "labels": ["bug"]}
    """
    return {key: value for key, value in kwargs.items() if value is not None}
