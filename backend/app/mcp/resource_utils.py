from __future__ import annotations

from typing import Any
from urllib.parse import unquote_plus

from app.domains.agents.schemas import ToolErrorCode
from app.mcp.resource_constants import _RESOURCE_MAX_FILENAME_CHARS, _RESOURCE_MAX_QUERY_CHARS


def safe_resource_error_payload(
    *,
    resource: str,
    code: ToolErrorCode,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "resource": resource,
        "error": {
            "code": code.value,
            "message": message,
            "request_id": request_id,
        },
    }


def decode_uri_text(value: str) -> str:
    return unquote_plus(value).strip()


def decode_optional_uri_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = decode_uri_text(value)
    return normalized or None


def coerce_bounded_int(
    value: int | str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None or isinstance(value, bool):
        return default
    parsed: int
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            parsed = int(stripped)
        except ValueError:
            return default
    else:
        return default
    return max(minimum, min(parsed, maximum))


def truncate_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def truncate_filename(value: object) -> str | None:
    return truncate_text(value, max_length=_RESOURCE_MAX_FILENAME_CHARS)


def coerce_query(value: str | None) -> str | None:
    normalized = decode_optional_uri_text(value)
    if normalized is None:
        return None
    if len(normalized) <= _RESOURCE_MAX_QUERY_CHARS:
        return normalized
    return normalized[:_RESOURCE_MAX_QUERY_CHARS]
