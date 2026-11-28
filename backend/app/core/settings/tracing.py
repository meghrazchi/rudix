"""OpenTelemetry tracing settings (0.8.0, R08-10).

Owned by B3. Tracing stays off by default: with ``TRACING_ENABLED=false`` no tracer provider,
exporter, or instrumentation is installed (``app/core/tracing.py``). Nothing is exported while
no OTLP endpoint is set, and enabling tracing without one fails validation.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode

DEFAULT_TRACING_EXCLUDED_PATHS: tuple[str, ...] = ("health", "ready", "metrics")


class TracingSettings(BaseModel):
    """Tracing switch, OTLP/HTTP exporter endpoint, sampling, and instrumentation toggles."""

    # Master switch. False (the default) keeps request-ID logs plus Langfuse only.
    tracing_enabled: bool = False
    # OTLP/HTTP (protobuf) collector base URL, e.g. ``https://collector.internal:4318``;
    # ``/v1/traces`` is appended unless the path already ends with it.
    # Env ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the field name, matched case-insensitively).
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    # ``key=value,key2=value2`` headers sent to the collector (vendor auth). Never logged.
    otel_exporter_otlp_headers: SecretStr | None = None
    # Fraction of new traces recorded (head sampling by trace id).
    tracing_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    # False: an inbound ``traceparent`` keeps its trace id (correlation) but its sampled flag
    # and ``tracestate`` are ignored; the API decides locally so a client cannot force
    # sampling. True: follow the inbound sampled flag (only behind a trusted proxy).
    tracing_trust_inbound_context: bool = False
    # ``service.name`` is ``<prefix>-<runtime>`` (api, worker, mcp).
    tracing_service_name_prefix: str = Field(
        default="rudix", min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    # Last path segments that never produce a server span (comma list).
    tracing_excluded_paths: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_TRACING_EXCLUDED_PATHS)
    )
    tracing_instrument_sqlalchemy: bool = True
    tracing_instrument_redis: bool = True
    tracing_instrument_httpx: bool = True
    tracing_instrument_celery: bool = True
    # Allow an http:// collector in staging or production (private network only).
    tracing_allow_insecure_endpoint: bool = False

    @field_validator("tracing_excluded_paths", mode="before")
    @classmethod
    def _parse_excluded_paths(cls, value: Any) -> list[str]:
        if value is None:
            return list(DEFAULT_TRACING_EXCLUDED_PATHS)
        raw_items = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw_items, list | tuple | set | frozenset):
            raise ValueError("tracing_excluded_paths must be a comma list or list")
        paths: list[str] = []
        for item in raw_items:
            path = str(item).strip().strip("/")
            if not path or path in paths:
                continue
            if not all(ch.isalnum() or ch in "-_/." for ch in path):
                raise ValueError(f"tracing_excluded_paths: invalid path {path!r}")
            paths.append(path)
        return paths

    @model_validator(mode="after")
    def _validate_tracing_endpoint(self) -> TracingSettings:
        if not self.tracing_enabled:
            return self
        endpoint = self.otel_exporter_otlp_endpoint
        if endpoint is None:
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT is required when TRACING_ENABLED=true")
        environment = getattr(getattr(self, "environment", None), "value", None)
        if (
            environment in {"staging", "production"}
            and endpoint.scheme != "https"
            and not self.tracing_allow_insecure_endpoint
        ):
            raise ValueError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must use https:// in staging or production "
                "(set TRACING_ALLOW_INSECURE_ENDPOINT=true for a private collector)"
            )
        return self
