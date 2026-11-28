"""OpenTelemetry tracing: off by default, provider setup, server spans, sampling (R08-10)."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags
from pydantic import ValidationError

from app.core import langfuse_tracer, tracing
from app.core import logging as app_logging
from app.core.config import Environment, Settings, settings
from app.core.settings.snapshot import sanitized_snapshot
from app.core.settings.tracing import TracingSettings
from app.core.tracing_context import (
    annotate_current_span,
    current_trace_id,
    current_trace_ids,
    operation_span,
    tracing_active,
)
from app.core.tracing_sampling import UntrustedRemoteParentSampler, build_sampler
from tests.test_langfuse_f271 import _make_metadata as _chat_trace_metadata
from tests.tracing_support import (
    TEST_ENDPOINT,
    reset_otel_globals,
    tracing_config,
    tracing_session,
)

INBOUND_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
ORG_ID = UUID("00000000-0000-4000-8000-0000000000b3")


def _app() -> FastAPI:
    app = FastAPI()
    app_logging.attach_access_log_middleware(app)

    @app.get("/api/v1/items/{item_id}")
    async def item(item_id: str, request: Request) -> dict[str, str]:
        if item_id == "authed":
            request.state.auth_principal = SimpleNamespace(organization_id=ORG_ID)
        return {"id": item_id}

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _server_spans(exporter: Any) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]


# -- off by default ------------------------------------------------------------------------


def test_tracing_is_off_by_default() -> None:
    assert Settings.model_fields["tracing_enabled"].default is False
    assert settings.tracing_enabled is False


def test_disabled_installs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_otel_globals()
    build = MagicMock(side_effect=AssertionError("exporter built while disabled"))
    monkeypatch.setattr(tracing, "build_exporter", build)
    config = settings.model_copy(update={"tracing_enabled": False})
    app = _app()

    assert tracing.init_tracing("api", config=config) is False
    assert tracing.instrument_fastapi_app(app, config) is False
    assert tracing.tracer_provider() is None
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    assert tracing_active() is False
    assert not getattr(app, "_is_instrumented_by_opentelemetry", False)
    with operation_span("rudix.qdrant.search", attributes={"x": "c"}) as span:
        assert span is None
        assert current_trace_ids() is None
    annotate_current_span(request_id="r")  # no-op
    with TestClient(app) as client:
        assert client.get("/api/v1/items/1").status_code == 200
    build.assert_not_called()
    tracing.shutdown_tracing()  # no provider: nothing to do


# -- enabled -------------------------------------------------------------------------------


def test_request_produces_server_span_with_route_status_and_request_id() -> None:
    app = _app()
    with tracing_session() as exporter:
        assert tracing.instrument_fastapi_app(app, tracing_config())
        with TestClient(app) as client:
            response = client.get("/api/v1/items/42", headers={"X-Request-ID": "req-b3-1"})
            assert response.status_code == 200
            assert client.get("/api/v1/health").status_code == 200
            assert client.get("/api/v1/items/authed").status_code == 200
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.uninstrument_app(app)

    servers = _server_spans(exporter)
    assert len(servers) == 2, [s.name for s in servers]  # /health is excluded
    span, authed = servers
    assert "rudix.organization_id" not in (span.attributes or {})
    assert (authed.attributes or {})["rudix.organization_id"] == str(ORG_ID)
    attributes = dict(span.attributes or {})
    assert attributes["http.route"] == "/api/v1/items/{item_id}"
    status = attributes.get("http.response.status_code", attributes.get("http.status_code"))
    assert status == 200
    assert attributes["rudix.request_id"] == "req-b3-1"
    assert span.resource.attributes["service.name"] == "rudix-api"
    assert span.resource.attributes["deployment.environment"] == settings.environment.value
    assert span.resource.attributes["service.version"] == settings.api_version


def test_init_is_idempotent_and_shutdown_flushes(caplog: pytest.LogCaptureFixture) -> None:
    with tracing_session("worker", tracing_service_name_prefix="acme") as exporter:
        provider = tracing.tracer_provider()
        assert provider is not None
        assert tracing.init_tracing("worker", config=tracing_config()) is True
        assert tracing.tracer_provider() is provider
        with operation_span(
            "rudix.qdrant.upsert", attributes={"rudix.qdrant.collection": "docs", "x": None}
        ):
            assert current_trace_id() is not None
        caplog.set_level(logging.INFO, logger=tracing._logger.name)
    [span] = exporter.get_finished_spans()
    assert span.resource.attributes["service.name"] == "acme-worker"
    assert span.attributes == {"rudix.qdrant.collection": "docs", "rudix.outcome": "ok"}
    assert tracing.tracer_provider() is None
    assert tracing_active() is False
    assert any(r.getMessage() == "tracing.shutdown" for r in caplog.records)


def test_operation_span_records_error_type_only() -> None:
    with tracing_session() as exporter:
        with (
            pytest.raises(RuntimeError),
            operation_span("rudix.llm.call", attributes={"rudix.llm.model": "m"}),
        ):
            raise RuntimeError("secret detail")
        with pytest.raises(GeneratorExit), operation_span("rudix.llm.call", current=False):
            raise GeneratorExit
        with pytest.raises(asyncio.CancelledError), operation_span("rudix.qdrant.search"):
            raise asyncio.CancelledError
    error_span, closed_span, cancelled_span = exporter.get_finished_spans()
    assert cancelled_span.attributes == {"rudix.outcome": "cancelled"}
    assert error_span.attributes == {
        "rudix.llm.model": "m",
        "rudix.outcome": "error",
        "error.type": "RuntimeError",
    }
    assert not error_span.events
    assert closed_span.attributes == {"rudix.outcome": "closed"}


def test_instrumentation_toggles_and_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    installed: list[str] = []
    monkeypatch.setattr(tracing, "_instrument_sqlalchemy", lambda: installed.append("sa"))
    monkeypatch.setattr(tracing, "_instrument_redis", lambda: installed.append("redis"))

    def broken() -> None:
        raise ImportError("missing")

    monkeypatch.setattr(tracing, "_instrument_httpx", broken)
    caplog.set_level(logging.WARNING, logger=tracing._logger.name)
    with tracing_session(tracing_instrument_redis=False, tracing_instrument_celery=False):
        pass
    assert installed == ["sa"]
    failed = [r for r in caplog.records if r.getMessage() == "tracing.instrumentation_failed"]
    assert failed and failed[0].instrumentation == "httpx"  # type: ignore[attr-defined]


def test_shutdown_logs_uninstrument_and_flush_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=tracing._logger.name)
    with tracing_session(
        tracing_instrument_sqlalchemy=False,
        tracing_instrument_redis=False,
        tracing_instrument_httpx=False,
        tracing_instrument_celery=False,
    ):
        broken = MagicMock()
        broken.uninstrument.side_effect = RuntimeError("x")
        tracing._instrumentors.append(broken)
        provider = tracing.tracer_provider()
        assert provider is not None
        monkeypatch.setattr(provider, "force_flush", MagicMock(side_effect=RuntimeError("y")))
    messages = {r.getMessage() for r in caplog.records}
    assert {"tracing.uninstrument_failed", "tracing.shutdown_failed"} <= messages


# -- exporter configuration ----------------------------------------------------------------


def test_exporter_endpoint_and_headers() -> None:
    config = tracing_config(
        otel_exporter_otlp_headers="x-api-key=abc%20def,bad-entry,other=1",
    )
    assert tracing.traces_endpoint(config) == TEST_ENDPOINT + "/v1/traces"
    full = tracing_config(otel_exporter_otlp_endpoint=TEST_ENDPOINT + "/v1/traces")
    assert tracing.traces_endpoint(full) == TEST_ENDPOINT + "/v1/traces"
    assert tracing.exporter_headers(config) == {"x-api-key": "abc def", "other": "1"}
    assert tracing.exporter_headers(tracing_config()) == {}
    exporter = tracing.build_exporter(config)
    assert exporter._endpoint == TEST_ENDPOINT + "/v1/traces"  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        tracing.traces_endpoint(settings.model_copy(update={"otel_exporter_otlp_endpoint": None}))


def test_excluded_urls_pattern() -> None:
    pattern = tracing.excluded_urls_pattern(["health", "ready", "metrics"])
    assert pattern == "/health/?$,/ready/?$,/metrics/?$"


def test_excluded_paths_record_no_dependency_spans() -> None:
    """A readiness probe's database and dependency calls start no root trace of their own."""
    from sqlalchemy import text

    from app.db import session as db_session

    app = FastAPI()

    async def dependency_calls() -> None:
        engine = db_session.create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        with operation_span("rudix.qdrant.search"):
            pass

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, str]:
        await dependency_calls()
        return {"status": "ok"}

    @app.get("/api/v1/items")
    async def items() -> dict[str, str]:
        await dependency_calls()
        return {"status": "ok"}

    with tracing_session(tracing_instrument_redis=False, tracing_instrument_celery=False) as exp:
        assert tracing.instrument_fastapi_app(app, tracing_config())
        with TestClient(app) as client:
            assert client.get("/api/v1/ready").status_code == 200
            assert exp.get_finished_spans() == ()
            assert client.get("/api/v1/items").status_code == 200
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.uninstrument_app(app)
    spans = exp.get_finished_spans()
    [server] = _server_spans(exp)
    assert (server.attributes or {})["http.route"] == "/api/v1/items"
    children = [s for s in spans if s is not server]
    assert {s.name for s in children} >= {"connect", "rudix.qdrant.search"}
    assert all(s.context.trace_id == server.context.trace_id for s in children)


