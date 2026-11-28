"""Span redaction before export (R08-10).

``RedactingSpanExporter`` wraps the real exporter and rebuilds every finished span so only
allowlisted, content-free attributes leave the process:

* attribute names outside ``ALLOWED_ATTRIBUTES`` (and the ``rpc.`` prefix) are dropped, and
  so is any name containing a denied word (token, prompt, content, text, query, ...);
* string values lose their query string and are cut to ``MAX_VALUE_LENGTH``;
* exception events keep ``exception.type`` only (no message, no stack trace), other events
  keep their allowlisted attributes, links keep their context and allowlisted attributes;
* the status description is dropped (it carries the exception message);
* span names are cut and lose any query string.

Instrumentations still collect their usual attributes (``db.statement``, ``url.full``, Redis
arguments); this wrapper is the single place that decides what is exported.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Link, Status
from opentelemetry.util.types import AttributeValue

ALLOWED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "http.request.method",
        "http.method",
        "http.route",
        "http.response.status_code",
        "http.status_code",
        "url.scheme",
        "server.address",
        "db.system",
        "db.operation",
        "messaging.system",
        "messaging.destination.name",
        "celery.task_name",
        "celery.action",
        "rudix.request_id",
        "rudix.organization_id",
        "rudix.llm.provider",
        "rudix.llm.model",
        "rudix.qdrant.collection",
        "rudix.outcome",
        "error.type",
    }
)
ALLOWED_ATTRIBUTE_PREFIXES: Final[tuple[str, ...]] = ("rpc.",)
DENIED_NAME_PARTS: Final[tuple[str, ...]] = (
    "token",
    "prompt",
    "content",
    "text",
    "query",
    "password",
    "secret",
    "authorization",
    "cookie",
)
EXCEPTION_EVENT_NAME: Final = "exception"
EXCEPTION_TYPE_ATTRIBUTE: Final = "exception.type"
MAX_VALUE_LENGTH: Final = 256
MAX_NAME_LENGTH: Final = 128

_QUERY_PATTERN = re.compile(r"[?#][^\s]*")


def is_allowed_attribute(name: str) -> bool:
    lowered = name.lower()
    if any(part in lowered for part in DENIED_NAME_PARTS):
        return False
    return lowered in ALLOWED_ATTRIBUTES or lowered.startswith(ALLOWED_ATTRIBUTE_PREFIXES)


def strip_query(value: str) -> str:
    """Drop the query string and fragment of any URL-like value."""
    return _QUERY_PATTERN.sub("", value)


def _clean_string(value: str, limit: int = MAX_VALUE_LENGTH) -> str:
    return strip_query(value)[:limit]


def _clean_value(value: Any) -> AttributeValue | None:
    if isinstance(value, str):
        return _clean_string(value)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, Sequence):
        items = list(value)
        if all(isinstance(item, str) for item in items):
            return tuple(_clean_string(item) for item in items)
        if all(isinstance(item, bool | int | float) for item in items):
            return tuple(items)
    return None


def redact_attributes(attributes: Mapping[str, Any] | None) -> dict[str, AttributeValue]:
    cleaned: dict[str, AttributeValue] = {}
    for name, value in (attributes or {}).items():
        if not is_allowed_attribute(name):
            continue
        safe = _clean_value(value)
        if safe is not None:
            cleaned[name] = safe
    return cleaned


def redact_event(event: Event) -> Event:
    attributes = event.attributes or {}
    if event.name == EXCEPTION_EVENT_NAME:
        kept: dict[str, AttributeValue] = {}
        exc_type = attributes.get(EXCEPTION_TYPE_ATTRIBUTE)
        if isinstance(exc_type, str):
            kept[EXCEPTION_TYPE_ATTRIBUTE] = _clean_string(exc_type)
        return Event(EXCEPTION_EVENT_NAME, kept, event.timestamp)
    return Event(
        _clean_string(event.name, MAX_NAME_LENGTH), redact_attributes(attributes), event.timestamp
    )


def redact_span(span: ReadableSpan) -> ReadableSpan:
    links = tuple(
        Link(link.context, redact_attributes(link.attributes)) for link in (span.links or ())
    )
    return ReadableSpan(
        name=_clean_string(span.name, MAX_NAME_LENGTH),
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=redact_attributes(span.attributes),
        events=tuple(redact_event(event) for event in span.events),
        links=links,
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    """Exports redacted copies of finished spans through ``inner``."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.inner.export([redact_span(span) for span in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)
