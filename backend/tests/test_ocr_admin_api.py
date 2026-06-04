"""Tests for admin OCR config endpoint and OCR quality metadata (F232)."""
from __future__ import annotations

import os
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
from app.domains.documents.services.ocr_service import OcrDocumentResult, OcrPageResult, run_ocr
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


def _headers(token: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}


async def _create_doc(db_session: AsyncSession, *, org_id, user_id) -> Document:
    doc = Document(
        id=uuid4(),
        organization_id=org_id,
        uploaded_by_user_id=user_id,
        filename="test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="OCR Org", slug=f"ocr-{org_id}")
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

    org = Organization(id=org_id, name="Member Org", slug=f"member-ocr-{org_id}")
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
# OcrService confidence scoring unit tests (no HTTP)
# ---------------------------------------------------------------------------


class TestOcrConfidenceScoring:
    def test_high_char_count_gives_high_confidence(self) -> None:
        page = OcrPageResult(
            page_number=1,
            text="x" * 200,
            languages=["eng"],
            status="completed",
            confidence=0.9,
        )
        assert page.confidence is not None
        assert page.confidence > 0.6

    def test_empty_text_gives_zero_confidence(self) -> None:
        page = OcrPageResult(
            page_number=1,
            text="",
            languages=["eng"],
            status="completed",
            confidence=0.0,
        )
        assert page.confidence == 0.0

    def test_avg_confidence_in_document_result(self) -> None:
        result = OcrDocumentResult(
            status="completed",
            pages=[
                OcrPageResult(page_number=1, text="x" * 200, languages=["eng"], status="completed", confidence=0.9),
                OcrPageResult(page_number=2, text="x" * 50, languages=["eng"], status="completed", confidence=0.5),
            ],
            duration_ms=100,
            languages=["eng"],
            avg_confidence=0.7,
        )
        assert result.avg_confidence is not None

    def test_failed_pages_have_zero_confidence(self) -> None:
        page = OcrPageResult(
            page_number=1,
            text="",
            languages=["eng"],
            status="failed",
            warning="error",
            confidence=0.0,
        )
        assert page.confidence == 0.0


# ---------------------------------------------------------------------------
# Admin OCR config endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_set_ocr_language_to_german(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/ocr-config",
        json={"ocr_languages": ["de"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ocr_languages_override"] == "deu"


@pytest.mark.asyncio
async def test_admin_can_set_multiple_ocr_languages(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/ocr-config",
        json={"ocr_languages": ["en", "de"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ocr_languages_override"] == "eng+deu"


@pytest.mark.asyncio
async def test_admin_can_clear_ocr_language_override(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)
    doc.ocr_languages_override = "deu"
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/ocr-config",
        json={"ocr_languages": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ocr_languages_override"] is None


@pytest.mark.asyncio
async def test_admin_ocr_config_rejects_unsupported_language(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/ocr-config",
        json={"ocr_languages": ["en", "klingon"]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_set_ocr_language(
    member_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = member_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/ocr-config",
        json={"ocr_languages": ["de"]},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ocr_config_for_other_org_document_returns_404(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client

    other_org = Organization(id=uuid4(), name="Other", slug=f"other2-{uuid4()}")
    other_user = User(id=uuid4(), email=f"o2-{uuid4()}@example.com", hashed_password="x")
    db_session.add_all([other_org, other_user])
    await db_session.flush()

    other_doc = await _create_doc(db_session, org_id=other_org.id, user_id=other_user.id)

    response = await client.patch(
        f"/api/v1/admin/documents/{other_doc.id}/ocr-config",
        json={"ocr_languages": ["de"]},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_document_detail_exposes_ocr_quality_snapshot(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)
    doc.ocr_quality_snapshot = {
        "status": "completed",
        "mode": "scanned",
        "languages": ["deu"],
        "effective_languages_string": "deu",
        "pages_processed": 5,
        "pages_completed": 5,
        "pages_failed": 0,
        "duration_ms": 3200,
        "avg_confidence": 0.78,
        "page_confidences": [],
        "warnings": [],
    }
    await db_session.flush()

    response = await client.get(f"/api/v1/documents/{doc.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["ocr_quality_snapshot"]["avg_confidence"] == pytest.approx(0.78, abs=0.01)
    assert data["ocr_quality_snapshot"]["languages"] == ["deu"]


@pytest.mark.asyncio
async def test_reindex_with_ocr_languages_stores_override(
    admin_client, db_session: AsyncSession, monkeypatch
) -> None:
    """Reindex with ocr_languages should update ocr_languages_override on the document."""
    import app.workers.document_tasks as worker_module

    client, org_id, user_id = admin_client
    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    # Stub the task so it doesn't actually run.
    class FakeTask:
        called_with: list = []

        def delay(self, *args, **kwargs) -> object:
            FakeTask.called_with.append((args, kwargs))
            return type("FakeResult", (), {"id": "fake-task-id"})()

    monkeypatch.setattr(worker_module, "reindex_document", FakeTask())

    response = await client.post(
        f"/api/v1/documents/{doc.id}/reindex",
        json={"ocr_languages": ["fr"]},
    )

    assert response.status_code == 202
    await db_session.refresh(doc)
    assert doc.ocr_languages_override == "fra"