# -- sampling ------------------------------------------------------------------------------


def _decision(sampler: Any, trace_id: int, parent: Context | None = None) -> bool:
    result = sampler.should_sample(parent, trace_id, "span")
    return bool(result.decision.is_sampled())


def test_sample_ratio_is_respected_with_deterministic_ids() -> None:
    sampler = build_sampler(0.25, trust_remote=False)
    bound = TraceIdRatioBased.get_bound_for_rate(0.25)
    assert _decision(sampler, bound - 1) is True
    assert _decision(sampler, bound) is False
    assert _decision(build_sampler(0.0, trust_remote=False), 1) is False
    assert _decision(build_sampler(1.0, trust_remote=False), (1 << 64) - 1) is True
    # Evenly spread deterministic ids: the sampled fraction matches the ratio.
    step = (1 << 64) // 1000
    sampled = sum(_decision(sampler, i * step + 7) for i in range(1000))
    assert abs(sampled - 250) <= 2


def _remote_parent(sampled: bool, trace_id: int = int(INBOUND_TRACE_ID, 16)) -> Context:
    flags = TraceFlags(TraceFlags.SAMPLED if sampled else TraceFlags.DEFAULT)
    span_context = SpanContext(trace_id, 0x00F067AA0BA902B7, is_remote=True, trace_flags=flags)
    return trace.set_span_in_context(NonRecordingSpan(span_context))


