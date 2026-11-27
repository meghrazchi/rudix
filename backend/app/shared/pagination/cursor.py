"""Opaque, versioned keyset cursors (R04-04).

A cursor is base64url JSON ``{"v": 1, "s": <sort name>, "k": [<typed values>]}``. It carries
only the sort-key values of the last row of a page. Tenant and user filters are always applied
by the endpoint on the server side, so a forged or replayed cursor can never widen what a
caller may see; at worst it selects a different window of the caller's own rows.

Each value is stored as a ``[type, value]`` pair so it decodes back to the exact Python type
the column binds with: ``d`` (ISO-8601 datetime), ``u`` (UUID) and ``i`` (int).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import DateTime, String, and_, bindparam, or_, tuple_
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import TypeDecorator, TypeEngine

CURSOR_VERSION = 1
INVALID_CURSOR_DETAIL = "Invalid pagination cursor"
CURSOR_WITH_OFFSET_DETAIL = "Cursor pagination cannot be combined with offset"
MAX_CURSOR_LENGTH = 1024

CursorValue = datetime | UUID | int
KeysetColumn = ColumnElement[Any] | QueryableAttribute[Any]


def _invalid_cursor() -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CURSOR_DETAIL)


def _encode_value(value: CursorValue) -> list[Any]:
    # ``bool`` is an ``int`` subclass; sort keys never use it, so reject it explicitly.
    if isinstance(value, bool):
        raise TypeError("bool is not a supported cursor value")
    if isinstance(value, datetime):
        return ["d", value.isoformat()]
    if isinstance(value, UUID):
        return ["u", str(value)]
    if isinstance(value, int):
        return ["i", value]
    raise TypeError(f"unsupported cursor value type: {type(value).__name__}")


def _decode_value(item: Any) -> CursorValue:
    if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
        raise ValueError("malformed cursor value")
    kind, raw = item
    if kind == "d" and isinstance(raw, str):
        return datetime.fromisoformat(raw)
    if kind == "u" and isinstance(raw, str):
        return UUID(raw)
    if kind == "i" and isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    raise ValueError("malformed cursor value")


def encode_cursor(sort_name: str, values: Sequence[CursorValue]) -> str:
    """Encode the sort-key ``values`` of the last row of a page as an opaque cursor."""
    payload = {
        "v": CURSOR_VERSION,
        "s": sort_name,
        "k": [_encode_value(value) for value in values],
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(raw: str, expected_sort: str) -> list[CursorValue]:
    """Decode ``raw``; any malformed, wrong-version or wrong-sort cursor raises a 400."""
    if not raw or len(raw) > MAX_CURSOR_LENGTH:
        raise _invalid_cursor()
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload is not an object")
        if payload.get("v") != CURSOR_VERSION or payload.get("s") != expected_sort:
            raise ValueError("cursor version or sort mismatch")
        keys = payload.get("k")
        if not isinstance(keys, list) or not keys:
            raise ValueError("cursor has no sort values")
        return [_decode_value(item) for item in keys]
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise _invalid_cursor() from exc


class _KeysetDateTime(TypeDecorator[Any]):
    """Bind a cursor datetime the way the column stored it.

    PostgreSQL compares real ``timestamptz`` values. SQLite stores datetimes as text, and rows
    written by the ``CURRENT_TIMESTAMP`` server default have no fractional seconds while the
    default SQLAlchemy bind format always adds ``.ffffff``; binding the same textual shape
    keeps equal timestamps equal, so ties are broken by the next key instead of being skipped.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String())
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if dialect.name != "sqlite" or not isinstance(value, datetime):
            return value
        text = value.strftime("%Y-%m-%d %H:%M:%S")
        if value.microsecond:
            text = f"{text}.{value.microsecond:06d}"
        return text


def _bind(column: KeysetColumn, value: CursorValue) -> ColumnElement[Any]:
    if isinstance(column.type, DateTime):
        return bindparam(None, value, type_=_KeysetDateTime())
    return bindparam(None, value, type_=column.type)


def keyset_condition(
    columns: Sequence[KeysetColumn],
    descending: bool | Sequence[bool],
    values: Sequence[CursorValue],
) -> ColumnElement[bool]:
    """Rows strictly after ``values`` in the order given by ``columns``/``descending``.

    A uniform direction uses one row-value comparison (``(a, b) < (:a, :b)``), which both
    PostgreSQL and SQLite evaluate and PostgreSQL can serve from a matching composite index.
    Mixed directions expand to the equivalent ``OR`` of prefix equalities.
    """
    if len(columns) != len(values) or not columns:
        raise _invalid_cursor()
    directions = [descending] * len(columns) if isinstance(descending, bool) else list(descending)
    if len(directions) != len(columns):
        raise ValueError("descending must match columns")
    binds = [_bind(column, value) for column, value in zip(columns, values, strict=True)]
    if len(set(directions)) == 1:
        left = tuple_(*columns)
        right = tuple_(*binds)
        return left < right if directions[0] else left > right
    clauses: list[ColumnElement[bool]] = []
    for index, (column, bound) in enumerate(zip(columns, binds, strict=True)):
        prefix = [columns[i] == binds[i] for i in range(index)]
        step = column < bound if directions[index] else column > bound
        clauses.append(and_(*prefix, step))
    return or_(*clauses)


def apply_keyset[SelectT: Select[Any]](
    stmt: SelectT,
    columns: Sequence[KeysetColumn],
    descending: bool | Sequence[bool],
    values: Sequence[CursorValue],
) -> SelectT:
    """Add the keyset ``WHERE`` for ``values`` to ``stmt`` (its ``ORDER BY`` must match)."""
    return stmt.where(keyset_condition(columns, descending, values))


@dataclass(frozen=True)
class PageRequest:
    """Resolved pagination inputs for one list request."""

    keyset: list[CursorValue] | None
    include_total: bool


def resolve_page_request(
    *,
    cursor: str | None,
    offset: int,
    include_total: bool | None,
    sort_name: str,
) -> PageRequest:
    """Validate ``cursor``/``offset`` and apply the ``include_total`` default.

    ``include_total`` defaults to ``True`` without a cursor (today's behaviour) and to
    ``False`` with one. A cursor combined with ``offset > 0`` is rejected with a 400.
    """
    normalized = cursor.strip() if cursor is not None else None
    if not normalized:
        return PageRequest(
            keyset=None, include_total=True if include_total is None else include_total
        )
    if offset > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=CURSOR_WITH_OFFSET_DETAIL
        )
    return PageRequest(
        keyset=decode_cursor(normalized, sort_name),
        include_total=False if include_total is None else include_total,
    )


def split_page[RowT](rows: Sequence[RowT], limit: int) -> tuple[list[RowT], bool]:
    """Trim rows fetched with ``LIMIT limit + 1`` to ``limit`` and report whether more exist."""
    return list(rows[:limit]), len(rows) > limit
