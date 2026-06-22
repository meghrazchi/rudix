import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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


class FakeReindexTask:
    def __init__(self) -> None:
        self.delay_calls: list[dict[str, Any]] = []
        self.fail_delay = False

    def delay(self, document_id: str, **kwargs: Any) -> FakeTaskResult:
        if self.fail_delay:
            raise RuntimeError("enqueue failure")
        self.delay_calls.append({"document_id": document_id, **kwargs})
        return FakeTaskResult(task_id=f"reindex-task-{len(self.delay_calls)}")


@pytest_asyncio.fixture
async def reindex_client(
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
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def fake_reindex_task(monkeypatch: pytest.MonkeyPatch) -> FakeReindexTask:
    fake = FakeReindexTask()
    monkeypatch.setattr(documents_api, "reindex_document_task", fake)
    return fake


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    slug_prefix: str,
) -> tuple[User, Organization]:
    org = Organization(name=f"{slug_prefix}-org", slug=f"{slug_prefix}-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"{slug_prefix}-user-{uuid4().hex[:8]}",
        email=f"{slug_prefix}-{uuid4().hex[:8]}@example.com",
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
    status: DocumentStatus,
    error_message: str | None = None,
) -> Document:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename="reindex.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{organization.id}/{uploader.id}/{uuid4()}.pdf",
        status=status.value,
    )
    if error_message is not None:
        _ = await repository.update_document_status(
            db_session,
            document_id=document.id,
            status=status.value,
            error_message=error_message,
        )
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _get_document(db_session: AsyncSession, *, document_id: UUID) -> Document | None:
    result = await db_session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
        "X-Request-ID": "req-reindex-1",
    }


@pytest.mark.asyncio
async def test_reindex_requires_admin_or_owner_role(
    reindex_client: AsyncClient,
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,
) -> None:
    user, org = await _seed_org_user(
        db_session, role=OrganizationRole.member, slug_prefix="reindex-member"
    )
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.indexed
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
    assert fake_reindex_task.delay_calls == []


@pytest.mark.asyncio
async def test_reindex_queues_task_and_sets_processing_status(
    reindex_client: AsyncClient,
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,
) -> None:
    user, org = await _seed_org_user(
        db_session, role=OrganizationRole.admin, slug_prefix="reindex-admin"
    )
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.indexed
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "document_id": str(document.id),
        "status": DocumentStatus.processing.value,
        "queue_status": "queued",
    }
    assert len(fake_reindex_task.delay_calls) == 1
    delay_call = fake_reindex_task.delay_calls[0]
    assert delay_call["document_id"] == str(document.id)
    assert delay_call["organization_id"] == str(org.id)
    assert delay_call["user_id"] == str(user.id)
    assert delay_call["request_id"] == "req-reindex-1"
    assert delay_call["force"] is False

    updated = await _get_document(db_session, document_id=document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.processing.value
    assert updated.error_message is None
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 2
    actions = {row.action for row in audit_logs}
    assert actions == {"document.reindex.requested", "document.reindex.queued"}


@pytest.mark.asyncio
async def test_reindex_blocks_concurrent_processing_requests(
    reindex_client: AsyncClient,
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,
) -> None:
    user, org = await _seed_org_user(
        db_session, role=OrganizationRole.owner, slug_prefix="reindex-owner"
    )
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.processing
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Document is already being processed"
    assert fake_reindex_task.delay_calls == []


@pytest.mark.asyncio
async def test_force_reindex_allows_processing_documents(
    reindex_client: AsyncClient,
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,
) -> None:
    user, org = await _seed_org_user(
        db_session, role=OrganizationRole.admin, slug_prefix="reindex-force"
    )
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.processing
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"force": True},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "document_id": str(document.id),
        "status": DocumentStatus.processing.value,
        "queue_status": "queued",
    }
    assert len(fake_reindex_task.delay_calls) == 1
    delay_call = fake_reindex_task.delay_calls[0]
    assert delay_call["document_id"] == str(document.id)
    assert delay_call["force"] is True
    assert delay_call["organization_id"] == str(org.id)
    assert delay_call["user_id"] == str(user.id)

    updated = await _get_document(db_session, document_id=document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.processing.value
    assert updated.error_message is None
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 2
    actions = {row.action for row in audit_logs}
    assert actions == {"document.reindex.requested", "document.reindex.queued"}


@pytest.mark.asyncio
async def test_reindex_enqueue_failure_restores_previous_status_and_error(
    reindex_client: AsyncClient,
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,
) -> None:
    fake_reindex_task.fail_delay = True
    user, org = await _seed_org_user(
        db_session, role=OrganizationRole.admin, slug_prefix="reindex-fail"
    )
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        status=DocumentStatus.failed,
        error_message="legacy-error",
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Document re-index request could not be queued"

    updated = await _get_document(db_session, document_id=document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.failed.value
    assert updated.error_message == "legacy-error"
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 2
    actions = {row.action for row in audit_logs}
    assert actions == {"document.reindex.requested", "document.reindex.enqueue_failed"}
