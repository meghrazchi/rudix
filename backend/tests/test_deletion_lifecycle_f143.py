"""Tests for F143 — data deletion lifecycle: delete_requested, retained_by_policy,
bulk delete, retry delete, and admin deletion status endpoint."""

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
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
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http import admin_documents as admin_documents_api
from app.interfaces.http import documents as documents_api
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


class FakeTaskResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class FakeDeleteDocumentTask:
    def __init__(self) -> None:
        self.delay_calls: list[dict[str, Any]] = []
        self.fail_delay = False

    def delay(self, document_id: str, **kwargs: Any) -> FakeTaskResult:
        if self.fail_delay:
            raise RuntimeError("enqueue failure")
        self.delay_calls.append({"document_id": document_id, **kwargs})
        return FakeTaskResult(task_id=f"delete-task-{len(self.delay_calls)}")


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def fake_task(monkeypatch: pytest.MonkeyPatch) -> FakeDeleteDocumentTask:
    fake = FakeDeleteDocumentTask()
    monkeypatch.setattr(documents_api, "delete_document_task", fake)
    monkeypatch.setattr(admin_documents_api, "delete_document_task", fake)
    return fake


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    prefix: str = "f143",
) -> tuple[User, Organization]:
    org = Organization(name=f"{prefix}-org", slug=f"{prefix}-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"{prefix}-user-{uuid4().hex[:8]}",
        email=f"{prefix}-{uuid4().hex[:8]}@example.com",
        display_name=f"{prefix} User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, org


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
    status: DocumentStatus = DocumentStatus.indexed,
    retention_class: str | None = None,
) -> Document:
    repo = DocumentRepository()
    document = await repo.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename="lifecycle-test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{organization.id}/{uploader.id}/{uuid4()}.pdf",
        status=status.value,
    )
    if retention_class:
        document.retention_class = retention_class
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _get_document(db_session: AsyncSession, *, document_id: UUID) -> Document | None:
    result = await db_session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def _get_audit_actions(
    db_session: AsyncSession,
    *,
    resource_id: UUID,
) -> list[str]:
    result = await db_session.execute(
        select(AuditLog.action).where(AuditLog.resource_id == resource_id)
    )
    return [row[0] for row in result.all()]


def _auth_headers(*, token: str, organization_id: str, request_id: str = "req-f143") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
        "X-Request-ID": request_id,
    }


# ---------------------------------------------------------------------------
# DELETE /documents/{id} → delete_requested status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_transitions_to_delete_requested(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member, prefix="dr")
    document = await _seed_document(db_session, organization=org, uploader=user)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "delete_requested"

    await db_session.refresh(document)
    assert document.status == DocumentStatus.delete_requested.value
    assert document.deletion_requested_at is not None

    assert len(fake_task.delay_calls) == 1

    actions = await _get_audit_actions(db_session, resource_id=document.id)
    assert "document.delete.requested" in actions
    assert "document.delete.queued" in actions


@pytest.mark.asyncio
async def test_delete_document_blocked_by_legal_hold(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="hold")
    document = await _seed_document(
        db_session, organization=org, uploader=user, retention_class="legal_hold"
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "retained_by_policy"
    assert body["hold_reason"] is not None

    await db_session.refresh(document)
    assert document.status == DocumentStatus.retained_by_policy.value

    # No Celery task enqueued for retained documents.
    assert len(fake_task.delay_calls) == 0

    actions = await _get_audit_actions(db_session, resource_id=document.id)
    assert "document.delete.retained" in actions


@pytest.mark.asyncio
async def test_delete_already_delete_requested_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member, prefix="idem")
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        status=DocumentStatus.delete_requested,
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "delete_requested"

    # No additional task enqueued for already-in-flight deletion.
    assert len(fake_task.delay_calls) == 0


# ---------------------------------------------------------------------------
# POST /documents/bulk-delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_delete_documents(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="bulk")
    doc1 = await _seed_document(db_session, organization=org, uploader=user)
    doc2 = await _seed_document(db_session, organization=org, uploader=user)
    doc3 = await _seed_document(
        db_session, organization=org, uploader=user, retention_class="legal_hold"
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.post(
        "/api/v1/documents/bulk-delete",
        json={"document_ids": [str(doc1.id), str(doc2.id), str(doc3.id)]},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 2
    assert body["retained"] == 1
    assert body["errors"] == 0

    statuses = {r["document_id"]: r["status"] for r in body["results"]}
    assert statuses[str(doc1.id)] == "delete_requested"
    assert statuses[str(doc2.id)] == "delete_requested"
    assert statuses[str(doc3.id)] == "retained_by_policy"

    # Two tasks enqueued (one per non-retained document).
    assert len(fake_task.delay_calls) == 2


@pytest.mark.asyncio
async def test_bulk_delete_rejects_empty_list(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="bempty")
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await client.post(
        "/api/v1/documents/bulk-delete",
        json={"document_ids": []},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /admin/documents/deletion/{id}/retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_delete_document_from_delete_requested(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="retry")
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        status=DocumentStatus.delete_requested,
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.post(
        f"/api/v1/admin/documents/deletion/{document.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "delete_requested"
    assert body["queue_status"] == "queued"

    assert len(fake_task.delay_calls) == 1

    actions = await _get_audit_actions(db_session, resource_id=document.id)
    assert "document.delete.retry_requested" in actions
    assert "document.delete.queued" in actions


@pytest.mark.asyncio
async def test_retry_delete_document_not_retryable(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="noretry")
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        status=DocumentStatus.deleted,
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.post(
        f"/api/v1/admin/documents/deletion/{document.id}/retry",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409
    assert len(fake_task.delay_calls) == 0


# ---------------------------------------------------------------------------
# GET /admin/documents/deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_deletion_status(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, prefix="admlist")
    doc_dr = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.delete_requested
    )
    doc_dl = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.deleting
    )
    doc_rp = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.retained_by_policy
    )
    # Indexed document should NOT appear.
    await _seed_document(db_session, organization=org, uploader=user, status=DocumentStatus.indexed)

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.get(
        "/api/v1/admin/documents/deletion",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {item["document_id"] for item in body["items"]}
    assert str(doc_dr.id) in returned_ids
    assert str(doc_dl.id) in returned_ids
    assert str(doc_rp.id) in returned_ids


@pytest.mark.asyncio
async def test_admin_list_deletion_requires_admin_role(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member, prefix="admauth")
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await client.get(
        "/api/v1/admin/documents/deletion",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# RAG exclusion — delete_requested documents must not be retrievable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_requested_document_status_is_not_indexed(
    db_session: AsyncSession,
) -> None:
    """delete_requested documents are excluded from retrieval because Qdrant
    vectors are removed during the worker cleanup phase (delete_index stage).
    This test verifies the status transition is correct and documents cannot
    be fetched as 'indexed' after deletion is requested."""
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member, prefix="ragexcl")
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.indexed
    )

    repo = DocumentRepository()
    updated = await repo.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.delete_requested.value,
        error_message=None,
    )
    await db_session.commit()

    assert updated is not None
    assert updated.status == DocumentStatus.delete_requested.value
    # Document is not in the 'indexed' state — will not be returned by indexed-only filters.
    assert updated.status != DocumentStatus.indexed.value
