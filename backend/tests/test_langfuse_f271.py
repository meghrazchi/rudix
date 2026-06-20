"""Backend tests for F271: Langfuse self-hosted observability integration.

Covers:
  A. init_langfuse disabled — no-op when LANGFUSE_ENABLED=false
  B. init_langfuse missing keys — graceful warning, client stays None
  C. init_langfuse missing base URL — graceful warning, client stays None
  D. init_langfuse package not installed — ImportError handled gracefully
  E. init_langfuse success — client is created and is_enabled() returns True
  F. trace_chat_query disabled — returns silently when client not initialized
  G. trace_chat_query sample_rate=0.0 — never traces when sampling disabled
  H. trace_chat_query full mode — calls Langfuse trace/span/generation methods
  I. trace_chat_query redaction=all — sends redacted question and answer
  J. trace_chat_query redaction=inputs — redacts question, sends real answer
  K. trace_chat_query capture_input_output=false — redacts both
  L. trace_chat_query failure is silent — Langfuse SDK exception not propagated
  M. _hash_user_id — deterministic, non-reversible, 18 chars with u_ prefix
  N. check_langfuse_health disabled — returns enabled=false without HTTP call
  O. check_langfuse_health reachable — returns reachable=true on 200
  P. check_langfuse_health unreachable — returns reachable=false and error class
  Q. GET /admin/langfuse/status — member gets 403
  R. GET /admin/langfuse/status — admin sees status without secrets
  S. shutdown_langfuse — calls flush() safely, handles missing client
  T. LangfuseRedactionMode enum values correct
  U. Config snapshot includes langfuse fields without secret values

Run:
    pytest tests/test_langfuse_f271.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

import app.core.langfuse_tracer as tracer_module
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, LangfuseRedactionMode, settings
from app.core.langfuse_tracer import (
    ChatTraceMetadata,
    _hash_user_id,
    check_langfuse_health,
    init_langfuse,
    shutdown_langfuse,
    trace_chat_query,
)
from app.main import app
from app.models.enums import OrganizationRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(**overrides: object) -> ChatTraceMetadata:
    base = dict(
        organization_id="org-123",
        user_id="user-abc",
        session_id="sess-001",
        message_id="msg-001",
        question="What is RAG?",
        answer="RAG is retrieval-augmented generation.",
        scope_mode="all",
        source_scope_label="all",
        retrieved_count=5,
        selected_count=3,
        rerank_applied=True,
        cited_count=2,
        not_found=False,
        citation_validation_failed=False,
        confidence_score=0.82,
        confidence_category="high",
        llm_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        embedding_prompt_tokens=10,
        llm_prompt_tokens=400,
        llm_completion_tokens=120,
        llm_total_tokens=530,
        estimated_cost_usd=Decimal("0.0005"),
        latencies_ms={"embed": 80, "retrieve": 110, "rerank": 30, "llm": 1200},
        answer_latency_ms=1500,
        detected_language="en",
        answer_language_used="en",
    )
    base.update(overrides)
    return ChatTraceMetadata(**base)  # type: ignore[arg-type]


def _reset_tracer() -> None:
    """Reset module-level state between tests."""
    tracer_module._langfuse_client = None
    tracer_module._initialized_pids.clear()


# ---------------------------------------------------------------------------
# A. Disabled mode — LANGFUSE_ENABLED=false
# ---------------------------------------------------------------------------


def test_init_langfuse_disabled_when_not_enabled() -> None:
    _reset_tracer()
    with patch.object(settings, "langfuse_enabled", False):
        result = init_langfuse(runtime="api")
    assert result is False
    assert tracer_module._langfuse_client is None


# ---------------------------------------------------------------------------
# B. Missing keys
# ---------------------------------------------------------------------------


def test_init_langfuse_disabled_missing_keys() -> None:
    _reset_tracer()
    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_public_key", None),
        patch.object(settings, "langfuse_secret_key", None),
        patch.object(settings, "langfuse_base_url", "http://localhost:3030"),
    ):
        result = init_langfuse(runtime="api")
    assert result is False
    assert tracer_module._langfuse_client is None


# ---------------------------------------------------------------------------
# C. Missing base URL
# ---------------------------------------------------------------------------


def test_init_langfuse_disabled_missing_base_url() -> None:
    _reset_tracer()
    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_public_key", "pk-test"),
        patch.object(
            settings, "langfuse_secret_key", MagicMock(get_secret_value=lambda: "sk-test")
        ),
        patch.object(settings, "langfuse_base_url", None),
    ):
        result = init_langfuse(runtime="api")
    assert result is False
    assert tracer_module._langfuse_client is None


# ---------------------------------------------------------------------------
# D. ImportError handled gracefully
# ---------------------------------------------------------------------------


def test_init_langfuse_handles_import_error() -> None:
    _reset_tracer()
    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_public_key", "pk-test"),
        patch.object(
            settings, "langfuse_secret_key", MagicMock(get_secret_value=lambda: "sk-test")
        ),
        patch.object(settings, "langfuse_base_url", "http://localhost:3030"),
        patch("builtins.__import__", side_effect=ImportError("langfuse not installed")),
    ):
        result = init_langfuse(runtime="api")
    assert result is False


# ---------------------------------------------------------------------------
# E. Successful initialisation
# ---------------------------------------------------------------------------


def test_init_langfuse_success() -> None:
    _reset_tracer()
    mock_client = MagicMock()
    mock_langfuse_class = MagicMock(return_value=mock_client)

    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_public_key", "pk-live"),
        patch.object(
            settings, "langfuse_secret_key", MagicMock(get_secret_value=lambda: "sk-live")
        ),
        patch.object(settings, "langfuse_base_url", "http://langfuse:3030"),
        patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_class)}),
    ):
        result = init_langfuse(runtime="api")

    assert result is True
    assert tracer_module._langfuse_client is mock_client


# ---------------------------------------------------------------------------
# F. trace_chat_query — disabled mode
# ---------------------------------------------------------------------------


def test_trace_chat_query_disabled_is_noop() -> None:
    _reset_tracer()
    # Should not raise and should not interact with any Langfuse client.
    trace_chat_query(_make_metadata())


# ---------------------------------------------------------------------------
# G. trace_chat_query — sample_rate=0.0
# ---------------------------------------------------------------------------


def test_trace_chat_query_zero_sample_rate_never_traces() -> None:
    _reset_tracer()
    mock_client = MagicMock()
    tracer_module._langfuse_client = mock_client

    with patch.object(settings, "langfuse_sample_rate", 0.0):
        trace_chat_query(_make_metadata())

    mock_client.trace.assert_not_called()


# ---------------------------------------------------------------------------
# H. trace_chat_query — full RAG mode, all spans created
# ---------------------------------------------------------------------------


def test_trace_chat_query_full_rag_creates_spans() -> None:
    _reset_tracer()
    mock_span = MagicMock()
    mock_span.end = MagicMock()
    mock_generation = MagicMock()
    mock_generation.end = MagicMock()
    mock_trace = MagicMock()
    mock_trace.span.return_value = mock_span
    mock_trace.generation.return_value = mock_generation
    mock_client = MagicMock()
    mock_client.trace.return_value = mock_trace
    tracer_module._langfuse_client = mock_client

    with (
        patch.object(settings, "langfuse_sample_rate", 1.0),
        patch.object(settings, "langfuse_capture_input_output", True),
        patch.object(settings, "langfuse_redaction_mode", LangfuseRedactionMode.none),
    ):
        trace_chat_query(_make_metadata())

    mock_client.trace.assert_called_once()
    call_kwargs = mock_client.trace.call_args.kwargs
    assert call_kwargs["name"] == "rag.chat"
    assert call_kwargs["input"] == "What is RAG?"
    assert call_kwargs["output"] == "RAG is retrieval-augmented generation."
    assert call_kwargs["session_id"] == "sess-001"

    # Embedding, retrieval, rerank, generation, citation spans expected.
    span_names = [c.kwargs["name"] for c in mock_trace.span.call_args_list]
    assert "embedding.query" in span_names
    assert "retrieval.vector_search" in span_names
    assert "retrieval.rerank" in span_names
    assert "citations.validate" in span_names
    mock_trace.generation.assert_called_once()
    assert mock_trace.generation.call_args.kwargs["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# I. trace_chat_query — redaction=all
# ---------------------------------------------------------------------------


def test_trace_chat_query_redaction_all() -> None:
    _reset_tracer()
    mock_trace = MagicMock()
    mock_trace.span.return_value = MagicMock()
    mock_trace.generation.return_value = MagicMock()
    mock_client = MagicMock()
    mock_client.trace.return_value = mock_trace
    tracer_module._langfuse_client = mock_client

    with (
        patch.object(settings, "langfuse_sample_rate", 1.0),
        patch.object(settings, "langfuse_capture_input_output", True),
        patch.object(settings, "langfuse_redaction_mode", LangfuseRedactionMode.all),
    ):
        trace_chat_query(_make_metadata())

    call_kwargs = mock_client.trace.call_args.kwargs
    assert call_kwargs["input"] == "<redacted:question>"
    assert call_kwargs["output"] == "<redacted:answer>"


# ---------------------------------------------------------------------------
# J. trace_chat_query — redaction=inputs
# ---------------------------------------------------------------------------


def test_trace_chat_query_redaction_inputs_only() -> None:
    _reset_tracer()
    mock_trace = MagicMock()
    mock_trace.span.return_value = MagicMock()
    mock_trace.generation.return_value = MagicMock()
    mock_client = MagicMock()
    mock_client.trace.return_value = mock_trace
    tracer_module._langfuse_client = mock_client

    with (
        patch.object(settings, "langfuse_sample_rate", 1.0),
        patch.object(settings, "langfuse_capture_input_output", True),
        patch.object(settings, "langfuse_redaction_mode", LangfuseRedactionMode.inputs),
    ):
        trace_chat_query(_make_metadata())

    call_kwargs = mock_client.trace.call_args.kwargs
    assert call_kwargs["input"] == "<redacted:question>"
    assert call_kwargs["output"] == "RAG is retrieval-augmented generation."


# ---------------------------------------------------------------------------
# K. trace_chat_query — capture_input_output=false
# ---------------------------------------------------------------------------


def test_trace_chat_query_capture_disabled_redacts_both() -> None:
    _reset_tracer()
    mock_trace = MagicMock()
    mock_trace.span.return_value = MagicMock()
    mock_trace.generation.return_value = MagicMock()
    mock_client = MagicMock()
    mock_client.trace.return_value = mock_trace
    tracer_module._langfuse_client = mock_client

    with (
        patch.object(settings, "langfuse_sample_rate", 1.0),
        patch.object(settings, "langfuse_capture_input_output", False),
        patch.object(settings, "langfuse_redaction_mode", LangfuseRedactionMode.none),
    ):
        trace_chat_query(_make_metadata())

    call_kwargs = mock_client.trace.call_args.kwargs
    assert call_kwargs["input"] == "<redacted:question>"
    assert call_kwargs["output"] == "<redacted:answer>"


# ---------------------------------------------------------------------------
# L. trace_chat_query — SDK failure is silent
# ---------------------------------------------------------------------------


def test_trace_chat_query_sdk_failure_does_not_propagate() -> None:
    _reset_tracer()
    mock_client = MagicMock()
    mock_client.trace.side_effect = RuntimeError("Langfuse exploded")
    tracer_module._langfuse_client = mock_client

    with patch.object(settings, "langfuse_sample_rate", 1.0):
        # Must not raise.
        trace_chat_query(_make_metadata())


# ---------------------------------------------------------------------------
# M. _hash_user_id
# ---------------------------------------------------------------------------


def test_hash_user_id_deterministic_and_prefixed() -> None:
    h1 = _hash_user_id("user-abc")
    h2 = _hash_user_id("user-abc")
    h3 = _hash_user_id("user-xyz")

    assert h1 == h2
    assert h1 != h3
    assert h1.startswith("u_")
    assert len(h1) == 18  # "u_" + 16 hex chars


def test_hash_user_id_non_reversible() -> None:
    h = _hash_user_id("sensitive-user-id")
    assert "sensitive" not in h
    assert "user" not in h


# ---------------------------------------------------------------------------
# N. check_langfuse_health — disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_disabled() -> None:
    with patch.object(settings, "langfuse_enabled", False):
        result = await check_langfuse_health()

    assert result["enabled"] is False
    assert result["reachable"] is False


# ---------------------------------------------------------------------------
# O. check_langfuse_health — reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_reachable() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_base_url", "http://langfuse:3030"),
        patch("httpx.AsyncClient", return_value=mock_async_client),
    ):
        result = await check_langfuse_health()

    assert result["enabled"] is True
    assert result["reachable"] is True
    assert result["last_error"] is None


# ---------------------------------------------------------------------------
# P. check_langfuse_health — unreachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_unreachable() -> None:
    import httpx

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_async_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(settings, "langfuse_enabled", True),
        patch.object(settings, "langfuse_base_url", "http://langfuse-down:3030"),
        patch("httpx.AsyncClient", return_value=mock_async_client),
    ):
        result = await check_langfuse_health()

    assert result["reachable"] is False
    assert result["last_error"] == "ConnectError"


# ---------------------------------------------------------------------------
# Q / R. GET /admin/langfuse/status endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def _admin_token() -> str:
    if settings.auth_provider != AuthProvider.app:
        pytest.skip("app auth required")
    return create_app_access_token(
        user_id="admin-user",
        organization_id="org-001",
        roles=[OrganizationRole.admin.value],
        secret=settings.app_auth_secret.get_secret_value(),
        issuer=settings.app_auth_issuer,
        audience=settings.app_auth_audience,
        ttl_seconds=3600,
    )


@pytest.fixture()
def _member_token() -> str:
    if settings.auth_provider != AuthProvider.app:
        pytest.skip("app auth required")
    return create_app_access_token(
        user_id="member-user",
        organization_id="org-001",
        roles=[OrganizationRole.member.value],
        secret=settings.app_auth_secret.get_secret_value(),
        issuer=settings.app_auth_issuer,
        audience=settings.app_auth_audience,
        ttl_seconds=3600,
    )


@pytest.mark.asyncio
async def test_langfuse_status_member_gets_403(_member_token: str) -> None:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/langfuse/status",
            headers={"Authorization": f"Bearer {_member_token}"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_langfuse_status_admin_sees_status(_admin_token: str) -> None:
    from httpx import ASGITransport, AsyncClient

    with patch(
        "app.core.langfuse_tracer.check_langfuse_health",
        AsyncMock(
            return_value={
                "enabled": False,
                "base_url_configured": False,
                "keys_configured": False,
                "client_initialized": False,
                "reachable": False,
                "last_error": None,
            }
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/admin/langfuse/status",
                headers={"Authorization": f"Bearer {_admin_token}"},
            )

    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body
    assert "reachable" in body
    # Secrets must never appear.
    response_text = response.text
    assert "sk-" not in response_text
    assert "pk-" not in response_text
    assert "secret" not in response_text.lower()


# ---------------------------------------------------------------------------
# S. shutdown_langfuse
# ---------------------------------------------------------------------------


def test_shutdown_langfuse_flushes_client() -> None:
    _reset_tracer()
    mock_client = MagicMock()
    tracer_module._langfuse_client = mock_client
    shutdown_langfuse()
    mock_client.flush.assert_called_once()


def test_shutdown_langfuse_no_client_is_safe() -> None:
    _reset_tracer()
    # Must not raise when no client is initialised.
    shutdown_langfuse()


def test_shutdown_langfuse_flush_error_is_silent() -> None:
    _reset_tracer()
    mock_client = MagicMock()
    mock_client.flush.side_effect = RuntimeError("network down")
    tracer_module._langfuse_client = mock_client
    shutdown_langfuse()  # must not propagate


# ---------------------------------------------------------------------------
# T. LangfuseRedactionMode enum
# ---------------------------------------------------------------------------


def test_redaction_mode_enum_values() -> None:
    assert LangfuseRedactionMode.none.value == "none"
    assert LangfuseRedactionMode.inputs.value == "inputs"
    assert LangfuseRedactionMode.all.value == "all"


# ---------------------------------------------------------------------------
# U. Config sanitized_snapshot includes Langfuse fields without secrets
# ---------------------------------------------------------------------------


def test_config_snapshot_includes_langfuse_no_secrets() -> None:
    snapshot = settings.sanitized_snapshot()
    assert "langfuse_enabled" in snapshot
    assert "langfuse_base_url_set" in snapshot
    assert "langfuse_public_key_set" in snapshot
    assert "langfuse_secret_key_set" in snapshot
    assert "langfuse_sample_rate" in snapshot
    assert "langfuse_redaction_mode" in snapshot
    # Secret values must not appear.
    snapshot_str = str(snapshot)
    assert "pk-" not in snapshot_str
    assert "sk-" not in snapshot_str
