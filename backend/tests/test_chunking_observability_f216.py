"""Unit tests for F216: Chunking observability, rollout controls, and documentation.

Covers:
  - log_chunking_event helper emits the correct fields
  - feature_enable_adaptive_chunking flag is present in sanitized_snapshot
  - Chunk metrics (avg_tokens, max_tokens, min_tokens) computed correctly
  - Empty page counting logic
  - Pipeline graph service "chunk" node description updated
  - reason_codes propagated in chunking logs
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

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

from app.core.config import get_settings
from app.core.logging import log_chunking_event
from app.domains.pipeline.services.pipeline_graph_service import (
    pipeline_node_description,
)

# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


def test_feature_enable_adaptive_chunking_exists_and_defaults_false() -> None:
    s = get_settings()
    assert hasattr(s, "feature_enable_adaptive_chunking")
    assert s.feature_enable_adaptive_chunking is False


def test_sanitized_snapshot_includes_adaptive_chunking_and_chunking_profiles() -> None:
    s = get_settings()
    snapshot = s.sanitized_snapshot()
    features = snapshot["features"]
    assert "adaptive_chunking" in features
    assert features["adaptive_chunking"] is False
    assert "chunking_profiles" in features
    assert isinstance(features["chunking_profiles"], bool)


# ---------------------------------------------------------------------------
# log_chunking_event helper tests
# ---------------------------------------------------------------------------


def test_log_chunking_event_started_calls_logger() -> None:
    captured: list[dict[str, Any]] = []

    class _CapturingLogger:
        def info(self, event: str, **kwargs: Any) -> None:
            captured.append({"event": event, **kwargs})

    with patch("app.core.logging.get_logger", return_value=_CapturingLogger()):
        log_chunking_event(
            event="document.chunking.started",
            document_id="doc-1",
            organization_id="org-1",
            user_id="user-1",
            strategy="token_recursive",
            profile_source="system_default",
        )

    assert len(captured) == 1
    entry = captured[0]
    assert entry["event"] == "document.chunking.started"
    assert entry["strategy"] == "token_recursive"
    assert entry["profile_source"] == "system_default"
    assert entry["document_id"] == "doc-1"


def test_log_chunking_event_completed_emits_all_metric_fields() -> None:
    captured: list[dict[str, Any]] = []

    class _CapturingLogger:
        def info(self, event: str, **kwargs: Any) -> None:
            captured.append({"event": event, **kwargs})

    with patch("app.core.logging.get_logger", return_value=_CapturingLogger()):
        log_chunking_event(
            event="document.chunking.completed",
            document_id="doc-2",
            organization_id="org-1",
            user_id="user-1",
            strategy="page_aware",
            chunk_count=42,
            avg_tokens=312.5,
            max_tokens=695,
            min_tokens=88,
            duration_ms=234,
            profile_source="system_default",
            reason_codes=["pdf_ocr_applied"],
            empty_pages=0,
            language=None,
        )

    assert len(captured) == 1
    entry = captured[0]
    assert entry["chunk_count"] == 42
    assert entry["avg_tokens"] == 312.5
    assert entry["max_tokens"] == 695
    assert entry["min_tokens"] == 88
    assert entry["duration_ms"] == 234
    assert entry["reason_codes"] == ["pdf_ocr_applied"]


def test_log_chunking_event_failed_emits_error_fields() -> None:
    captured: list[dict[str, Any]] = []

    class _CapturingLogger:
        def info(self, event: str, **kwargs: Any) -> None:
            captured.append({"event": event, **kwargs})

    with patch("app.core.logging.get_logger", return_value=_CapturingLogger()):
        log_chunking_event(
            event="document.chunking.failed",
            document_id="doc-3",
            organization_id="org-1",
            error_code="EMPTY_CHUNK_SET",
            error_message="cleaned document produced no chunks",
        )

    assert len(captured) == 1
    entry = captured[0]
    assert entry["event"] == "document.chunking.failed"
    assert entry["error_code"] == "EMPTY_CHUNK_SET"


# ---------------------------------------------------------------------------
# Chunk metric computation helpers
# ---------------------------------------------------------------------------


def _chunk_metrics(token_counts: list[int]) -> dict[str, Any]:
    avg = round(sum(token_counts) / len(token_counts), 1)
    return {
        "avg_tokens": avg,
        "max_tokens": max(token_counts),
        "min_tokens": min(token_counts),
    }


def test_chunk_metric_avg_rounds_correctly() -> None:
    m = _chunk_metrics([100, 200, 300])
    assert m["avg_tokens"] == 200.0
    assert m["max_tokens"] == 300
    assert m["min_tokens"] == 100


def test_chunk_metric_single_chunk() -> None:
    m = _chunk_metrics([512])
    assert m["avg_tokens"] == 512.0
    assert m["max_tokens"] == 512
    assert m["min_tokens"] == 512


def test_chunk_metric_uneven_avg() -> None:
    m = _chunk_metrics([100, 101])
    assert m["avg_tokens"] == 100.5


# ---------------------------------------------------------------------------
# Empty page counting
# ---------------------------------------------------------------------------


def _count_empty_pages(texts: list[str]) -> int:
    return sum(1 for t in texts if not t.strip())


def test_empty_pages_all_populated() -> None:
    assert _count_empty_pages(["some text", "more text"]) == 0


def test_empty_pages_one_blank() -> None:
    assert _count_empty_pages(["some text", "", "   "]) == 2


def test_empty_pages_all_blank() -> None:
    assert _count_empty_pages(["", "  ", "\n"]) == 3


# ---------------------------------------------------------------------------
# Pipeline graph service chunk node
# ---------------------------------------------------------------------------


def test_chunk_node_description_mentions_metrics() -> None:
    desc = pipeline_node_description("chunk")
    assert "strategy" in desc.lower()
    assert "reason" in desc.lower() or "codes" in desc.lower()
    assert "token" in desc.lower()


def test_chunk_node_description_mentions_duration() -> None:
    desc = pipeline_node_description("chunk")
    assert "duration" in desc.lower()


# ---------------------------------------------------------------------------
# Reason codes preserved through adaptive selection path
# ---------------------------------------------------------------------------


def test_selection_result_reason_codes_are_list_of_strings() -> None:
    from app.domains.documents.chunking.selector import AdaptiveHybridSelector, DocumentSignals

    signals = DocumentSignals(
        file_type="pdf",
        page_count=3,
        total_token_count=1500,
        ocr_applied=True,
    )
    result = AdaptiveHybridSelector.select(signals)
    assert result.strategy == "page_aware"
    assert isinstance(result.reason_codes, list)
    assert all(isinstance(c, str) for c in result.reason_codes)
    assert "pdf_ocr_applied" in result.reason_codes


def test_force_override_reason_code() -> None:
    from app.domains.documents.chunking.selector import AdaptiveHybridSelector, DocumentSignals

    signals = DocumentSignals(
        file_type="txt",
        page_count=1,
        total_token_count=200,
    )
    result = AdaptiveHybridSelector.select(signals, force_strategy="heading_aware")
    assert result.strategy == "heading_aware"
    assert "force_override" in result.reason_codes
