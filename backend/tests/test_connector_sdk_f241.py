"""Tests for F241: connector provider SDK utilities."""
from __future__ import annotations

import json
import pytest

from app.domains.connectors.sdk.content_hash import hash_acl, hash_dict, hash_text
from app.domains.connectors.sdk.metadata import build_metadata, normalize_metadata
from app.domains.connectors.sdk.models import ExternalACL, ExternalSource, SyncCursor
from app.domains.connectors.sdk.pagination import CursorPage, next_page, offset_cursor, page_cursor, paginate_list
from app.domains.connectors.sdk.rate_limits import parse_retry_after, raise_for_rate_limit
from app.domains.connectors.sdk.url_builder import build_url, normalize_url

pytestmark = pytest.mark.sdk


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestHashText:
    def test_returns_64_char_hex(self) -> None:
        result = hash_text("hello")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        assert hash_text("foo") == hash_text("foo")

    def test_different_inputs_differ(self) -> None:
        assert hash_text("foo") != hash_text("bar")

    def test_empty_string(self) -> None:
        result = hash_text("")
        assert len(result) == 64


class TestHashDict:
    def test_key_order_independent(self) -> None:
        h1 = hash_dict({"a": 1, "b": 2})
        h2 = hash_dict({"b": 2, "a": 1})
        assert h1 == h2

    def test_different_values_differ(self) -> None:
        assert hash_dict({"a": 1}) != hash_dict({"a": 2})

    def test_nested_dict(self) -> None:
        result = hash_dict({"x": {"y": 1}})
        assert len(result) == 64


class TestHashACL:
    def test_order_independent(self) -> None:
        acl1 = [
            ExternalACL("user", "alice", "read"),
            ExternalACL("user", "bob", "write"),
        ]
        acl2 = [
            ExternalACL("user", "bob", "write"),
            ExternalACL("user", "alice", "read"),
        ]
        assert hash_acl(acl1) == hash_acl(acl2)

    def test_different_principals_differ(self) -> None:
        acl1 = [ExternalACL("user", "alice", "read")]
        acl2 = [ExternalACL("user", "bob", "read")]
        assert hash_acl(acl1) != hash_acl(acl2)

    def test_empty_acl(self) -> None:
        result = hash_acl([])
        assert len(result) == 64


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class TestExternalSource:
    def test_valid(self) -> None:
        src = ExternalSource(
            provider_source_id="PROJ-1",
            name="My Project",
            source_type="project",
            url="https://jira.example.com/PROJ-1",
        )
        assert src.provider_source_id == "PROJ-1"

    def test_blank_id_raises(self) -> None:
        with pytest.raises(ValueError, match="provider_source_id"):
            ExternalSource(provider_source_id="  ", name="x", source_type="project")

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ExternalSource(provider_source_id="id", name="", source_type="project")


class TestExternalACL:
    def test_valid_principal_types(self) -> None:
        for pt in ("user", "group", "role", "anyone"):
            acl = ExternalACL(pt, "id", "read")
            assert acl.principal_type == pt

    def test_invalid_principal_type_raises(self) -> None:
        with pytest.raises(ValueError, match="principal_type"):
            ExternalACL("org", "id", "read")

    def test_invalid_access_level_raises(self) -> None:
        with pytest.raises(ValueError, match="access_level"):
            ExternalACL("user", "id", "owner")

    def test_to_dict(self) -> None:
        acl = ExternalACL("group", "eng", "read", inherited=True)
        d = acl.to_dict()
        assert d == {
            "principal_type": "group",
            "principal_id": "eng",
            "access_level": "read",
            "inherited": True,
        }


class TestSyncCursor:
    def test_empty(self) -> None:
        c = SyncCursor.empty()
        assert c.is_empty()

    def test_from_dict_round_trips(self) -> None:
        data = {"token": "abc", "page": 2}
        c = SyncCursor.from_dict(data)
        assert c.to_dict() == data

    def test_get_missing_returns_default(self) -> None:
        c = SyncCursor.empty()
        assert c.get("missing", "fallback") == "fallback"

    def test_require_missing_raises(self) -> None:
        c = SyncCursor.empty()
        with pytest.raises(KeyError, match="missing"):
            c.require("missing")

    def test_set_returns_new_cursor(self) -> None:
        c = SyncCursor.empty()
        c2 = c.set("token", "xyz")
        assert c.is_empty()
        assert c2.get("token") == "xyz"

    def test_json_serializable(self) -> None:
        c = SyncCursor.from_dict({"page": 1, "token": "abc"})
        assert c.is_json_serializable()

    def test_non_serializable(self) -> None:
        c = SyncCursor(_data={"obj": object()})
        assert not c.is_json_serializable()


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


