"""In-memory stand-in for the Qdrant client used by ``QdrantService`` tests (R06-06, R06-07).

Implements the calls the service makes (``upsert``, ``scroll``, ``delete``, ``count``,
``query_points``) with ``Filter`` evaluation for ``FieldCondition`` with ``MatchValue`` or
``MatchAny`` in ``must`` and ``must_not``, and counts every call by name, including the
collection and payload-index calls that must not happen on the write path. The ``Async``
variant exposes the same calls as coroutines, like ``AsyncQdrantClient``.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue


@dataclass
class StoredPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0


def _matches(condition: Any, payload: dict[str, Any]) -> bool:
    if not isinstance(condition, FieldCondition):
        raise AssertionError(f"unsupported condition {type(condition).__name__}")
    value = payload.get(condition.key)
    if isinstance(condition.match, MatchValue):
        return value == condition.match.value
    if isinstance(condition.match, MatchAny):
        return value in condition.match.any
    raise AssertionError("unsupported match")


def matches(query_filter: Filter | None, payload: dict[str, Any]) -> bool:
    if query_filter is None:
        return True
    must = query_filter.must or []
    must_not = query_filter.must_not or []
    must_list = must if isinstance(must, list) else [must]
    not_list = must_not if isinstance(must_not, list) else [must_not]
    return all(_matches(c, payload) for c in must_list) and not any(
        _matches(c, payload) for c in not_list
    )


def text_vector(text: str, size: int) -> list[float]:
    """Deterministic vector of ``size`` floats from the text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(size)]


class InMemoryQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, StoredPoint]] = {}
        self.calls: Counter[str] = Counter()
        self.filters: list[tuple[str, Filter | None]] = []

    def _store(self, collection_name: str) -> dict[str, StoredPoint]:
        return self.collections.setdefault(collection_name, {})

    def points(self, collection_name: str) -> dict[str, StoredPoint]:
        return self._store(collection_name)

    def upsert(self, *, collection_name: str, points: list[Any], wait: bool = True) -> None:
        self.calls["upsert"] += 1
        store = self._store(collection_name)
        for point in points:
            store[str(point.id)] = StoredPoint(
                id=str(point.id), vector=list(point.vector), payload=dict(point.payload or {})
            )

    def scroll(
        self,
        *,
        collection_name: str,
        scroll_filter: Filter | None = None,
        limit: int = 10,
        with_payload: Any = True,
        with_vectors: bool = False,
    ) -> tuple[list[StoredPoint], None]:
        self.calls["scroll"] += 1
        self.filters.append(("scroll", scroll_filter))
        hits = [
            point
            for point in self._store(collection_name).values()
            if matches(scroll_filter, point.payload)
        ][:limit]
        return hits, None

    def delete(self, *, collection_name: str, points_selector: Any, wait: bool = True) -> None:
        self.calls["delete"] += 1
        self.filters.append(("delete", points_selector))
        store = self._store(collection_name)
        for key in [k for k, p in store.items() if matches(points_selector, p.payload)]:
            del store[key]

    def count(self, *, collection_name: str, count_filter: Filter | None, exact: bool) -> Any:
        self.calls["count"] += 1
        total = sum(
            1 for p in self._store(collection_name).values() if matches(count_filter, p.payload)
        )
        return type("CountResult", (), {"count": total})()

    def query_points(
        self, *, collection_name: str, query_filter: Filter | None, limit: int, **_: Any
    ) -> Any:
        self.calls["query_points"] += 1
        self.filters.append(("query_points", query_filter))
        hits = [
            p for p in self._store(collection_name).values() if matches(query_filter, p.payload)
        ]
        return type("QueryResponse", (), {"points": hits[:limit]})()

    # Calls that must stay off the write path (R06-07).
    def collection_exists(self, *_: Any, **__: Any) -> bool:
        self.calls["collection_exists"] += 1
        return True

    def get_collection(self, *_: Any, **__: Any) -> Any:
        self.calls["get_collection"] += 1
        raise AssertionError("get_collection on the write path")

    def create_payload_index(self, **_: Any) -> None:
        self.calls["create_payload_index"] += 1


class AsyncInMemoryQdrant(InMemoryQdrant):
    """The same store with coroutine methods, as ``AsyncQdrantClient`` has."""

    async def upsert(self, **kwargs: Any) -> None:  # type: ignore[override]
        InMemoryQdrant.upsert(self, **kwargs)

    async def scroll(self, **kwargs: Any) -> Any:  # type: ignore[override]
        return InMemoryQdrant.scroll(self, **kwargs)

    async def delete(self, **kwargs: Any) -> None:  # type: ignore[override]
        InMemoryQdrant.delete(self, **kwargs)

    async def count(self, **kwargs: Any) -> Any:  # type: ignore[override]
        return InMemoryQdrant.count(self, **kwargs)

    async def query_points(self, **kwargs: Any) -> Any:  # type: ignore[override]
        return InMemoryQdrant.query_points(self, **kwargs)

    async def close(self) -> None:
        self.calls["close"] += 1
