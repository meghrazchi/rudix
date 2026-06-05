"""Rate limit helpers for the connector SDK."""
from __future__ import annotations

from typing import Any


def parse_retry_after(headers: dict[str, str] | Any, *, default_seconds: int = 60) -> int:
    """Extract retry delay from an HTTP Retry-After header value or response headers dict.

    Handles both integer-seconds and HTTP-date formats; falls back to *default_seconds*
    when the header is absent or unparseable.
    """
    if isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    else:
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except Exception:
            raw = None

    if not raw:
        return default_seconds

    raw = str(raw).strip()

    try:
        return max(1, int(raw))
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        retry_at = parsedate_to_datetime(raw)
        now = datetime.now(tz=timezone.utc)
        delay = int((retry_at - now).total_seconds())
        return max(1, delay)
    except Exception:
        return default_seconds


def raise_for_rate_limit(
    response_status: int,
    headers: dict[str, str] | Any,
    *,
    default_retry_after: int = 60,
) -> None:
    """Raise ConnectorRateLimitError if *response_status* is 429.

    Call this after every provider HTTP response so rate limits are handled
    consistently across adapters without duplicating the check inline.
    """
    if response_status == 429:
        from app.domains.connectors.services.provider_adapter import ConnectorRateLimitError

        retry_after = parse_retry_after(headers, default_seconds=default_retry_after)
        raise ConnectorRateLimitError(
            f"Provider returned 429; retry after {retry_after}s",
            retry_after_seconds=retry_after,
        )
