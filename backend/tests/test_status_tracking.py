import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.workers import status_tracking


@pytest_asyncio.fixture
async def seeded_document(db_session: AsyncSession) -> Document:
    org = Organization(name="Status Track Org", slug=f"status-track-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"status-track-user-{uuid4().hex[:8]}",
        email=f"status-track-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
        )
    )
    await db_session.flush()

    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="status.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{user.id}/{uuid4()}.txt",
        status=DocumentStatus.uploaded.value,
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


@pytest.mark.asyncio
async def test_set_document_status_is_idempotent_when_values_unchanged(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(status_tracking, "SessionLocal", session_factory)

    updated = await status_tracking._set_document_status_async(
        str(seeded_document.id),
        status=DocumentStatus.processing,
        error_message=None,
    )
    assert updated is True

    calls = {"count": 0}
    original_update = status_tracking._document_repository.update_document_status

    async def _update_wrapper(*args, **kwargs):
        calls["count"] += 1
        return await original_update(*args, **kwargs)

    monkeypatch.setattr(
        status_tracking._document_repository, "update_document_status", _update_wrapper
    )

    second_update = await status_tracking._set_document_status_async(
        str(seeded_document.id),
        status=DocumentStatus.processing,
        error_message=None,
    )
    assert second_update is True
    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_set_document_status_clears_stale_error_on_processing(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = seeded_document.id
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(status_tracking, "SessionLocal", session_factory)

    repository = DocumentRepository()
    _ = await repository.update_document_status(
        db_session,
        document_id=document_id,
        status=DocumentStatus.failed.value,
        error_message="legacy error",
    )
    await db_session.commit()

    updated = await status_tracking._set_document_status_async(
        str(document_id),
        status=DocumentStatus.processing,
        error_message=None,
    )
    assert updated is True

    db_session.expire_all()
    refreshed = await repository.get_document_by_id(db_session, document_id=document_id)
    assert refreshed is not None
    assert refreshed.status == DocumentStatus.processing.value
    assert refreshed.error_message is None
