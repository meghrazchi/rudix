"""OpenTelemetry tracing for the API, workers, and MCP server (0.8.0, R08-10).

Off by default. With ``TRACING_ENABLED=false`` ``init_tracing`` returns at once: no tracer
provider, exporter, propagator, or instrumentation is installed and no span is created.

With tracing on, one ``TracerProvider`` per process exports through OTLP/HTTP (protobuf) to
``OTEL_EXPORTER_OTLP_ENDPOINT``. Every span passes ``RedactingSpanExporter`` first, which
keeps allowlisted, content-free attributes only (``tracing_redaction.py``). Sampling is in
``tracing_sampling.py``. Instrumented: FastAPI (``instrument_fastapi_app``, called from
``app/main.py``), SQLAlchemy (commenter off), Redis (arguments sanitised, then dropped by the
allowlist), httpx, and Celery (producer and consumer through ``traceparent`` headers).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanProcessor,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.tracing_context import set_tracing_active
from app.core.tracing_redaction import RedactingSpanExporter
from app.core.tracing_sampling import build_sampler

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

    from app.core.config import Settings

Runtime = Literal["api", "worker", "mcp"]
ProcessorKind = Literal["batch", "simple"]

TRACES_PATH = "/v1/traces"
# Stable HTTP semantic conventions (``http.request.method``, ``url.scheme``,
# ``server.address``), which the redaction allowlist names. Read once, at the first
# instrumentation; an operator value is kept.
SEMCONV_OPT_IN_ENV = "OTEL_SEMCONV_STABILITY_OPT_IN"
SEMCONV_OPT_IN_DEFAULT = "http"
SHUTDOWN_TIMEOUT_MILLIS = 5000
EXPORT_TIMEOUT_SECONDS = 10.0

_logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None
_instrumentors: list[BaseInstrumentor] = []
_restore_hooks: list[Callable[[], None]] = []


def _settings() -> Settings:
    from app.core.config import settings

    return settings


def traces_endpoint(config: Settings) -> str:
    """The OTLP/HTTP traces URL: the endpoint, with ``/v1/traces`` appended when missing."""
    if config.otel_exporter_otlp_endpoint is None:
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT is not set")
    base = str(config.otel_exporter_otlp_endpoint).rstrip("/")
    return base if base.endswith(TRACES_PATH) else base + TRACES_PATH


def exporter_headers(config: Settings) -> dict[str, str]:
    """Collector headers from ``OTEL_EXPORTER_OTLP_HEADERS`` (``k=v,k2=v2``, URL-encoded)."""
    from opentelemetry.util.re import parse_env_headers

    if config.otel_exporter_otlp_headers is None:
        return {}
    raw = config.otel_exporter_otlp_headers.get_secret_value()
    return dict(parse_env_headers(raw, liberal=True))


def build_exporter(config: Settings) -> SpanExporter:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(
        endpoint=traces_endpoint(config),
        headers=exporter_headers(config),
        timeout=EXPORT_TIMEOUT_SECONDS,
    )


def build_resource(runtime: Runtime, config: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": f"{config.tracing_service_name_prefix}-{runtime}",
            "deployment.environment": config.environment.value,
            "service.version": config.api_version,
        }
    )


def trusts_remote_parent(runtime: Runtime, config: Settings) -> bool:
    """Workers read ``traceparent`` written by our own producers, so they always follow it."""
    return runtime == "worker" or config.tracing_trust_inbound_context


def excluded_urls_pattern(paths: list[str]) -> str:
    """Comma-joined regexes for the ASGI middleware: ``/<path>`` at the end of the URL."""
    return ",".join(rf"/{re.escape(path)}/?$" for path in paths)


def init_tracing(
    runtime: Runtime,
    *,
    config: Settings | None = None,
    exporter: SpanExporter | None = None,
    processor: ProcessorKind = "batch",
    sampler_salt: bytes | None = None,
) -> bool:
    """Install the provider, exporter, and instrumentations; False (no-op) when disabled.

    Idempotent: a second call in the same process returns True without changes.
    """
    global _provider
    config = config or _settings()
    if not config.tracing_enabled:
        return False
    if _provider is not None:
        return True
    os.environ.setdefault(SEMCONV_OPT_IN_ENV, SEMCONV_OPT_IN_DEFAULT)
    provider = TracerProvider(
        resource=build_resource(runtime, config),
        sampler=build_sampler(
            config.tracing_sample_ratio,
            trust_remote=trusts_remote_parent(runtime, config),
            salt=sampler_salt,
        ),
    )
    redacting = RedactingSpanExporter(exporter or build_exporter(config))
    span_processor: SpanProcessor = (
        SimpleSpanProcessor(redacting) if processor == "simple" else BatchSpanProcessor(redacting)
    )
    provider.add_span_processor(span_processor)
    trace.set_tracer_provider(provider)
    # W3C trace context only: inbound ``baggage`` is never forwarded to workers.
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    _provider = provider
    set_tracing_active(True)
    _install_instrumentations(config)
    _logger.info(
        "tracing.init",
        extra={
            "runtime": runtime,
            "sample_ratio": config.tracing_sample_ratio,
            "trust_inbound_context": config.tracing_trust_inbound_context,
            "endpoint_set": config.otel_exporter_otlp_endpoint is not None,
        },
    )
    return True


def tracer_provider() -> TracerProvider | None:
    """The provider ``init_tracing`` installed in this process, or None."""
    return _provider


def shutdown_tracing(timeout_millis: int = SHUTDOWN_TIMEOUT_MILLIS) -> None:
    """Flush pending spans (bounded by ``timeout_millis``), then remove instrumentation."""
    global _provider
    provider = _provider
    if provider is None:
        return
    set_tracing_active(False)
    for instrumentor in reversed(_instrumentors):
        try:
            instrumentor.uninstrument()
        except Exception as exc:
            _logger.warning("tracing.uninstrument_failed", extra={"error": type(exc).__name__})
    _instrumentors.clear()
    for restore in reversed(_restore_hooks):
        restore()
    _restore_hooks.clear()
    try:
        flushed = provider.force_flush(timeout_millis)
        provider.shutdown()
    except Exception as exc:
        _logger.warning("tracing.shutdown_failed", extra={"error": type(exc).__name__})
        flushed = False
    _provider = None
    _logger.info("tracing.shutdown", extra={"flushed": flushed})


def instrument_fastapi_app(app: FastAPI, config: Settings | None = None) -> bool:
    """Wrap ``app`` in the OpenTelemetry ASGI middleware; False (untouched) when disabled.

    Runs when the app module is imported, before ``init_tracing`` in the lifespan: the
    middleware resolves the global provider lazily. Health, readiness, and metrics paths
    (``TRACING_EXCLUDED_PATHS``) never produce a span.
    """
    config = config or _settings()
    if not config.tracing_enabled:
        return False
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    os.environ.setdefault(SEMCONV_OPT_IN_ENV, SEMCONV_OPT_IN_DEFAULT)
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=excluded_urls_pattern(config.tracing_excluded_paths) or None,
        exclude_spans=["receive", "send"],
    )
    return True


def _install_instrumentations(config: Settings) -> None:
    steps: list[tuple[bool, str, Callable[[], None]]] = [
        (config.tracing_instrument_sqlalchemy, "sqlalchemy", _instrument_sqlalchemy),
        (config.tracing_instrument_redis, "redis", _instrument_redis),
        (config.tracing_instrument_httpx, "httpx", _instrument_httpx),
        (config.tracing_instrument_celery, "celery", _instrument_celery),
    ]
    for enabled, name, install in steps:
        if not enabled:
            continue
        try:
            install()
        except Exception as exc:
            _logger.warning(
                "tracing.instrumentation_failed",
                extra={"instrumentation": name, "error": type(exc).__name__},
            )


def _register(instrumentor: BaseInstrumentor, **kwargs: Any) -> None:
    instrumentor.instrument(**kwargs)
    _instrumentors.append(instrumentor)


def _instrument_sqlalchemy() -> None:
    """Instrument existing engines and every engine ``app.db.session`` creates later.

    The engine module binds ``create_async_engine`` at import time, so the instrumentor's
    wrapper of ``sqlalchemy.ext.asyncio.create_async_engine`` is reached through a hook
    that resolves the module attribute at call time (maintenance and replica engines).
    """
    import sqlalchemy.ext.asyncio as sa_asyncio
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from app.db import session as db_session

    engines = [db_session.engine.sync_engine]
    for name in ("_maintenance_engine", "_reporting_engine"):
        existing = getattr(db_session, name, None)
        if existing is not None:
            engines.append(existing.sync_engine)
    _register(
        SQLAlchemyInstrumentor(),
        engines=engines,
        enable_commenter=False,
        enable_attribute_commenter=False,
    )
    original = db_session.create_async_engine

    def _create_async_engine(*args: Any, **kwargs: Any) -> Any:
        return sa_asyncio.create_async_engine(*args, **kwargs)

    db_session.create_async_engine = _create_async_engine  # type: ignore[assignment]

    def _restore() -> None:
        db_session.create_async_engine = original  # type: ignore[assignment]

    _restore_hooks.append(_restore)


def _instrument_redis() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    # The instrumentation replaces command arguments with ``?``; the allowlist then drops
    # ``db.statement`` entirely.
    _register(RedisInstrumentor())


def _instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    _register(HTTPXClientInstrumentor())


def _instrument_celery() -> None:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    _register(CeleryInstrumentor())
