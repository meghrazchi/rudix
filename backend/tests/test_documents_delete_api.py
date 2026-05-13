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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
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

from app.api import documents as documents_api
from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User
from app.repositories.documents import DocumentRepository


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
async def delete_client(
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
def fake_delete_document_task(monkeypatch: pytest.MonkeyPatch) -> FakeDeleteDocumentTask:
    fake = FakeDeleteDocumentTask()
    monkeypatch.setattr(documents_api, "delete_document_task", fake)
    return fake


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    org_slug_prefix: str,
) -> tuple[User, Organization]:
    org = Organization(name=f"{org_slug_prefix}-org", slug=f"{org_slug_prefix}-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"{org_slug_prefix}-user-{uuid4().hex[:8]}",
        email=f"{org_slug_prefix}-{uuid4().hex[:8]}@example.com",
        display_name=f"{org_slug_prefix} User",
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
) -> Document:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename="delete-me.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{organization.id}/{uploader.id}/{uuid4()}.pdf",
        status=status.value,
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _get_document(db_session: AsyncSession, *, document_id: UUID) -> Document | None:
    result = await db_session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
        "X-Request-ID": "req-delete-1",
    }


@pytest.mark.asyncio
async def test_delete_document_marks_deleting_and_enqueues_task(
    delete_client: AsyncClient,
    db_session: AsyncSession,
    fake_delete_document_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(
        db_session,
        role=OrganizationRole.member,
        org_slug_prefix="delete-primary",
    )
    document = await _seed_document(db_session, organization=org, uploader=user, status=DocumentStatus.indexed)
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await delete_client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["status"] == DocumentStatus.deleting.value
    assert len(fake_delete_document_task.delay_calls) == 1
    delay_call = fake_delete_document_task.delay_calls[0]
    assert delay_call["document_id"] == str(document.id)
    assert delay_call["request_id"] == "req-delete-1"
    assert delay_call["organization_id"] == str(org.id)
    assert delay_call["user_id"] == str(user.id)

    updated = await _get_document(db_session, document_id=document.id)
    assert updated is not None
    assert updated.status == DocumentStatus.deleting.value
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 2
    actions = {row.action for row in audit_logs}
    assert actions == {"document.delete.requested", "document.delete.queued"}


@pytest.mark.asyncio
async def test_delete_document_returns_403_for_viewer(
    delete_client: AsyncClient,
    db_session: AsyncSession,
    fake_delete_document_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(
        db_session,
        role=OrganizationRole.viewer,
        org_slug_prefix="delete-viewer",
    )
    document = await _seed_document(db_session, organization=org, uploader=user, status=DocumentStatus.indexed)
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await delete_client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"
    assert fake_delete_document_task.delay_calls == []


@pytest.mark.asyncio
async def test_delete_document_hides_cross_org_document_access(
    delete_client: AsyncClient,
    db_session: AsyncSession,
    fake_delete_document_task: FakeDeleteDocumentTask,
) -> None:
    user, primary_org = await _seed_org_user(
        db_session,
        role=OrganizationRole.member,
        org_slug_prefix="delete-primary-org",
    )
    foreign_user, foreign_org = await _seed_org_user(
        db_session,
        role=OrganizationRole.member,
        org_slug_prefix="delete-foreign-org",
    )
    foreign_document = await _seed_document(
        db_session,
        organization=foreign_org,
        uploader=foreign_user,
        status=DocumentStatus.indexed,
    )

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )
    response = await delete_client.delete(
        f"/api/v1/documents/{foreign_document.id}",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
    assert fake_delete_document_task.delay_calls == []


@pytest.mark.asyncio
async def test_delete_document_is_idempotent_for_already_deleted_records(
    delete_client: AsyncClient,
    db_session: AsyncSession,
    fake_delete_document_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(
        db_session,
        role=OrganizationRole.member,
        org_slug_prefix="delete-already",
    )
    document = await _seed_document(db_session, organization=org, uploader=user, status=DocumentStatus.deleted)
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await delete_client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["status"] == DocumentStatus.deleted.value
    assert fake_delete_document_task.delay_calls == []


@pytest.mark.asyncio
async def test_delete_document_does_not_requeue_when_already_deleting(
    delete_client: AsyncClient,
    db_session: AsyncSession,
    fake_delete_document_task: FakeDeleteDocumentTask,
) -> None:
    user, org = await _seed_org_user(
        db_session,
        role=OrganizationRole.member,
        org_slug_prefix="delete-in-flight",
    )
    document = await _seed_document(db_session, organization=org, uploader=user, status=DocumentStatus.deleting)
    token = create_app_access_token(subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600)

    response = await delete_client.delete(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["status"] == DocumentStatus.deleting.value
    assert fake_delete_document_task.delay_calls == []
