"""Unit tests for ``app.shared.pagination.cursor`` (R04-04); no database needed."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql, sqlite

from app.models.document import Document
from app.shared.pagination import (
    decode_cursor,
    encode_cursor,
    keyset_condition,
    resolve_page_request,
    split_page,
)
from app.shared.pagination.cursor import _KeysetDateTime


def test_cursor_round_trip_keeps_types() -> None:
    moment = datetime(2026, 11, 27, 10, 0, 0, 123456, tzinfo=UTC)
    identifier = UUID("12345678-1234-5678-1234-567812345678")
    raw = encode_cursor("things.created_at.desc", [moment, 7, identifier])
    assert "=" not in raw
    assert decode_cursor(raw, "things.created_at.desc") == [moment, 7, identifier]


def test_cursor_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError):
        encode_cursor("s", [True])
    with pytest.raises(TypeError):
        encode_cursor("s", ["text"])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "A" * 1025,
        "e30",  # {} - no version
        "!!!!",
        base64.urlsafe_b64encode(b'{"k":[["i",true]],"s":"s","v":1}').decode(),
        base64.urlsafe_b64encode(b'{"k":[["d",5]],"s":"s","v":1}').decode(),
        base64.urlsafe_b64encode(b'{"k":["i"],"s":"s","v":1}').decode(),
        base64.urlsafe_b64encode(b'{"k":[["d","not a date"]],"s":"s","v":1}').decode(),
        base64.urlsafe_b64encode(b'{"k":[],"s":"s","v":1}').decode(),
        base64.urlsafe_b64encode(b"[1]").decode(),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_cursor_decode_errors_are_400(raw: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        decode_cursor(raw, "s")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid pagination cursor"


def test_cursor_for_another_sort_is_rejected() -> None:
    with pytest.raises(HTTPException):
        decode_cursor(encode_cursor("other", [1]), "s")


def test_resolve_page_request_defaults() -> None:
    plain = resolve_page_request(cursor=None, offset=5, include_total=None, sort_name="s")
    assert plain.keyset is None and plain.include_total is True
    blank = resolve_page_request(cursor="  ", offset=0, include_total=False, sort_name="s")
    assert blank.keyset is None and blank.include_total is False
    cursor = encode_cursor("s", [3])
    paged = resolve_page_request(cursor=cursor, offset=0, include_total=None, sort_name="s")
    assert paged.keyset == [3] and paged.include_total is False
    counted = resolve_page_request(cursor=cursor, offset=0, include_total=True, sort_name="s")
    assert counted.include_total is True
    with pytest.raises(HTTPException) as exc_info:
        resolve_page_request(cursor=cursor, offset=1, include_total=None, sort_name="s")
    assert exc_info.value.status_code == 400


def test_keyset_condition_shapes() -> None:
    now = datetime.now(UTC)
    uniform = keyset_condition([Document.created_at, Document.id], True, [now, uuid4()])
    compiled = str(uniform.compile(dialect=postgresql.dialect()))
    assert "(documents.created_at, documents.id) <" in compiled
    ascending = keyset_condition([Document.created_at, Document.id], False, [now, uuid4()])
    assert ") >" in str(ascending.compile(dialect=postgresql.dialect()))
    mixed = keyset_condition([Document.created_at, Document.id], [False, True], [now, uuid4()])
    compiled_mixed = str(mixed.compile(dialect=sqlite.dialect()))
    assert " OR " in compiled_mixed and "documents.created_at >" in compiled_mixed
    with pytest.raises(HTTPException):
        keyset_condition([Document.created_at], True, [now, uuid4()])
    with pytest.raises(ValueError):
        keyset_condition([Document.created_at, Document.id], [True], [now, uuid4()])


def test_split_page() -> None:
    assert split_page([1, 2, 3], 2) == ([1, 2], True)
    assert split_page([1, 2], 2) == ([1, 2], False)


def test_sqlite_keyset_datetime_bind_matches_storage() -> None:
    bind_type = _KeysetDateTime()
    whole = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    fractional = whole.replace(microsecond=42)
    assert bind_type.process_bind_param(whole, sqlite.dialect()) == "2026-01-02 03:04:05"
    assert (
        bind_type.process_bind_param(fractional, sqlite.dialect()) == "2026-01-02 03:04:05.000042"
    )
    assert bind_type.process_bind_param(whole, postgresql.dialect()) is whole
