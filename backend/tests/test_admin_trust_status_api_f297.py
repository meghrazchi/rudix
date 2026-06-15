"""Integration tests for PATCH /admin/documents/{id}/trust-status — F297."""

from __future__ import annotations

import os
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

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

from app.interfaces.http.admin_documents import (
    AdminTrustStatusRequest,
    AdminTrustStatusResponse,
)


# ---------------------------------------------------------------------------
# AdminTrustStatusRequest validation
# ---------------------------------------------------------------------------


def test_valid_trust_status_current() -> None:
    req = AdminTrustStatusRequest(trust_status="current")
    assert req.trust_status == "current"


def test_valid_trust_status_verified() -> None:
    req = AdminTrustStatusRequest(trust_status="verified")
    assert req.trust_status == "verified"


@pytest.mark.parametrize(
    "status",
    ["draft", "current", "verified", "stale", "deprecated", "superseded", "expired"],
)
def test_all_valid_trust_statuses(status: str) -> None:
    req = AdminTrustStatusRequest(trust_status=status)
    assert req.trust_status == status


def test_invalid_trust_status_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Invalid trust_status"):
        AdminTrustStatusRequest(trust_status="unknown_value")


def test_trust_status_normalised_to_lowercase() -> None:
    req = AdminTrustStatusRequest(trust_status="VERIFIED")
    assert req.trust_status == "verified"


def test_valid_with_all_optional_fields() -> None:
    req = AdminTrustStatusRequest(
        trust_status="current",
        version_label="v1.0",
        review_date=date(2026, 12, 31),
        effective_date=date(2026, 1, 1),
        stale_after_days=90,
        superseded_by_document_id=str(uuid4()),
    )
    assert req.version_label == "v1.0"
    assert req.stale_after_days == 90


def test_stale_after_days_too_small_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="stale_after_days"):
        AdminTrustStatusRequest(trust_status="current", stale_after_days=0)


def test_stale_after_days_too_large_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="stale_after_days"):
        AdminTrustStatusRequest(trust_status="current", stale_after_days=9999)


def test_minimal_request_no_optional_fields() -> None:
    req = AdminTrustStatusRequest(trust_status="deprecated")
    assert req.version_label is None
    assert req.review_date is None
    assert req.effective_date is None
    assert req.stale_after_days is None
    assert req.superseded_by_document_id is None


# ---------------------------------------------------------------------------
# AdminTrustStatusResponse construction
# ---------------------------------------------------------------------------


def _make_response(trust_status: str = "current") -> AdminTrustStatusResponse:
    from datetime import datetime

    return AdminTrustStatusResponse(
        document_id=str(uuid4()),
        trust_status=trust_status,
        version_label=None,
        review_date=None,
        effective_date=None,
        stale_after_days=None,
        superseded_by_document_id=None,
        trusted_at=None,
        updated_at=datetime(2026, 6, 15, 12, 0, 0),
    )


def test_response_serialises() -> None:
    resp = _make_response("verified")
    data = resp.model_dump()
    assert data["trust_status"] == "verified"
    assert "updated_at" in data


def test_response_includes_review_date() -> None:
    from datetime import datetime

    resp = AdminTrustStatusResponse(
        document_id=str(uuid4()),
        trust_status="stale",
        version_label="v1",
        review_date=date(2026, 3, 1),
        effective_date=None,
        stale_after_days=30,
        superseded_by_document_id=None,
        trusted_at=None,
        updated_at=datetime(2026, 6, 15, 12, 0, 0),
    )
    data = resp.model_dump()
    assert data["review_date"] == date(2026, 3, 1)
    assert data["stale_after_days"] == 30


# ---------------------------------------------------------------------------
# RagProfileConfig freshness knobs
# ---------------------------------------------------------------------------


def test_rag_profile_config_freshness_defaults() -> None:
    from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig

    cfg = RagProfileConfig()
    assert cfg.freshness_boost_enabled is True
    assert cfg.exclude_deprecated_docs is True
    assert cfg.stale_threshold_days is None


def test_rag_profile_config_freshness_override() -> None:
    from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig

    cfg = RagProfileConfig(
        freshness_boost_enabled=False,
        exclude_deprecated_docs=False,
        stale_threshold_days=180,
    )
    assert cfg.freshness_boost_enabled is False
    assert cfg.exclude_deprecated_docs is False
    assert cfg.stale_threshold_days == 180


