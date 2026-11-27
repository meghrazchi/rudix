import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

# Ensure strict settings can be loaded in test environment.
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
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

from app.core.config import settings
from app.core.metrics import (
    is_metrics_enabled,
    record_auth_verification,
    record_authz_decision,
    record_bot_ask,
    record_celery_task,
    record_connector_sync,
    record_document_indexing_job,
    record_document_upload,
    record_llm_request,
    record_llm_retry,
    record_rag_query,
    record_rag_stage,
    record_rate_limit,
    registry,
    set_dependency_readiness,
)
from app.main import app


def test_metrics_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 404
    assert response.json()["detail"] == "Metrics collection is disabled"


def test_metrics_enabled_returns_prometheus_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_require_auth", False)
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "rudix_http_requests_total" in response.text


def test_metrics_require_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_require_auth", True)
    monkeypatch.setattr(settings, "metrics_bearer_token", SecretStr("secret-token-123"))
    client = TestClient(app)

    # Missing authorization header
    res_no_auth = client.get("/metrics")
    assert res_no_auth.status_code == 401

    # Wrong token
    res_wrong_auth = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
    assert res_wrong_auth.status_code == 403

    # Valid token
    res_valid = client.get("/metrics", headers={"Authorization": "Bearer secret-token-123"})
    assert res_valid.status_code == 200
    assert "rudix_http_requests_total" in res_valid.text


def test_http_request_metrics_normalizes_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    client = TestClient(app)

    # Call a known route
    res = client.get("/api/v1/health")
    assert res.status_code == 200

    # Call an unmatched route
    res_unmatched = client.get("/non-existent-path-for-test-999")
    assert res_unmatched.status_code == 404

    scrape = client.get("/metrics")
    assert scrape.status_code == 200
    # Must contain normalized route template without leaking raw dynamic parameters
    assert 'route="/health"' in scrape.text
    assert 'route="unmatched"' in scrape.text


def test_metrics_helpers_are_safe_noops_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    assert not is_metrics_enabled()

    # None of these should raise
    record_rate_limit(scope="upload", decision="allowed")
    record_auth_verification(provider="clerk", outcome="success")
    record_authz_decision(
        resource_type="document", action="read", decision="deny", deny_reason="tenant_boundary"
    )
    record_rag_query(
        scope_mode="all", status="success", duration_seconds=1.23, confidence_score=0.88
    )
    record_rag_stage(stage="retrieve", provider="qdrant", duration_seconds=0.045)
    record_llm_request(
        provider="openai",
        model="gpt-5.4-mini",
        operation="chat",
        status="success",
        input_tokens=100,
        output_tokens=50,
    )
    record_llm_retry(provider="openai", model="gpt-5.4-mini", reason="timeout")
    record_document_upload(file_type="pdf", status="accepted", malware_scan_result="clean")
    record_document_indexing_job(
        task_type="process",
        file_type="pdf",
        status="success",
        duration_seconds=5.2,
        stage="chunk",
        chunk_count=12,
        strategy="token_recursive",
    )
    record_celery_task(
        task_name="documents.process",
        queue="documents.processing",
        status="succeeded",
        duration_seconds=4.5,
    )
    record_connector_sync(provider_key="confluence", status="success")
    record_bot_ask(provider="slack", outcome="answered")
    set_dependency_readiness(dependency="postgres", is_ready=True)


def test_metrics_helpers_record_values_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    assert is_metrics_enabled()

    record_rate_limit(scope="chat", decision="rejected", failure_mode="none")
    record_rag_query(
        scope_mode="collection",
        status="success",
        duration_seconds=0.75,
        confidence_score=0.92,
        confidence_category="high",
        not_found=False,
        fallback_used=False,
    )

    client = TestClient(app)
    scrape = client.get("/metrics")
    assert scrape.status_code == 200
    assert (
        'rudix_rate_limit_decisions_total{decision="rejected",failure_mode="none",scope="chat"}'
        in scrape.text
    )
    assert (
        'rudix_rag_answers_total{confidence_category="high",fallback_used="false",not_found="false",scope_mode="collection"}'
        in scrape.text
    )


def test_no_sensitive_or_high_cardinality_labels_in_metrics() -> None:
    forbidden_labels = {
        "user_id",
        "document_id",
        "chunk_id",
        "session_id",
        "message_id",
        "request_id",
        "prompt",
        "question",
        "answer",
        "token",
        "password",
        "organization_id",
    }

    for metric_family in registry.collect():
        for sample in metric_family.samples:
            for label_name in sample.labels:
                assert label_name not in forbidden_labels, (
                    f"Metric {sample.name} contains forbidden high-cardinality/sensitive label: {label_name}"
                )
                assert not label_name.endswith("_id") or label_name in {
                    "resource_id"  # only if bounded, but verify
                }, f"Metric {sample.name} contains potential ID label: {label_name}"
