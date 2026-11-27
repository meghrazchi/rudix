"""Recording helpers in app/core/metrics.py write their series when metrics are enabled.

The suite must not depend on the developer's ``.env``: CI does not set ``METRICS_ENABLED``,
so each test enables metrics itself and asserts the exact delta on the series it touched.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import metrics
from app.core.config import settings


@pytest.fixture(autouse=True)
def _metrics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)


def _value(metric: Any, **labels: str) -> float:
    return float(metric.labels(**labels)._value.get())


def _count(metric: Any, **labels: str) -> float:
    sample = metrics.registry.get_sample_value(f"{metric._name}_count", labels)
    return float(sample or 0.0)


def test_auth_and_authz_counters() -> None:
    auth = {"provider": "app", "outcome": "rejected"}
    authz = {
        "resource_type": "document",
        "action": "read",
        "decision": "deny",
        "deny_reason": "tenant_boundary",
    }
    before = (
        _value(metrics.AUTH_VERIFICATIONS_TOTAL, **auth),
        _value(metrics.AUTHZ_DECISIONS_TOTAL, **authz),
    )

    metrics.record_auth_verification(**auth)
    metrics.record_authz_decision(**authz)

    assert _value(metrics.AUTH_VERIFICATIONS_TOTAL, **auth) == before[0] + 1
    assert _value(metrics.AUTHZ_DECISIONS_TOTAL, **authz) == before[1] + 1


def test_rag_query_records_citation_failure_and_stage_duration() -> None:
    reason = {"reason": "unknown_chunk"}
    stage = {"stage": "rerank", "provider": "metrics-test"}
    failures = _value(metrics.RAG_CITATION_VALIDATION_FAILURES_TOTAL, **reason)
    stages = _count(metrics.RAG_STAGE_DURATION_SECONDS, **stage)

    metrics.record_rag_query(
        scope_mode="documents",
        status="success",
        duration_seconds=0.2,
        citation_validation_failed=True,
        citation_failure_reason="unknown_chunk",
    )
    metrics.record_rag_stage(duration_seconds=0.01, **stage)

    assert _value(metrics.RAG_CITATION_VALIDATION_FAILURES_TOTAL, **reason) == failures + 1
    assert _count(metrics.RAG_STAGE_DURATION_SECONDS, **stage) == stages + 1


def test_llm_request_tokens_cost_and_retry() -> None:
    model = {"provider": "metrics-test", "model": "m"}
    tokens_in = _value(metrics.LLM_TOKENS_TOTAL, direction="input", **model)
    tokens_out = _value(metrics.LLM_TOKENS_TOTAL, direction="output", **model)
    cost = _value(metrics.LLM_ESTIMATED_COST_USD_TOTAL, **model)
    retries = _value(metrics.LLM_RETRIES_TOTAL, reason="timeout", **model)

    metrics.record_llm_request(
        operation="chat",
        status="success",
        input_tokens=11,
        output_tokens=5,
        estimated_cost_usd=0.25,
        **model,
    )
    metrics.record_llm_retry(reason="timeout", **model)

    assert _value(metrics.LLM_TOKENS_TOTAL, direction="input", **model) == tokens_in + 11
    assert _value(metrics.LLM_TOKENS_TOTAL, direction="output", **model) == tokens_out + 5
    assert _value(metrics.LLM_ESTIMATED_COST_USD_TOTAL, **model) == pytest.approx(cost + 0.25)
    assert _value(metrics.LLM_RETRIES_TOTAL, reason="timeout", **model) == retries + 1


def test_chat_counters_skip_non_positive_amounts() -> None:
    tokens = {"stage": "metrics-test", "kind": "prompt"}
    flagged = {"action": "metrics-test"}
    before_tokens = _value(metrics.CHAT_TOKENS_TOTAL, **tokens)
    before_flagged = _value(metrics.CHAT_CONTEXT_INJECTION_FLAGGED_TOTAL, **flagged)

    metrics.record_chat_tokens(amount=0, **tokens)
    metrics.record_chat_tokens(amount=7, **tokens)
    metrics.record_chat_context_injection_flagged(count=0, **flagged)
    metrics.record_chat_context_injection_flagged(count=2, **flagged)

    assert _value(metrics.CHAT_TOKENS_TOTAL, **tokens) == before_tokens + 7
    assert _value(metrics.CHAT_CONTEXT_INJECTION_FLAGGED_TOTAL, **flagged) == before_flagged + 2


def test_document_upload_indexing_and_reaper() -> None:
    upload = {"file_type": "txt", "status": "accepted", "malware_scan_result": "metrics-test"}
    job = {"task_type": "metrics-test", "file_type": "txt", "status": "success"}
    duration = {"stage": "metrics-test", "file_type": "txt"}
    chunks = {"strategy": "metrics-test", "file_type": "txt"}
    before = (
        _value(metrics.DOCUMENT_UPLOADS_TOTAL, **upload),
        _value(metrics.DOCUMENT_INDEXING_JOBS_TOTAL, **job),
        _count(metrics.DOCUMENT_INDEXING_DURATION_SECONDS, **duration),
        _count(metrics.DOCUMENT_CHUNKS_GENERATED, **chunks),
        _value(metrics.DOCUMENTS_REAPED_TOTAL, outcome="metrics-test"),
    )

    metrics.record_document_upload(**upload)
    metrics.record_document_indexing_job(
        duration_seconds=1.5, stage="metrics-test", chunk_count=4, strategy="metrics-test", **job
    )
    metrics.record_document_reaped("metrics-test")

    assert _value(metrics.DOCUMENT_UPLOADS_TOTAL, **upload) == before[0] + 1
    assert _value(metrics.DOCUMENT_INDEXING_JOBS_TOTAL, **job) == before[1] + 1
    assert _count(metrics.DOCUMENT_INDEXING_DURATION_SECONDS, **duration) == before[2] + 1
    assert _count(metrics.DOCUMENT_CHUNKS_GENERATED, **chunks) == before[3] + 1
    assert _value(metrics.DOCUMENTS_REAPED_TOTAL, outcome="metrics-test") == before[4] + 1


def test_worker_agent_connector_and_bot_counters() -> None:
    task = {"task_name": "metrics.test", "queue": "default"}
    tool = {"tool_name": "metrics-test", "surface": "api", "effect": "read_only"}
    before = (
        _value(metrics.CELERY_TASKS_TOTAL, status="succeeded", **task),
        _count(metrics.CELERY_TASK_DURATION_SECONDS, **task),
        _value(metrics.AGENT_RUNS_TOTAL, status="metrics-test"),
        _value(metrics.AGENT_TOOL_CALLS_TOTAL, status="success", **tool),
        _value(metrics.CONNECTOR_SYNC_RUNS_TOTAL, provider_key="metrics-test", status="ok"),
        _value(metrics.BOT_ASKS_TOTAL, provider="metrics-test", outcome="answered"),
    )

    metrics.record_celery_task(status="succeeded", duration_seconds=0.5, **task)
    metrics.record_agent_run("metrics-test")
    metrics.record_agent_tool_call(status="success", **tool)
    metrics.record_connector_sync(provider_key="metrics-test", status="ok")
    metrics.record_bot_ask(provider="metrics-test", outcome="answered")

    assert _value(metrics.CELERY_TASKS_TOTAL, status="succeeded", **task) == before[0] + 1
    assert _count(metrics.CELERY_TASK_DURATION_SECONDS, **task) == before[1] + 1
    assert _value(metrics.AGENT_RUNS_TOTAL, status="metrics-test") == before[2] + 1
    assert _value(metrics.AGENT_TOOL_CALLS_TOTAL, status="success", **tool) == before[3] + 1
    assert (
        _value(metrics.CONNECTOR_SYNC_RUNS_TOTAL, provider_key="metrics-test", status="ok")
        == before[4] + 1
    )
    assert (
        _value(metrics.BOT_ASKS_TOTAL, provider="metrics-test", outcome="answered") == before[5] + 1
    )


def test_failure_quota_ws_auth_counters_and_readiness_gauge() -> None:
    before = (
        _value(metrics.RETRIEVAL_BRANCH_FAILURES_TOTAL, branch="metrics-test", error="E"),
        _value(metrics.EVAL_INDEX_CLEANUP_FAILURES_TOTAL, store="metrics-test"),
        _value(metrics.CHAT_QUOTA_DENIED_TOTAL, transport="metrics-test"),
        _value(metrics.CHAT_WS_AUTH_TOTAL, method="metrics-test", outcome="ok"),
    )

    metrics.record_retrieval_branch_failure(branch="metrics-test", error="E")
    metrics.record_eval_index_cleanup_failure("metrics-test")
    metrics.record_chat_quota_denied("metrics-test")
    metrics.record_chat_ws_auth(method="metrics-test", outcome="ok")
    metrics.set_dependency_readiness(dependency="metrics-test", is_ready=False)

    assert (
        _value(metrics.RETRIEVAL_BRANCH_FAILURES_TOTAL, branch="metrics-test", error="E")
        == before[0] + 1
    )
    assert _value(metrics.EVAL_INDEX_CLEANUP_FAILURES_TOTAL, store="metrics-test") == before[1] + 1
    assert _value(metrics.CHAT_QUOTA_DENIED_TOTAL, transport="metrics-test") == before[2] + 1
    assert _value(metrics.CHAT_WS_AUTH_TOTAL, method="metrics-test", outcome="ok") == before[3] + 1
    assert _value(metrics.DEPENDENCY_READINESS, dependency="metrics-test") == 0.0
    metrics.set_dependency_readiness(dependency="metrics-test", is_ready=True)
    assert _value(metrics.DEPENDENCY_READINESS, dependency="metrics-test") == 1.0
