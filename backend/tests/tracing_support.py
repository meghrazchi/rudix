"""Shared helpers for the tracing tests (R08-10).

OpenTelemetry allows one global tracer provider per process; ``reset_otel_globals`` puts the
API back in its never-configured state so each test installs its own provider. The private
names are the ones ``opentelemetry-test-utils`` resets (not a dependency here).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util._once import Once

from app.core import tracing
from app.core.config import Settings, settings

TEST_ENDPOINT = "https://collector.example.invalid:4318"


def reset_otel_globals() -> None:
    trace._TRACER_PROVIDER_SET_ONCE = Once()  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


def tracing_config(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tracing_enabled": True,
        "otel_exporter_otlp_endpoint": TEST_ENDPOINT,
        "tracing_sample_ratio": 1.0,
    }
    values.update(overrides)
    if isinstance(values["otel_exporter_otlp_endpoint"], str):
        from pydantic import AnyHttpUrl

        values["otel_exporter_otlp_endpoint"] = AnyHttpUrl(values["otel_exporter_otlp_endpoint"])
    if isinstance(values.get("otel_exporter_otlp_headers"), str):
        from pydantic import SecretStr

        values["otel_exporter_otlp_headers"] = SecretStr(values["otel_exporter_otlp_headers"])
    return settings.model_copy(update=values)


@contextmanager
def tracing_session(
    runtime: tracing.Runtime = "api", **overrides: Any
) -> Iterator[InMemorySpanExporter]:
    """Tracing on with an in-memory exporter behind the redacting wrapper."""
    reset_otel_globals()
    textmap = propagate.get_global_textmap()
    exporter = InMemorySpanExporter()
    salt = overrides.pop("sampler_salt", None)
    config = tracing_config(**overrides)
    assert tracing.init_tracing(
        runtime, config=config, exporter=exporter, processor="simple", sampler_salt=salt
    )
    try:
        yield exporter
    finally:
        tracing.shutdown_tracing()
        reset_otel_globals()
        propagate.set_global_textmap(textmap)


def span_text(span: ReadableSpan) -> str:
    """Everything an exported span carries, as one string for sentinel checks."""
    parts: list[str] = [span.name, str(span.status.description or "")]
    parts.extend(f"{k}={v}" for k, v in (span.attributes or {}).items())
    for event in span.events:
        parts.append(event.name)
        parts.extend(f"{k}={v}" for k, v in (event.attributes or {}).items())
    for link in span.links:
        parts.extend(f"{k}={v}" for k, v in (link.attributes or {}).items())
    return "\n".join(parts)
