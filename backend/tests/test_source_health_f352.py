"""Backend tests for F352: Source health dashboard.

Covers:
  A. _freshness / _needs_review helpers — pure unit tests (no DB)
  B. SourceHealthService.get_summary — indexed/failed/pending counts
  C. SourceHealthService.get_summary — OCR required / low-confidence counts
  D. SourceHealthService.get_summary — stale/deprecated/expired/needs_review/unreviewed
  E. SourceHealthService.get_summary — missing_metadata (F256 required-field anti-join)
  F. SourceHealthService.get_summary — table_extraction_warnings (F298 table chunks)
  G. SourceHealthService.get_summary — total_sources includes collections
  H. SourceHealthService.list_sources — file vs connector source_type split
  I. SourceHealthService.list_sources — status filter
  J. SourceHealthService.list_sources — freshness filter
  K. SourceHealthService.list_sources — ocr_quality filter
  L. SourceHealthService.list_sources — q (name search) filter
  M. SourceHealthService.list_sources — pagination
  N. SourceHealthService.get_error_detail — document error + table warnings
  O. SourceHealthService.get_error_detail — unknown source returns None
  P. HTTP — GET /admin/source-health/summary requires admin/owner role (member 403)
  Q. HTTP — GET /admin/source-health/summary org isolation
  R. HTTP — GET /admin/source-health/sources returns rows with available_actions
  S. HTTP — GET /admin/source-health/sources/{type}/{id}/error 404 for unknown id
  T. HTTP — GET /admin/source-health/export returns CSV with header row

Run:
    pytest tests/test_source_health_f352.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.admin.services.source_health_service import (
    SourceHealthFilters,
    SourceHealthService,
    _freshness,
    _needs_review,
)
from app.main import app
from app.models.collection import Collection
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentIngestionSource, DocumentStatus, OrganizationRole
from app.models.metadata import DocumentMetadata, MetadataField
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def source_health_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _make_org_user(db: AsyncSession, role: str = OrganizationRole.admin.value) -> dict:
    slug = f"sh-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Source Health Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(email=f"sh-{uuid4().hex[:6]}@test.com", display_name="SH User")
    db.add(user)
    await db.flush()

    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    await db.flush()

    tok = _token(str(user.id), str(org.id), role)
    return {"org_id": org.id, "user_id": user.id, "token": tok}


def _doc(
    org_id: UUID,
    *,
    filename: str = "report.pdf",
    status: str = DocumentStatus.indexed.value,
    ingestion_source: str | None = None,
    ocr_quality_status: str | None = None,
    trust_status: str = "current",
    review_status: str = "current",
    quality_state: str | None = None,
    expiry_date: date | None = None,
    review_due_date: date | None = None,
    error_message: str | None = None,
) -> Document:
    return Document(
        organization_id=org_id,
        filename=filename,
        status=status,
        ingestion_source=ingestion_source,
        ocr_quality_status=ocr_quality_status,
        trust_status=trust_status,
        review_status=review_status,
        quality_state=quality_state,
        expiry_date=expiry_date,
        review_due_date=review_due_date,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# A. Pure helper unit tests
# ---------------------------------------------------------------------------


def test_freshness_expired_by_date() -> None:
    today = date(2026, 8, 19)
    result = _freshness(
        trust_status="current", review_status="current", expiry_date=date(2026, 1, 1), today=today
    )
    assert result == "expired"


def test_freshness_stale_by_trust_status() -> None:
    today = date(2026, 8, 19)
    result = _freshness(
        trust_status="stale", review_status="current", expiry_date=None, today=today
    )
    assert result == "stale"


def test_freshness_defaults_to_fresh() -> None:
    today = date(2026, 8, 19)
    result = _freshness(
        trust_status="current", review_status="current", expiry_date=None, today=today
    )
    assert result == "fresh"


def test_needs_review_by_due_date() -> None:
    today = date(2026, 8, 19)
    assert _needs_review(review_status="current", review_due_date=date(2026, 1, 1), today=today)
    assert not _needs_review(review_status="current", review_due_date=date(2027, 1, 1), today=today)


def test_needs_review_by_status() -> None:
    today = date(2026, 8, 19)
    assert _needs_review(review_status="needs_review", review_due_date=None, today=today)


# ---------------------------------------------------------------------------
# B. Summary — indexed/failed/pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_indexing_status_counts(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, status=DocumentStatus.indexed.value))
    db_session.add(_doc(org_id, status=DocumentStatus.indexed.value))
    db_session.add(_doc(org_id, status=DocumentStatus.failed.value))
    db_session.add(_doc(org_id, status=DocumentStatus.extraction_failed.value))
    db_session.add(_doc(org_id, status=DocumentStatus.processing.value))
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.indexed == 2
    assert summary.failed_indexing == 2
    assert summary.pending == 1


# ---------------------------------------------------------------------------
# C. Summary — OCR counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_ocr_counts(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, ocr_quality_status="high"))
    db_session.add(_doc(org_id, ocr_quality_status="low"))
    db_session.add(_doc(org_id, ocr_quality_status="failed"))
    db_session.add(_doc(org_id, ocr_quality_status="not_required"))
    db_session.add(_doc(org_id, ocr_quality_status=None))
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.ocr_required == 3  # high, low, failed — excludes not_required and None
    assert summary.ocr_low_confidence == 2  # low, failed


# ---------------------------------------------------------------------------
# D. Summary — trust/review lifecycle counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_trust_review_counts(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    today = datetime.now(tz=UTC).date()

    db_session.add(_doc(org_id, trust_status="stale", review_status="current"))
    db_session.add(_doc(org_id, trust_status="deprecated", review_status="current"))
    db_session.add(_doc(org_id, trust_status="current", expiry_date=today - timedelta(days=1)))
    db_session.add(_doc(org_id, quality_state="unreviewed"))
    db_session.add(_doc(org_id, review_status="needs_review"))
    db_session.add(_doc(org_id, review_due_date=today - timedelta(days=5)))
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.stale == 1
    assert summary.deprecated == 1
    assert summary.expired == 1
    assert summary.unreviewed == 1
    assert summary.needs_review == 2  # explicit needs_review + overdue due date


# ---------------------------------------------------------------------------
# E. Summary — missing_metadata anti-join (F256)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_missing_metadata(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    required_field = MetadataField(
        organization_id=org_id,
        name="owner_team",
        display_name="Owner Team",
        field_type="text",
        is_required=True,
        is_active=True,
    )
    db_session.add(required_field)
    complete_doc = _doc(org_id, filename="complete.pdf")
    incomplete_doc = _doc(org_id, filename="incomplete.pdf")
    db_session.add(complete_doc)
    db_session.add(incomplete_doc)
    await db_session.flush()

    db_session.add(
        DocumentMetadata(
            document_id=complete_doc.id,
            field_id=required_field.id,
            organization_id=org_id,
            value_text="Platform",
        )
    )
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.missing_metadata == 1


# ---------------------------------------------------------------------------
# F. Summary — table extraction warnings (F298)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_table_extraction_warnings(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    doc = _doc(org_id, filename="tables.pdf")
    db_session.add(doc)
    await db_session.flush()

    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            text="| a | b |",
            token_count=10,
            embedding_model="test-embed",
            chunk_type="table",
            table_metadata={"is_valid": False, "confidence": 0.2, "row_count": 2, "col_count": 2},
        )
    )
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=1,
            text="| c | d |",
            token_count=10,
            embedding_model="test-embed",
            chunk_type="table",
            table_metadata={"is_valid": True, "confidence": 0.9, "row_count": 2, "col_count": 2},
        )
    )
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.table_extraction_warnings == 1


# ---------------------------------------------------------------------------
# G. Summary — total_sources includes collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_total_sources_includes_collections(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id))
    db_session.add(_doc(org_id))
    db_session.add(Collection(organization_id=org_id, name="Policies"))
    await db_session.flush()

    summary = await SourceHealthService().get_summary(db_session, organization_id=org_id)
    assert summary.total_sources == 3


# ---------------------------------------------------------------------------
# H. list_sources — file vs connector split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_file_vs_connector(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, filename="uploaded.pdf"))
    db_session.add(
        _doc(
            org_id,
            filename="synced.pdf",
            ingestion_source=DocumentIngestionSource.connector.value,
        )
    )
    await db_session.flush()

    service = SourceHealthService()
    file_rows = await service.list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(source_type="file"),
    )
    connector_rows = await service.list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(source_type="connector"),
    )
    assert [r.source_name for r in file_rows.rows] == ["uploaded.pdf"]
    assert [r.source_name for r in connector_rows.rows] == ["synced.pdf"]


# ---------------------------------------------------------------------------
# I. list_sources — status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_status_filter(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, filename="ok.pdf", status=DocumentStatus.indexed.value))
    db_session.add(_doc(org_id, filename="bad.pdf", status=DocumentStatus.failed.value))
    await db_session.flush()

    result = await SourceHealthService().list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(status=DocumentStatus.failed.value),
    )
    assert [r.source_name for r in result.rows] == ["bad.pdf"]


# ---------------------------------------------------------------------------
# J. list_sources — freshness filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_freshness_filter(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, filename="fresh.pdf"))
    db_session.add(_doc(org_id, filename="stale.pdf", trust_status="stale"))
    await db_session.flush()

    result = await SourceHealthService().list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(freshness="stale"),
    )
    assert [r.source_name for r in result.rows] == ["stale.pdf"]


# ---------------------------------------------------------------------------
# K. list_sources — ocr_quality filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_ocr_quality_filter(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, filename="good-ocr.pdf", ocr_quality_status="high"))
    db_session.add(_doc(org_id, filename="bad-ocr.pdf", ocr_quality_status="low"))
    await db_session.flush()

    result = await SourceHealthService().list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(ocr_quality="low"),
    )
    assert [r.source_name for r in result.rows] == ["bad-ocr.pdf"]
    assert "ocr_retry" in result.rows[0].available_actions


# ---------------------------------------------------------------------------
# L. list_sources — name search filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_name_search(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_doc(org_id, filename="quarterly-report.pdf"))
    db_session.add(_doc(org_id, filename="handbook.pdf"))
    await db_session.flush()

    result = await SourceHealthService().list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(q="quarterly"),
    )
    assert [r.source_name for r in result.rows] == ["quarterly-report.pdf"]


# ---------------------------------------------------------------------------
# M. list_sources — pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_pagination(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    for i in range(5):
        db_session.add(_doc(org_id, filename=f"doc-{i}.pdf"))
    await db_session.flush()

    result = await SourceHealthService().list_sources(
        db_session,
        organization_id=org_id,
        filters=SourceHealthFilters(),
        page=1,
        page_size=2,
    )
    assert result.total == 5
    assert len(result.rows) == 2
    assert result.page == 1


# ---------------------------------------------------------------------------
# N. get_error_detail — document with table warnings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_detail_document(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    doc = _doc(org_id, filename="broken.pdf", status="failed", error_message="OCR timed out")
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            text="| a |",
            token_count=5,
            embedding_model="test-embed",
            chunk_type="table",
            table_metadata={"is_valid": False, "confidence": 0.1},
        )
    )
    await db_session.flush()

    detail = await SourceHealthService().get_error_detail(
        db_session, organization_id=org_id, source_type="file", source_id=doc.id
    )
    assert detail is not None
    assert detail.error_message == "OCR timed out"
    assert len(detail.table_warnings) == 1


# ---------------------------------------------------------------------------
# O. get_error_detail — unknown source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_detail_not_found(db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    detail = await SourceHealthService().get_error_detail(
        db_session, organization_id=ctx["org_id"], source_type="file", source_id=uuid4()
    )
    assert detail is None


# ---------------------------------------------------------------------------
# P. HTTP — role guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_summary_member_gets_403(
    source_health_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.member.value)
    resp = await source_health_client.get(
        "/api/admin/source-health/summary", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Q. HTTP — org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_summary_org_isolation(
    source_health_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx_a = await _make_org_user(db_session)
    ctx_b = await _make_org_user(db_session)

    db_session.add(_doc(ctx_b["org_id"], status=DocumentStatus.failed.value))
    db_session.add(_doc(ctx_b["org_id"], status=DocumentStatus.failed.value))
    await db_session.flush()

    resp = await source_health_client.get(
        "/api/admin/source-health/summary", headers=_auth(ctx_a["token"])
    )
    assert resp.status_code == 200
    assert resp.json()["total_sources"] == 0


# ---------------------------------------------------------------------------
# R. HTTP — sources list includes available_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_list_sources_available_actions(
    source_health_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    db_session.add(_doc(org_id, filename="a.pdf"))
    await db_session.flush()

    resp = await source_health_client.get(
        "/api/admin/source-health/sources", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    row = data["rows"][0]
    assert row["source_type"] == "file"
    assert "reindex" in row["available_actions"]
    assert "assign_reviewer" in row["available_actions"]


# ---------------------------------------------------------------------------
# S. HTTP — error detail 404 for unknown id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_error_detail_404(
    source_health_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    missing_id = uuid4()
    resp = await source_health_client.get(
        f"/api/admin/source-health/sources/file/{missing_id}/error",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T. HTTP — CSV export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_export_csv(source_health_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    db_session.add(_doc(org_id, filename="export-me.pdf"))
    await db_session.flush()

    resp = await source_health_client.get(
        "/api/admin/source-health/export", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    assert body.startswith("source_type,source_name,collection,owner,status")
    assert "export-me.pdf" in body
