from __future__ import annotations

from collections.abc import Iterable

from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue


def normalize_index_versions(index_versions: Iterable[str]) -> list[str]:
    """Strip, drop empties and dedupe index versions, preserving order."""
    normalized: list[str] = []
    for version in index_versions:
        candidate = version.strip()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def build_organization_filter(
    *,
    organization_id: str,
    document_ids: Iterable[str] | None = None,
    index_version: str | None = None,
    chunk_level: int | None = None,
    index_versions: Iterable[str] | None = None,
) -> Filter:
    normalized_organization_id = organization_id.strip()
    if not normalized_organization_id:
        raise ValueError("organization_id is required")

    conditions: list[FieldCondition] = [
        FieldCondition(
            key="organization_id",
            match=MatchValue(value=normalized_organization_id),
        )
    ]

    normalized_document_ids: list[str] = []
    seen_document_ids: set[str] = set()
    for document_id in document_ids or []:
        normalized_document_id = document_id.strip()
        if not normalized_document_id or normalized_document_id in seen_document_ids:
            continue
        seen_document_ids.add(normalized_document_id)
        normalized_document_ids.append(normalized_document_id)

    if len(normalized_document_ids) == 1:
        conditions.append(
            FieldCondition(
                key="document_id",
                match=MatchValue(value=normalized_document_ids[0]),
            )
        )
    elif normalized_document_ids:
        conditions.append(
            FieldCondition(
                key="document_id",
                match=MatchAny(any=normalized_document_ids),
            )
        )

    if index_version is not None and index_versions is not None:
        raise ValueError("pass either index_version or index_versions, not both")

    if index_version is not None:
        normalized_index_version = index_version.strip()
        if not normalized_index_version:
            raise ValueError("index_version must not be empty when provided")
        conditions.append(
            FieldCondition(
                key="index_version",
                match=MatchValue(value=normalized_index_version),
            )
        )

    if index_versions is not None:
        normalized_versions = normalize_index_versions(index_versions)
        if not normalized_versions:
            # Fail closed: an explicit empty allow-list must never mean "no filter".
            raise ValueError("index_versions must not be empty when provided")
        conditions.append(
            FieldCondition(
                key="index_version",
                match=(
                    MatchValue(value=normalized_versions[0])
                    if len(normalized_versions) == 1
                    else MatchAny(any=normalized_versions)
                ),
            )
        )

    if chunk_level is not None:
        conditions.append(
            FieldCondition(
                key="chunk_level",
                match=MatchValue(value=chunk_level),
            )
        )

    return Filter(must=conditions)  # type: ignore[arg-type]
