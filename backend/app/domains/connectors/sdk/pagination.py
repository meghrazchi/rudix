"""Cursor-based pagination helpers for the connector SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

_OFFSET_KEY = "offset"
_PAGE_KEY = "page"


@dataclass
class CursorPage[T]:
    """A single page of results with pagination metadata."""

    items: list[T]
    next_cursor: dict[str, Any] | None = None
    has_more: bool = False
    total_count: int | None = None


def paginate_list[T](
    items: list[T],
    *,
    cursor: dict[str, Any],
    page_size: int,
) -> CursorPage[T]:
    """Split a pre-loaded list into a cursor page using an integer offset cursor.

    Useful for providers that load all items locally (e.g., small sources or stubs)
    but need to present a paginated interface to the sync engine.
    """
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    offset = int(cursor.get(_OFFSET_KEY, 0))
    if offset < 0:
        offset = 0

    page_items = items[offset : offset + page_size]
    next_offset = offset + len(page_items)
    has_more = next_offset < len(items)

    return CursorPage(
        items=page_items,
        next_cursor={_OFFSET_KEY: next_offset} if has_more else None,
        has_more=has_more,
        total_count=len(items),
    )


def offset_cursor(offset: int) -> dict[str, Any]:
    """Build an offset-based cursor dict."""
    return {_OFFSET_KEY: offset}


def page_cursor(page: int) -> dict[str, Any]:
    """Build a 1-based page-number cursor dict."""
    return {_PAGE_KEY: page}


def next_page(cursor: dict[str, Any]) -> dict[str, Any]:
    """Advance a page-number cursor by one."""
    return {_PAGE_KEY: int(cursor.get(_PAGE_KEY, 1)) + 1}
