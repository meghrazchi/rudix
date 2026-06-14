"""Focused tests for GraphRAG retrieval expansion and fallback behavior."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
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

from app.domains.chat.services.graph_retrieval_service import GraphRetrievalService
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import DocumentChunk
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


class _FakeGraphService:
    def __init__(
        self,
        *,
        available: bool = True,
        seed_entity_id: UUID | None = None,
        allowed_document_id: UUID | None = None,
        allowed_chunk_id: UUID | None = None,
        foreign_document_id: UUID | None = None,
        foreign_chunk_id: UUID | None = None,
    ) -> None:
        self.available = available
        self.seed_entity_id = seed_entity_id or uuid4()
        self.allowed_document_id = allowed_document_id or uuid4()
        self.allowed_chunk_id = allowed_chunk_id or uuid4()
        self.foreign_document_id = foreign_document_id or uuid4()
        self.foreign_chunk_id = foreign_chunk_id or uuid4()
        self.calls: list[tuple[str, dict[str, object]]] = []

    def is_available(self) -> bool:
        self.calls.append(("is_available", {}))
        return self.available

    async def find_entities_by_name(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("find_entities_by_name", dict(kwargs)))
        return [
            {
                "entity_id": str(self.seed_entity_id),
                "canonical_name": "Annual Leave",
                "entity_type": "Policy",
            }
        ]

    async def find_related_entities(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("find_related_entities", dict(kwargs)))
        return []

    async def get_evidence_for_entities(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("get_evidence_for_entities", dict(kwargs)))
        evidence_rows = kwargs.get("entity_ids", [])
        entity_id = str(evidence_rows[0]) if evidence_rows else str(self.seed_entity_id)
        return [
            {
                "entity_id": entity_id,
                "canonical_name": "Annual Leave",
                "chunk_id": self.allowed_chunk_id,
                "source_document_id": self.allowed_document_id,
                "workspace_id": "ws-1",
                "filename": "allowed.pdf",
                "page_number": 1,
                "chunk_index": 0,
                "confidence": 0.95,
                "citation_text": "Allowed evidence",
                "evidence_text": "Allowed evidence",
            },
            {
                "entity_id": entity_id,
                "canonical_name": "Annual Leave",
                "chunk_id": self.foreign_chunk_id,
                "source_document_id": self.foreign_document_id,
                "workspace_id": "ws-2",
                "filename": "foreign.pdf",
                "page_number": 1,
                "chunk_index": 0,
                "confidence": 0.95,
                "citation_text": "Foreign evidence",
                "evidence_text": "Foreign evidence",
            },
        ]


async def _seed_principal(db_session: AsyncSession) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Graph Primary", slug=f"graph-primary-{uuid4().hex[:8]}")
    foreign_org = Organization(name="Graph Foreign", slug=f"graph-foreign-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, foreign_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"graph-user-{uuid4().hex[:8]}",
        email=f"graph-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=primary_org.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()
    return user, primary_org, foreign_org


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
    filename: str,
    text: str,
) -> tuple[object, DocumentChunk]:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=filename,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{filename}-{uuid4()}.pdf",
        status="indexed",
    )
    chunk = await repository.create_document_chunk(
        db_session,
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        text=text,
        token_count=40,
        embedding_model="text-embedding-3-small",
        index_version=1,
        qdrant_point_id=f"{document.id}:1:0",
    )
    await db_session.commit()
    await db_session.refresh(document)
    await db_session.refresh(chunk)
    return document, chunk


@pytest.mark.asyncio
async def test_graph_retrieval_service_respects_document_scope(
    db_session: AsyncSession,
) -> None:
    user, primary_org, foreign_org = await _seed_principal(db_session)
    allowed_document, allowed_chunk = await _seed_document(
        db_session,
        organization=primary_org,
        uploader=user,
        filename="allowed.pdf",
        text="Allowed document text.",
    )
    foreign_user = User(
        organization_id=foreign_org.id,
        external_auth_id=f"graph-foreign-{uuid4().hex[:8]}",
        email=f"graph-foreign-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(foreign_user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=foreign_org.id,
            user_id=foreign_user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()
    foreign_document, foreign_chunk = await _seed_document(
        db_session,
        organization=foreign_org,
        uploader=foreign_user,
        filename="foreign.pdf",
        text="Foreign document text.",
    )

    fake_graph_service = _FakeGraphService(
        allowed_document_id=allowed_document.id,
        allowed_chunk_id=allowed_chunk.id,
        foreign_document_id=foreign_document.id,
        foreign_chunk_id=foreign_chunk.id,
    )
    service = GraphRetrievalService(graph_service=fake_graph_service)  # type: ignore[arg-type]

    result = await service.expand(
        session=db_session,
        organization_id=primary_org.id,
        question='What does "Annual Leave" mean?',
        allowed_document_ids=[allowed_document.id],
        graph_enabled=True,
    )

    assert result.graph_context_enabled is True
    assert result.graph_context_used is True
    assert result.graph_context_unavailable is False
    assert result.graph_context_reason is None
    assert result.graph_chunk_count == 1
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == allowed_chunk.id
    assert result.chunks[0].document_id == allowed_document.id


@pytest.mark.asyncio
async def test_graph_retrieval_service_falls_back_when_neo4j_unavailable(
    db_session: AsyncSession,
) -> None:
    _ = db_session
    fake_graph_service = _FakeGraphService(available=False)
    service = GraphRetrievalService(graph_service=fake_graph_service)  # type: ignore[arg-type]

    result = await service.expand(
        session=db_session,
        organization_id=uuid4(),
        question='What does "Annual Leave" mean?',
        allowed_document_ids=None,
        graph_enabled=True,
    )

    assert result.graph_context_enabled is True
    assert result.graph_context_used is False
    assert result.graph_context_unavailable is True
    assert result.graph_context_reason == "neo4j_unavailable"
    assert result.chunks == []
