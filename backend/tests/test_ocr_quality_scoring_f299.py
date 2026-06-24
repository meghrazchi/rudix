"""Tests for OCR quality scoring, retrieval downranking, and admin retry (F299)."""

from __future__ import annotations

import os
from typing import ClassVar
from uuid import uuid4

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
from app.domains.documents.services.ocr_quality_service import OcrQualityService
from app.main import app
from app.models.document import Document, DocumentPage
from app.models.enums import DocumentStatus, OcrQualityStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

document_repository = DocumentRepository()
_ocr_quality_service = OcrQualityService()


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


def _headers(token: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}


async def _create_doc(
    db_session: AsyncSession,
    *,
    org_id,
    user_id,
    ocr_quality_status: str | None = None,
    ocr_avg_confidence: float | None = None,
) -> Document:
    doc = Document(
        id=uuid4(),
        organization_id=org_id,
        uploaded_by_user_id=user_id,
        filename="test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
        ocr_quality_status=ocr_quality_status,
        ocr_avg_confidence=ocr_avg_confidence,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="OCR Quality Org", slug=f"ocrq-{org_id}")
    user = User(id=user_id, email=f"admin-{user_id}@example.com", hashed_password="x")
    member = OrganizationMember(
        organization_id=org_id, user_id=user_id, role=OrganizationRole.admin.value
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.admin.value)
    app.dependency_overrides[get_db_session] = lambda: db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=_headers(token, str(org_id)),
    ) as client:
        yield client, org_id, user_id

    app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture
async def member_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="Member OCR Org", slug=f"mocrq-{org_id}")
    user = User(id=user_id, email=f"member-{user_id}@example.com", hashed_password="x")
    member = OrganizationMember(
        organization_id=org_id, user_id=user_id, role=OrganizationRole.member.value
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.member.value)
    app.dependency_overrides[get_db_session] = lambda: db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=_headers(token, str(org_id)),
    ) as client:
        yield client, org_id, user_id

    app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# OcrQualityService unit tests
# ---------------------------------------------------------------------------