def test_untrusted_remote_parent_ignores_sampled_flag_and_tracestate() -> None:
    trace_id = int(INBOUND_TRACE_ID, 16)
    assert (
        _decision(build_sampler(0.0, trust_remote=False), trace_id, _remote_parent(True)) is False
    )
    always = build_sampler(1.0, trust_remote=False)
    result = always.should_sample(_remote_parent(False), trace_id, "span")
    assert result.decision.is_sampled()
    assert len(result.trace_state) == 0
    # Trusted (the worker, or TRACING_TRUST_INBOUND_CONTEXT=true): the flag decides.
    trusting = build_sampler(0.0, trust_remote=True)
    assert _decision(trusting, trace_id, _remote_parent(True)) is True
    assert _decision(trusting, trace_id, _remote_parent(False)) is False


def test_untrusted_sampler_hashes_with_a_salt() -> None:
    a = UntrustedRemoteParentSampler(0.5, salt=b"a" * 16)
    b = UntrustedRemoteParentSampler(0.5, salt=b"b" * 16)
    ids = range(1, 400)
    decisions_a = [a._sampled(i) for i in ids]
    assert decisions_a == [a._sampled(i) for i in ids]  # deterministic for one salt
    assert decisions_a != [b._sampled(i) for i in ids]  # a client cannot predict it
    assert 120 < sum(decisions_a) < 280
    assert "0.5" in a.get_description()
    assert tracing.trusts_remote_parent("worker", tracing_config()) is True
    assert tracing.trusts_remote_parent("api", tracing_config()) is False
    assert tracing.trusts_remote_parent("mcp", tracing_config(tracing_trust_inbound_context=True))


def _request_spans(headers: dict[str, str], **overrides: Any) -> list[Any]:
    app = _app()  # a fresh app per provider: the middleware binds its tracer once
    with tracing_session(**overrides) as exporter:
        tracing.instrument_fastapi_app(app, tracing_config())
        with TestClient(app) as client:
            client.get("/api/v1/items/1", headers=headers)
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.uninstrument_app(app)
    return _server_spans(exporter)


def test_inbound_traceparent_does_not_force_sampling() -> None:
    sampled_parent = {"traceparent": f"00-{INBOUND_TRACE_ID}-00f067aa0ba902b7-01"}
    assert _request_spans(sampled_parent, tracing_sample_ratio=0.0) == []
    # Trusted: the caller's sampled flag decides and the caller's trace continues.
    [span] = _request_spans(
        sampled_parent, tracing_sample_ratio=0.0, tracing_trust_inbound_context=True
    )
    assert format(span.context.trace_id, "032x") == INBOUND_TRACE_ID
    # Untrusted but sampled locally: the trace id is kept for correlation, tracestate is not.
    [span] = _request_spans(
        {**sampled_parent, "tracestate": "vendor=forced"}, tracing_sample_ratio=1.0
    )
    assert format(span.context.trace_id, "032x") == INBOUND_TRACE_ID
    assert len(span.context.trace_state) == 0


