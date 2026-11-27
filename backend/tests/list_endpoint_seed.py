"""Seed helpers and an HTTP client for the R04-03/R04-04 list-endpoint tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

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

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.collections.repositories.collections import CollectionRepository
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.main import app
from app.models.chat import ChatSession
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.document import Document, DocumentChunk
from app.models.enums import ChatRole, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

chat_repository = ChatRepository()
document_repository = DocumentRepository()
collection_repository = CollectionRepository()
evaluation_repository = EvaluationRepository()


@dataclass
class Tenant:
    organization: Organization
    user: User
    headers: dict[str, str]

    @property
    def org_id(self) -> UUID:
        return self.organization.id


def configure_app_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """App-token auth settings; call before ``seed_tenant`` mints tokens."""
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()


@asynccontextmanager
async def api_client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    configure_app_auth(monkeypatch)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        get_auth_provider.cache_clear()


async def seed_tenant(
    db_session: AsyncSession, *, role: OrganizationRole = OrganizationRole.owner
) -> Tenant:
    suffix = uuid4().hex[:10]
    organization = Organization(name=f"B1 {suffix}", slug=f"b1-{suffix}")
    db_session.add(organization)
    await db_session.flush()
    user = User(
        organization_id=organization.id,
        external_auth_id=f"b1-user-{suffix}",
        email=f"b1-{suffix}@example.com",
        display_name="B1 User",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=role.value)
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": str(organization.id)}
    return Tenant(organization=organization, user=user, headers=headers)


async def seed_document(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    filename: str | None = None,
    chunks: int = 1,
    status: str = "indexed",
) -> tuple[Document, list[DocumentChunk]]:
    name = filename or f"doc-{uuid4().hex[:8]}.pdf"
    document = await document_repository.create_document(
        db_session,
        organization_id=tenant.org_id,
        uploaded_by_user_id=tenant.user.id,
        filename=name,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{name}-{uuid4()}.pdf",
        status=status,
    )
    created: list[DocumentChunk] = []
    for index in range(chunks):
        created.append(
            await document_repository.create_document_chunk(
                db_session,
                document_id=document.id,
                page_number=1,
                chunk_index=index,
                text=f"chunk {index} of {name}",
                token_count=10,
                embedding_model=settings.openai_embedding_model,
                index_version=settings.document_index_version,
                qdrant_point_id=f"{document.id}:{settings.document_index_version}:{index}",
            )
        )
    return document, created


async def seed_chat_session(
    db_session: AsyncSession, tenant: Tenant, *, title: str | None = None
) -> ChatSession:
    return await chat_repository.create_chat_session(
        db_session,
        organization_id=tenant.org_id,
        user_id=tenant.user.id,
        title=title or f"session-{uuid4().hex[:6]}",
    )


async def seed_turns(
    db_session: AsyncSession,
    chat_session: ChatSession,
    *,
    turns: int,
    document: Document,
    chunk: DocumentChunk,
    citations_per_answer: int = 2,
) -> None:
    """Add ``turns`` user/assistant pairs; every answer cites ``document``."""
    for turn in range(turns):
        await chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.user.value,
            content=f"question {turn}",
        )
        answer = await chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.assistant.value,
            content=f"answer {turn}",
            confidence_score=0.8,
        )
        for index in range(citations_per_answer):
            await chat_repository.create_citation(
                db_session,
                chat_message_id=answer.id,
                document_id=document.id,
                chunk_id=chunk.id,
                text_snippet=f"snippet {turn}.{index}",
                page_number=1,
                similarity_score=0.5 + index / 100,
            )


async def seed_connection(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    indexed_documents: int = 1,
    status: str = "active",
    deleted: bool = False,
) -> tuple[ConnectorConnection, list[Document]]:
    """A connection with ``indexed_documents`` connector documents (one item each)."""
    key = "confluence"
    provider = (
        await db_session.execute(select(ConnectorProvider).where(ConnectorProvider.key == key))
    ).scalar_one_or_none()
    if provider is None:
        provider = ConnectorProvider(
            key=key,
            display_name="Confluence",
            auth_type="oauth2",
            capabilities_json=[],
            config_schema_json={},
            rate_limits_json=[],
            export_formats_json=[],
            is_enabled=True,
        )
        db_session.add(provider)
        await db_session.flush()
    connection = ConnectorConnection(
        organization_id=tenant.org_id,
        provider_id=provider.id,
        display_name=f"Connection {uuid4().hex[:6]}",
        status=status,
        auth_config_json={},
        created_by_user_id=tenant.user.id,
    )
    db_session.add(connection)
    await db_session.flush()
    documents: list[Document] = []
    for index in range(indexed_documents):
        item = ExternalItem(
            organization_id=tenant.org_id,
            connection_id=connection.id,
            provider_item_id=f"item-{uuid4().hex}",
            item_type="wiki_page",
            title=f"Item {index}",
            source_url=f"https://confluence.example.test/items/{index}",
            content_hash="d" * 64,
            source_updated_at=datetime.now(UTC),
            sync_version=1,
            visibility="org_wide",
            metadata_json={},
            permissions_json={},
            deleted_at=datetime.now(UTC) if deleted else None,
        )
        db_session.add(item)
        await db_session.flush()
        document, _ = await seed_document(db_session, tenant, chunks=0)
        document.connector_external_item_id = item.id
        document.ingestion_source = "connector"
        db_session.add(document)
        await db_session.flush()
        documents.append(document)
    return connection, documents


async def seed_collection(
    db_session: AsyncSession, tenant: Tenant, *, documents: list[Document]
) -> UUID:
    collection = await collection_repository.create(
        db_session,
        organization_id=tenant.org_id,
        owner_id=tenant.user.id,
        name=f"Collection {uuid4().hex[:6]}",
        description=None,
        access_policy="org_wide",
    )
    for document in documents:
        await collection_repository.add_document(
            db_session, collection_id=collection.id, document_id=document.id
        )
    return collection.id


async def seed_evaluation_set(
    db_session: AsyncSession, tenant: Tenant, *, questions: int = 2
) -> UUID:
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=tenant.org_id,
        name=f"Set {uuid4().hex[:6]}",
        owner_id=tenant.user.id,
    )
    for index in range(questions):
        await evaluation_repository.create_evaluation_question(
            db_session,
            evaluation_set_id=evaluation_set.id,
            question=f"Question {index}?",
        )
    return evaluation_set.id