class TestOcrQualityServiceClassify:
    def test_high_confidence_classified_as_high(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.85,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.high

    def test_medium_confidence_classified_as_medium(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.55,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.medium

    def test_low_confidence_classified_as_low(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.20,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.low

    def test_failed_ocr_status_classified_as_failed(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=None,
            ocr_status="failed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.failed

    def test_txt_file_classified_as_not_required(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=None,
            ocr_status=None,
            ocr_applied=False,
            file_type="txt",
        )
        assert result == OcrQualityStatus.not_required

    def test_docx_file_classified_as_not_required(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=None,
            ocr_status=None,
            ocr_applied=False,
            file_type="docx",
        )
        assert result == OcrQualityStatus.not_required

    def test_ocr_not_applied_classified_as_not_required(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=None,
            ocr_status="skipped",
            ocr_applied=False,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.not_required

    def test_boundary_at_high_threshold_gives_high(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.70,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.high

    def test_boundary_just_below_high_gives_medium(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.699,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.medium

    def test_boundary_at_medium_threshold_gives_medium(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.40,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.medium

    def test_boundary_just_below_medium_gives_low(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.399,
            ocr_status="completed",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.low

    def test_zero_confidence_gives_low(self) -> None:
        result = _ocr_quality_service.classify(
            avg_confidence=0.0,
            ocr_status="partial",
            ocr_applied=True,
            file_type="pdf",
        )
        assert result == OcrQualityStatus.low


class TestOcrQualityServiceMultipliers:
    def test_high_quality_neutral_multiplier(self) -> None:
        assert _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.high) == 1.0

    def test_not_required_neutral_multiplier(self) -> None:
        assert _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.not_required) == 1.0

    def test_medium_quality_applies_penalty(self) -> None:
        m = _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.medium)
        assert 0.85 <= m < 1.0

    def test_low_quality_applies_stronger_penalty(self) -> None:
        m_medium = _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.medium)
        m_low = _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.low)
        assert m_low < m_medium

    def test_failed_quality_applies_strongest_penalty(self) -> None:
        m_low = _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.low)
        m_failed = _ocr_quality_service.retrieval_score_multiplier(OcrQualityStatus.failed)
        assert m_failed < m_low

    def test_apply_quality_score_reduces_low_quality_score(self) -> None:
        quality_map = {"doc1": OcrQualityStatus.low}
        adjusted = _ocr_quality_service.apply_quality_score(
            score=1.0, document_id="doc1", quality_map=quality_map
        )
        assert adjusted < 1.0

    def test_apply_quality_score_keeps_high_quality_score(self) -> None:
        quality_map = {"doc1": OcrQualityStatus.high}
        adjusted = _ocr_quality_service.apply_quality_score(
            score=1.0, document_id="doc1", quality_map=quality_map
        )
        assert adjusted == 1.0

    def test_apply_quality_score_missing_doc_is_neutral(self) -> None:
        adjusted = _ocr_quality_service.apply_quality_score(
            score=0.8, document_id="missing", quality_map={}
        )
        assert adjusted == 0.8


class TestOcrQualityServiceWarnings:
    def test_low_status_triggers_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(OcrQualityStatus.low) is True

    def test_failed_status_triggers_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(OcrQualityStatus.failed) is True

    def test_high_status_no_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(OcrQualityStatus.high) is False

    def test_medium_status_no_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(OcrQualityStatus.medium) is False

    def test_not_required_no_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(OcrQualityStatus.not_required) is False

    def test_none_status_no_warning(self) -> None:
        assert _ocr_quality_service.is_low_confidence(None) is False


class TestOcrQualityServiceQualityMap:
    def test_build_quality_map_from_documents(self) -> None:
        class FakeDoc:
            def __init__(self, doc_id, status):
                self.id = doc_id
                self.ocr_quality_status = status

        d1 = FakeDoc(uuid4(), OcrQualityStatus.high)
        d2 = FakeDoc(uuid4(), OcrQualityStatus.low)
        d3 = FakeDoc(uuid4(), None)

        quality_map = _ocr_quality_service.build_quality_map([d1, d2, d3])
        assert quality_map[str(d1.id)] == OcrQualityStatus.high
        assert quality_map[str(d2.id)] == OcrQualityStatus.low
        assert quality_map[str(d3.id)] == OcrQualityStatus.not_required

    def test_build_quality_map_empty_input(self) -> None:
        assert _ocr_quality_service.build_quality_map([]) == {}


# ---------------------------------------------------------------------------
# DocumentRepository OCR quality persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_document_ocr_quality_stores_status_and_confidence(
    db_session: AsyncSession,
) -> None:
    org_id = uuid4()
    user_id = uuid4()
    org = Organization(id=org_id, name="Repo Org", slug=f"repoorg-{org_id}")
    user = User(id=user_id, email=f"repo-{user_id}@example.com", hashed_password="x")
    db_session.add_all([org, user])
    await db_session.flush()

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    updated = await document_repository.update_document_ocr_quality(
        db_session,
        document_id=doc.id,
        ocr_quality_snapshot={"status": "completed", "avg_confidence": 0.82},
        ocr_quality_status=OcrQualityStatus.high,
        ocr_avg_confidence=0.82,
    )

    assert updated is not None
    assert updated.ocr_quality_status == OcrQualityStatus.high
    assert updated.ocr_avg_confidence == pytest.approx(0.82, abs=0.01)


@pytest.mark.asyncio
async def test_update_document_pages_ocr_confidence_bulk(db_session: AsyncSession) -> None:
    org_id = uuid4()
    user_id = uuid4()
    org = Organization(id=org_id, name="Page Org", slug=f"pageorg-{org_id}")
    user = User(id=user_id, email=f"page-{user_id}@example.com", hashed_password="x")
    db_session.add_all([org, user])
    await db_session.flush()

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    page1 = DocumentPage(
        id=uuid4(), document_id=doc.id, page_number=1, text="Sample text", char_count=11
    )
    page2 = DocumentPage(
        id=uuid4(), document_id=doc.id, page_number=2, text="Other text", char_count=10
    )
    db_session.add_all([page1, page2])
    await db_session.flush()

    updated_count = await document_repository.update_document_pages_ocr_confidence_bulk(
        db_session,
        document_id=doc.id,
        page_confidences={1: 0.90, 2: 0.35},
    )
    assert updated_count == 2

    await db_session.refresh(page1)
    await db_session.refresh(page2)
    assert page1.ocr_confidence == pytest.approx(0.90, abs=0.01)
    assert page2.ocr_confidence == pytest.approx(0.35, abs=0.01)


@pytest.mark.asyncio
async def test_get_page_ocr_confidence_map(db_session: AsyncSession) -> None:
    org_id = uuid4()
    user_id = uuid4()
    org = Organization(id=org_id, name="Map Org", slug=f"maporg-{org_id}")
    user = User(id=user_id, email=f"map-{user_id}@example.com", hashed_password="x")
    db_session.add_all([org, user])
    await db_session.flush()

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)
    page = DocumentPage(
        id=uuid4(),
        document_id=doc.id,
        page_number=3,
        text="Text",
        char_count=4,
        ocr_confidence=0.75,
    )
    db_session.add(page)
    await db_session.flush()

    confidence_map = await document_repository.get_page_ocr_confidence_map(
        db_session, document_id=doc.id
    )
    assert confidence_map == {3: pytest.approx(0.75, abs=0.01)}


# ---------------------------------------------------------------------------
# Admin OCR retry endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_retry_ocr_for_low_quality_document(
    admin_client, db_session: AsyncSession, monkeypatch
) -> None:
    import app.interfaces.http.admin_documents as admin_doc_http

    client, org_id, user_id = admin_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.low,
        ocr_avg_confidence=0.25,
    )

    class FakeTask:
        called: ClassVar[list] = []

        def delay(self, *args, **kwargs):
            FakeTask.called.append(kwargs)
            return type("FakeResult", (), {"id": "fake-task-id"})()

    monkeypatch.setattr(admin_doc_http, "reindex_document_task", FakeTask())

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")

    assert response.status_code == 202
    data = response.json()
    assert data["document_id"] == str(doc.id)
    assert data["ocr_quality_status"] == OcrQualityStatus.low
    assert data["queue_status"] == "queued"