# -- correlation ---------------------------------------------------------------------------


def test_log_lines_include_trace_and_span_ids(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved = list(root.handlers)
    for handler in saved:
        root.removeHandler(handler)
    try:
        app_logging.configure_logging("INFO", environment="production", log_format="json")
        with tracing_session():
            with operation_span("rudix.llm.call") as span:
                assert span is not None
                app_logging.get_logger("tests.tracing").info("tracing.correlated")
                expected = format(span.get_span_context().trace_id, "032x")
            app_logging.get_logger("tests.tracing").info("tracing.outside")
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved:
            root.addHandler(handler)
        structlog.reset_defaults()
        app_logging.configure_logging(settings.log_level)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if "{" in line]
    correlated = next(line for line in lines if line["event"] == "tracing.correlated")
    assert correlated["trace_id"] == expected
    assert len(correlated["span_id"]) == 16
    outside = next(line for line in lines if line["event"] == "tracing.outside")
    assert "trace_id" not in outside


def test_langfuse_trace_metadata_carries_otel_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(langfuse_tracer, "_langfuse_client", client)
    metadata = _chat_trace_metadata()
    langfuse_tracer._emit_chat_trace(metadata)
    assert "otel_trace_id" not in client.trace.call_args.kwargs["metadata"]
    with tracing_session(), operation_span("rudix.request") as span:
        assert span is not None
        langfuse_tracer._emit_chat_trace(metadata)
        expected = format(span.get_span_context().trace_id, "032x")
    assert client.trace.call_args.kwargs["metadata"]["otel_trace_id"] == expected


# -- settings ------------------------------------------------------------------------------


def _settings(**values: Any) -> Settings:
    return Settings(**values)


def test_enabled_requires_endpoint() -> None:
    with pytest.raises(ValidationError, match="OTEL_EXPORTER_OTLP_ENDPOINT is required"):
        _settings(tracing_enabled=True)
    assert _settings(tracing_enabled=True, otel_exporter_otlp_endpoint="http://c:4318")


class _TracingWithEnvironment(TracingSettings):
    environment: Environment = Environment.development


@pytest.mark.parametrize("environment", [Environment.staging, Environment.production])
def test_staging_and_production_require_https(environment: Environment) -> None:
    base = {"environment": environment, "tracing_enabled": True}
    with pytest.raises(ValidationError, match="must use https"):
        _TracingWithEnvironment(**base, otel_exporter_otlp_endpoint="http://collector:4318")
    assert _TracingWithEnvironment(
        **base,
        otel_exporter_otlp_endpoint="http://collector:4318",
        tracing_allow_insecure_endpoint=True,
    )
    assert _TracingWithEnvironment(**base, otel_exporter_otlp_endpoint="https://collector:4318")
    dev = {"environment": Environment.development, "tracing_enabled": True}
    assert _TracingWithEnvironment(**dev, otel_exporter_otlp_endpoint="http://collector:4318")


def test_tracing_setting_ranges_and_lists() -> None:
    with pytest.raises(ValidationError):
        _settings(tracing_sample_ratio=1.5)
    with pytest.raises(ValidationError):
        _settings(tracing_excluded_paths="health,bad path")
    with pytest.raises(ValidationError):
        _settings(tracing_excluded_paths=42)
    parsed = _settings(tracing_excluded_paths=" /health/ ,ready,health,,")
    assert parsed.tracing_excluded_paths == ["health", "ready"]
    defaults = _settings(tracing_excluded_paths=None)
    assert defaults.tracing_excluded_paths == ["health", "ready", "metrics"]
    with pytest.raises(ValidationError):
        _settings(tracing_service_name_prefix="Bad Prefix")


def test_snapshot_exposes_only_switch_ratio_and_endpoint_set() -> None:
    config = tracing_config(otel_exporter_otlp_headers="authorization=Bearer%20sk-hidden")
    snapshot = sanitized_snapshot(config)
    infra = snapshot["infrastructure"]
    assert infra["tracing_enabled"] is True
    assert infra["tracing_sample_ratio"] == 1.0
    assert infra["otel_exporter_otlp_endpoint_set"] is True
    dumped = json.dumps(snapshot, default=str)
    assert "collector.example.invalid" not in dumped
    assert "sk-hidden" not in dumped
    assert "sk-hidden" not in repr(config.otel_exporter_otlp_headers)
