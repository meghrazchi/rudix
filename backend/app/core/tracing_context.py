"""Trace correlation helpers and content-free manual spans (R08-10).

Depends on the OpenTelemetry API only, so logging, Langfuse, Qdrant, and the LLM wrapper can
import it cheaply. Every helper is a no-op while tracing is off (``tracing_active()`` false):
no tracer is looked up and no span object is created.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Final

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue

TRACER_NAME: Final = "rudix"

_active = False


def set_tracing_active(active: bool) -> None:
    """Called by ``init_tracing`` / ``shutdown_tracing`` only."""
    global _active
    _active = active


def tracing_active() -> bool:
    return _active


def current_trace_ids() -> tuple[str, str] | None:
    """``(trace_id, span_id)`` as lowercase hex of the active, valid span, else None."""
    if not _active:
        return None
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def current_trace_id() -> str | None:
    ids = current_trace_ids()
    return ids[0] if ids else None


def annotate_current_span(**attributes: AttributeValue | None) -> None:
    """Set ``rudix.<name>`` attributes on the active span (None values are skipped)."""
    if not _active:
        return
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for name, value in attributes.items():
        if value is not None:
            span.set_attribute(f"rudix.{name}", value)


def _outcome_for(exc: BaseException) -> str:
    if isinstance(exc, GeneratorExit):
        return "closed"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    return "error"


@contextmanager
def operation_span(
    name: str,
    *,
    current: bool = True,
    kind: SpanKind = SpanKind.CLIENT,
    attributes: Mapping[str, AttributeValue | None] | None = None,
) -> Iterator[Span | None]:
    """A span around one dependency call with ``attributes`` and ``rudix.outcome``.

    No content is recorded: callers pass identifiers (provider, model, collection) under
    their allowlisted names (``rudix.llm.model``, ``rudix.qdrant.collection``) only.
    The exception message is never recorded, only ``error.type``. ``current=False`` keeps
    the span out of the context (async generators that yield across tasks).
    """
    if not _active:
        yield None
        return
    tracer = trace.get_tracer(TRACER_NAME)
    span = tracer.start_span(name, kind=kind, record_exception=False)
    for key, value in (attributes or {}).items():
        if value is not None:
            span.set_attribute(key, value)
    try:
        if current:
            with trace.use_span(
                span, end_on_exit=False, record_exception=False, set_status_on_exception=False
            ):
                yield span
        else:
            yield span
    except BaseException as exc:
        span.set_attribute("rudix.outcome", _outcome_for(exc))
        if not isinstance(exc, GeneratorExit | asyncio.CancelledError):
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
        raise
    else:
        span.set_attribute("rudix.outcome", "ok")
    finally:
        span.end()
