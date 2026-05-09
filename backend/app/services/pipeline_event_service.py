from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

_SENSITIVE_KEYS = {
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "access_key",
    "secret_key",
    "cookie",
    "set_cookie",
}
_TEXTLIKE_KEYS = {
    "answer",
    "content",
    "context",
    "prompt",
    "question",
    "text",
}
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)
_MAX_STRING_CHARS = 400
_TEXT_PREVIEW_CHARS = 180
_MAX_LIST_ITEMS = 50


def _normalize_key(key: str | None) -> str:
    if key is None:
        return ""
    return key.strip().lower().replace("-", "_")


def _is_sensitive_key(key: str | None) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_api_key", "_access_key", "_secret_key")
    )


def _is_textlike_key(key: str | None) -> bool:
    normalized = _normalize_key(key)
    if normalized in _TEXTLIKE_KEYS:
        return True
    return normalized.endswith(("_text", "_content", "_prompt", "_answer", "_context", "_question"))


def _truncate(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… [truncated]"


def sanitize_pipeline_payload(value: object, *, key: str | None = None) -> object:
    if _is_sensitive_key(key):
        return "***"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, str):
        redacted = _SENSITIVE_VALUE_PATTERN.sub(r"\1=***", value)
        if _is_textlike_key(key):
            return _truncate(redacted, limit=_TEXT_PREVIEW_CHARS)
        return _truncate(redacted, limit=_MAX_STRING_CHARS)

    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for entry_key, entry_value in value.items():
            key_as_str = str(entry_key)
            sanitized[key_as_str] = sanitize_pipeline_payload(entry_value, key=key_as_str)
        return sanitized

    if isinstance(value, (list, tuple, set)):
        sanitized_items = [sanitize_pipeline_payload(item, key=key) for item in list(value)[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            sanitized_items.append(f"... {len(value) - _MAX_LIST_ITEMS} more items")
        return sanitized_items

    return _truncate(str(value), limit=_MAX_STRING_CHARS)