class TestPaginateList:
    def test_single_page(self) -> None:
        page = paginate_list([1, 2, 3], cursor={}, page_size=10)
        assert page.items == [1, 2, 3]
        assert not page.has_more
        assert page.next_cursor is None
        assert page.total_count == 3

    def test_multiple_pages(self) -> None:
        items = list(range(5))
        page1 = paginate_list(items, cursor={}, page_size=2)
        assert page1.items == [0, 1]
        assert page1.has_more
        assert page1.next_cursor == {"offset": 2}

        page2 = paginate_list(items, cursor=page1.next_cursor, page_size=2)
        assert page2.items == [2, 3]
        assert page2.has_more

        page3 = paginate_list(items, cursor=page2.next_cursor, page_size=2)
        assert page3.items == [4]
        assert not page3.has_more
        assert page3.next_cursor is None

    def test_empty_list(self) -> None:
        page = paginate_list([], cursor={}, page_size=10)
        assert page.items == []
        assert not page.has_more

    def test_invalid_page_size_raises(self) -> None:
        with pytest.raises(ValueError):
            paginate_list([1, 2], cursor={}, page_size=0)

    def test_offset_cursor_helper(self) -> None:
        c = offset_cursor(10)
        assert c == {"offset": 10}

    def test_page_cursor_helper(self) -> None:
        c = page_cursor(3)
        assert c == {"page": 3}

    def test_next_page_advances(self) -> None:
        assert next_page({"page": 1}) == {"page": 2}
        assert next_page({}) == {"page": 2}


# ---------------------------------------------------------------------------
# rate_limits
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    def test_integer_seconds(self) -> None:
        assert parse_retry_after({"Retry-After": "30"}) == 30

    def test_lowercase_header_key(self) -> None:
        assert parse_retry_after({"retry-after": "45"}) == 45

    def test_missing_header_returns_default(self) -> None:
        assert parse_retry_after({}) == 60
        assert parse_retry_after({}, default_seconds=120) == 120

    def test_minimum_one_second(self) -> None:
        assert parse_retry_after({"Retry-After": "0"}) == 1

    def test_non_dict_with_get(self) -> None:
        class FakeHeaders:
            def get(self, key: str) -> str | None:
                return "15" if key == "Retry-After" else None

        assert parse_retry_after(FakeHeaders()) == 15


class TestRaiseForRateLimit:
    def test_raises_on_429(self) -> None:
        from app.domains.connectors.services.provider_adapter import ConnectorRateLimitError

        with pytest.raises(ConnectorRateLimitError) as exc_info:
            raise_for_rate_limit(429, {"Retry-After": "10"})
        assert exc_info.value.retry_after_seconds == 10

    def test_no_raise_on_200(self) -> None:
        raise_for_rate_limit(200, {})

    def test_no_raise_on_404(self) -> None:
        raise_for_rate_limit(404, {})

    def test_default_retry_after_used(self) -> None:
        from app.domains.connectors.services.provider_adapter import ConnectorRateLimitError

        with pytest.raises(ConnectorRateLimitError) as exc_info:
            raise_for_rate_limit(429, {}, default_retry_after=30)
        assert exc_info.value.retry_after_seconds == 30


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


class TestNormalizeMetadata:
    def test_strips_none_values(self) -> None:
        result = normalize_metadata({"a": 1, "b": None, "c": "x"})
        assert result == {"a": 1, "c": "x"}

    def test_flattens_nested_dict(self) -> None:
        result = normalize_metadata({"labels": {"bug": True, "empty": None}})
        assert result == {"labels.bug": True}

    def test_preserves_non_dict_values(self) -> None:
        result = normalize_metadata({"tags": ["a", "b"], "count": 3})
        assert result == {"tags": ["a", "b"], "count": 3}


class TestBuildMetadata:
    def test_omits_none(self) -> None:
        result = build_metadata(author="alice", priority=None)
        assert result == {"author": "alice"}

    def test_keeps_falsy_non_none(self) -> None:
        result = build_metadata(empty_list=[], zero=0, flag=False)
        assert result == {"empty_list": [], "zero": 0, "flag": False}


# ---------------------------------------------------------------------------
# url_builder
# ---------------------------------------------------------------------------


class TestNormalizeUrl:
    def test_strips_trailing_slash(self) -> None:
        assert normalize_url("https://api.example.com/") == "https://api.example.com/"

    def test_strips_trailing_slashes_from_path(self) -> None:
        assert normalize_url("https://api.example.com/v2/") == "https://api.example.com/v2"

    def test_strips_fragment(self) -> None:
        assert "#anchor" not in normalize_url("https://example.com/path#anchor")

    def test_adds_https_scheme(self) -> None:
        result = normalize_url("example.com/path")
        assert result.startswith("https://")

    def test_invalid_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            normalize_url("ftp://example.com/file")


class TestBuildUrl:
    def test_basic_path(self) -> None:
        assert build_url("https://api.example.com", "v2", "issues") == \
            "https://api.example.com/v2/issues"

    def test_query_params(self) -> None:
        url = build_url("https://api.example.com", "items", page=1, status="open")
        assert "page=1" in url
        assert "status=open" in url

    def test_none_params_omitted(self) -> None:
        url = build_url("https://api.example.com", "items", filter=None)
        assert "filter" not in url

    def test_bool_params_lowercased(self) -> None:
        url = build_url("https://api.example.com", "items", active=True)
        assert "active=true" in url

    def test_no_segments(self) -> None:
        assert build_url("https://api.example.com") == "https://api.example.com"

    def test_strips_slashes_from_segments(self) -> None:
        url = build_url("https://api.example.com/", "/v2/", "/items")
        assert "//" not in url.replace("://", "X")