def test_rag_profile_stale_threshold_days_bounds() -> None:
    from pydantic import ValidationError

    from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig

    with pytest.raises(ValidationError):
        RagProfileConfig(stale_threshold_days=0)

    with pytest.raises(ValidationError):
        RagProfileConfig(stale_threshold_days=9999)

    valid = RagProfileConfig(stale_threshold_days=365)
    assert valid.stale_threshold_days == 365


# ---------------------------------------------------------------------------
# Document model fields present
# ---------------------------------------------------------------------------


def test_document_model_has_trust_fields() -> None:
    from app.models.document import Document

    assert hasattr(Document, "trust_status")
    assert hasattr(Document, "version_label")
    assert hasattr(Document, "review_date")
    assert hasattr(Document, "effective_date")
    assert hasattr(Document, "trusted_at")
    assert hasattr(Document, "trusted_by_id")
    assert hasattr(Document, "stale_after_days")
    assert hasattr(Document, "superseded_by_document_id")


# ---------------------------------------------------------------------------
# DocumentDetailResponse includes trust fields
# ---------------------------------------------------------------------------


def test_document_detail_response_includes_trust_fields() -> None:
    from datetime import datetime

    from app.domains.documents.schemas.documents import DocumentDetailResponse
    from app.models.enums import DocumentStatus, DocumentTrustStatus

    resp = DocumentDetailResponse(
        document_id=str(uuid4()),
        filename="report.pdf",
        file_type="pdf",
        status=DocumentStatus.indexed,
        chunk_count=5,
        trust_status=DocumentTrustStatus.verified,
        version_label="v3",
        review_date=date(2027, 1, 1),
        effective_date=date(2026, 1, 1),
        stale_after_days=180,
        created_at=datetime(2026, 6, 15, 0, 0, 0),
        updated_at=datetime(2026, 6, 15, 0, 0, 0),
    )
    data = resp.model_dump()
    assert data["trust_status"] == "verified"
    assert data["version_label"] == "v3"
    assert data["review_date"] == date(2027, 1, 1)


# ---------------------------------------------------------------------------
# ChatCitationResponse freshness fields
# ---------------------------------------------------------------------------


def test_citation_response_freshness_fields_default() -> None:
    from app.domains.chat.schemas.chat import ChatCitationResponse

    citation = ChatCitationResponse(
        document_id=str(uuid4()),
        chunk_id=str(uuid4()),
    )
    assert citation.doc_trust_status is None
    assert citation.doc_version_label is None
    assert citation.doc_review_date is None
    assert citation.doc_effective_date is None
    assert citation.doc_stale_warning is False
    assert citation.doc_is_excluded_status is False


def test_citation_response_freshness_fields_set() -> None:
    from app.domains.chat.schemas.chat import ChatCitationResponse

    citation = ChatCitationResponse(
        document_id=str(uuid4()),
        chunk_id=str(uuid4()),
        doc_trust_status="stale",
        doc_version_label="v1",
        doc_review_date=date(2026, 1, 1),
        doc_stale_warning=True,
    )
    assert citation.doc_trust_status == "stale"
    assert citation.doc_stale_warning is True


# ---------------------------------------------------------------------------
# ChatDebugResponse freshness fields
# ---------------------------------------------------------------------------


def test_debug_response_freshness_fields_default() -> None:
    from app.domains.chat.schemas.chat import ChatDebugResponse

    debug = ChatDebugResponse(
        latencies_ms={},
        retrieval_count=0,
        selected_count=0,
        rerank_applied=False,
    )
    assert debug.freshness_filter_enabled is False
    assert debug.freshness_excluded_count == 0
    assert debug.freshness_boosted_count == 0
    assert debug.freshness_stale_count == 0


def test_debug_response_freshness_fields_populated() -> None:
    from app.domains.chat.schemas.chat import ChatDebugResponse

    debug = ChatDebugResponse(
        latencies_ms={"retrieve": 50},
        retrieval_count=10,
        selected_count=5,
        rerank_applied=False,
        freshness_filter_enabled=True,
        freshness_excluded_count=2,
        freshness_boosted_count=3,
        freshness_stale_count=1,
    )
    assert debug.freshness_filter_enabled is True
    assert debug.freshness_excluded_count == 2
    assert debug.freshness_boosted_count == 3
    assert debug.freshness_stale_count == 1