@pytest.mark.asyncio
async def test_admin_can_retry_ocr_for_failed_document(
    admin_client, db_session: AsyncSession, monkeypatch
) -> None:
    import app.interfaces.http.admin_documents as admin_doc_http

    client, org_id, user_id = admin_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.failed,
    )

    class FakeTask:
        def delay(self, *args, **kwargs):
            return type("FakeResult", (), {"id": "fake-task-id"})()

    monkeypatch.setattr(admin_doc_http, "reindex_document_task", FakeTask())

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_ocr_retry_rejected_for_high_quality_document(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.high,
        ocr_avg_confidence=0.95,
    )

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ocr_retry_rejected_for_not_required_document(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.not_required,
    )

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ocr_retry_rejected_for_null_quality_status(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_retry_ocr(member_client, db_session: AsyncSession) -> None:
    client, org_id, user_id = member_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.low,
    )

    response = await client.post(f"/api/v1/admin/documents/{doc.id}/ocr-retry")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ocr_retry_for_other_org_document_returns_404(
    admin_client, db_session: AsyncSession
) -> None:
    client, _org_id, _user_id = admin_client

    other_org = Organization(id=uuid4(), name="Other Org", slug=f"other-{uuid4()}")
    other_user = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="x")
    db_session.add_all([other_org, other_user])
    await db_session.flush()

    other_doc = await _create_doc(
        db_session,
        org_id=other_org.id,
        user_id=other_user.id,
        ocr_quality_status=OcrQualityStatus.low,
    )

    response = await client.post(f"/api/v1/admin/documents/{other_doc.id}/ocr-retry")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Document detail response includes OCR quality fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_detail_exposes_ocr_quality_status(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        ocr_quality_status=OcrQualityStatus.medium,
        ocr_avg_confidence=0.58,
    )

    response = await client.get(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["ocr_quality_status"] == OcrQualityStatus.medium
    assert data["ocr_avg_confidence"] == pytest.approx(0.58, abs=0.01)


@pytest.mark.asyncio
async def test_document_detail_ocr_quality_fields_are_null_for_unprocessed_document(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.get(f"/api/v1/documents/{doc.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["ocr_quality_status"] is None
    assert data["ocr_avg_confidence"] is None
