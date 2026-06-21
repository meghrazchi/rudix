"""Integration tests for PATCH /admin/documents/{id}/trust-status — F297."""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.auth.token_codec import create_app_access_token
from app.db.session import get_db_session
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http.admin_documents import (
    AdminTrustStatusRequest,
    AdminTrustStatusResponse,
)
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

document_repository = DocumentRepository()


def _make_token(user_id: str, org_id: str, role: str) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        roles=[role],
        secret="test-secret",
        issuer="rudix-app",
        audience="rudix-api",
        ttl_seconds=3600,
    )


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="Admin Org", slug=f"admin-{org_id}")
    user = User(
        id=user_id,
        organization_id=org_id,
        email=f"admin-{user_id}@example.com",
        hashed_password="x",
    )
    member = OrganizationMember(
        organization_id=org_id,
        user_id=user_id,
        role=OrganizationRole.admin.value,
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.admin.value)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, org_id, user_id
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def member_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="Member Org", slug=f"member-{org_id}")
    user = User(
        id=user_id,
        organization_id=org_id,
        email=f"member-{user_id}@example.com",
        hashed_password="x",
    )
    member = OrganizationMember(
        organization_id=org_id,
        user_id=user_id,
        role=OrganizationRole.member.value,
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.member.value)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, org_id, user_id
    app.dependency_overrides.clear()


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    uploaded_by_user_id: UUID,
) -> Document:
    document = await document_repository.create_document(
        db_session,
        organization_id=organization_id,
        uploaded_by_user_id=uploaded_by_user_id,
        filename="admin-trust.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"admin-trust/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
    )
    await db_session.flush()
    return document


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
        review_status="current",
        review_owner_id=None,
        review_due_date=None,
        expiry_date=None,
        trust_level=None,
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
        review_status="stale",
        review_owner_id=None,
        review_due_date=None,
        expiry_date=None,
        trust_level=None,
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


@pytest.mark.asyncio
async def test_admin_can_update_review_status(
    admin_client: tuple[AsyncClient, UUID, UUID],
    db_session: AsyncSession,
) -> None:
    client, org_id, user_id = admin_client
    app.dependency_overrides[get_db_session] = lambda: db_session

    reviewer = User(
        organization_id=org_id,
        external_auth_id=f"reviewer-{uuid4().hex[:8]}",
        email=f"reviewer-{uuid4().hex[:8]}@example.com",
        display_name="Reviewer",
    )
    db_session.add(reviewer)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=reviewer.id,
            role=OrganizationRole.member.value,
        )
    )
    document = await _seed_document(
        db_session,
        organization_id=org_id,
        uploaded_by_user_id=user_id,
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/admin/documents/{document.id}/trust-status",
        json={
            "trust_status": "current",
            "review_status": "needs_review",
            "review_owner_id": str(reviewer.id),
            "review_due_date": "2026-07-01",
            "expiry_date": "2026-08-01",
            "trust_level": "gold",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["review_status"] == "needs_review"
    assert data["review_owner_id"] == str(reviewer.id)
    assert data["review_due_date"] == "2026-07-01"
    assert data["expiry_date"] == "2026-08-01"
    assert data["trust_level"] == "gold"


@pytest.mark.asyncio
async def test_member_cannot_update_review_status(
    member_client: tuple[AsyncClient, UUID, UUID],
    db_session: AsyncSession,
) -> None:
    client, org_id, user_id = member_client
    app.dependency_overrides[get_db_session] = lambda: db_session

    document = await _seed_document(
        db_session,
        organization_id=org_id,
        uploaded_by_user_id=user_id,
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/admin/documents/{document.id}/trust-status",
        json={"trust_status": "current", "review_status": "archived"},
    )

    assert response.status_code == 403


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
