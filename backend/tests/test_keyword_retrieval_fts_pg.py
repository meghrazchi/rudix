"""PostgreSQL full-text search tests for KeywordRetrievalService (R03-01).

SQLite has no ``tsvector``/``ts_rank``; these run only against a migrated PostgreSQL
database (``TEST_DATABASE_URL``) and exercise the persisted ``text_search_vector`` column.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest

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
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  # register all mappers for relationship resolution
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User

pytestmark = pytest.mark.requires_postgres

_service = KeywordRetrievalService()
# A token no other test seeds, so shared-database rows never match these queries.
_TOKEN = f"zyxquartz{uuid4().hex[:10]}"


async def _org(session: AsyncSession) -> tuple[Organization, User]:
    suffix = uuid4().hex
    org = Organization(name=f"FTS {suffix}", slug=f"fts-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"fts-{suffix}",
        email=f"fts-{suffix}@example.com",
        display_name="FTS",
    )
    session.add(user)
    await session.flush()
    return org, user


async def _document(
    session: AsyncSession,
    org: Organization,
    user: User,
    *,
    status: str = DocumentStatus.indexed.value,
) -> Document:
    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename=f"fts-{uuid4().hex[:8]}.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status=status,
    )
    session.add(document)
    await session.flush()
    return document


async def _chunk(
    session: AsyncSession,
    document: Document,
    text: str,
    *,
    chunk_index: int = 0,
    index_version: str = "v1",
) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=chunk_index,
        page_number=1,
        text=text,
        token_count=len(text.split()),
        embedding_model="test-embedding",
        index_version=index_version,
    )
    session.add(chunk)
    await session.flush()
    # text_search_vector is a persisted Computed column filled in by PostgreSQL.
    await session.refresh(chunk)
    return chunk


async def _search(
    session: AsyncSession,
    query: str,
    organization_id: UUID,
    *,
    document_ids: list[UUID] | None = None,
    index_version: str | None = None,
    index_versions: list[str] | None = None,
) -> list[UUID]:
    result = await _service.search_chunks(
        session=session,
        query=query,
        organization_id=organization_id,
        document_ids=document_ids,
        top_k=10,
        index_version=index_version,
        index_versions=index_versions,
    )
    return [candidate.chunk_id for candidate in result.candidates]


async def test_text_search_vector_is_populated(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    document = await _document(pg_session, org, user)
    chunk = await _chunk(pg_session, document, f"{_TOKEN} annual leave policy")

    assert chunk.text_search_vector is not None
    assert _TOKEN in str(chunk.text_search_vector)


async def test_best_lexical_match_ranks_first(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    document = await _document(pg_session, org, user)
    weak = await _chunk(
        pg_session,
        document,
        f"{_TOKEN} appears once in a long passage about parking, lunch and office hours.",
        chunk_index=0,
    )
    strong = await _chunk(
        pg_session,
        document,
        f"{_TOKEN} reimbursement: {_TOKEN} reimbursement claims follow the {_TOKEN} "
        "reimbursement policy.",
        chunk_index=1,
    )
    await _chunk(pg_session, document, "Unrelated text about holidays.", chunk_index=2)

    ids = await _search(pg_session, f"{_TOKEN} reimbursement", org.id)

    assert ids == [strong.id]  # plainto_tsquery ANDs terms; ``weak`` lacks one
    ids = await _search(pg_session, _TOKEN, org.id)
    assert ids[0] == strong.id
    assert set(ids) == {strong.id, weak.id}


async def test_other_organisation_chunks_are_never_returned(pg_session: AsyncSession) -> None:
    org_a, user_a = await _org(pg_session)
    org_b, user_b = await _org(pg_session)
    doc_a = await _document(pg_session, org_a, user_a)
    doc_b = await _document(pg_session, org_b, user_b)
    chunk_a = await _chunk(pg_session, doc_a, f"{_TOKEN} tenant alpha handbook")
    chunk_b = await _chunk(pg_session, doc_b, f"{_TOKEN} tenant beta handbook")

    assert await _search(pg_session, _TOKEN, org_a.id) == [chunk_a.id]
    assert await _search(pg_session, _TOKEN, org_b.id) == [chunk_b.id]
    # Naming another organisation's document does not leak it either.
    assert await _search(pg_session, _TOKEN, org_a.id, document_ids=[doc_b.id]) == []


async def test_non_indexed_documents_are_excluded(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    pending = await _document(pg_session, org, user, status=DocumentStatus.processing.value)
    await _chunk(pg_session, pending, f"{_TOKEN} still processing")

    assert await _search(pg_session, _TOKEN, org.id) == []


async def test_document_ids_filter_is_applied(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    doc_one = await _document(pg_session, org, user)
    doc_two = await _document(pg_session, org, user)
    chunk_one = await _chunk(pg_session, doc_one, f"{_TOKEN} first document")
    chunk_two = await _chunk(pg_session, doc_two, f"{_TOKEN} second document")

    assert await _search(pg_session, _TOKEN, org.id, document_ids=[doc_one.id]) == [chunk_one.id]
    assert await _search(pg_session, _TOKEN, org.id, document_ids=[doc_two.id]) == [chunk_two.id]
    assert await _search(pg_session, _TOKEN, org.id, document_ids=[]) == []


async def test_index_version_filters_are_applied(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    document = await _document(pg_session, org, user)
    live = await _chunk(pg_session, document, f"{_TOKEN} live", index_version="v1")
    evaluation = await _chunk(
        pg_session, document, f"{_TOKEN} eval", chunk_index=1, index_version="eval-fts-1"
    )

    assert await _search(pg_session, _TOKEN, org.id, index_version="v1") == [live.id]
    assert await _search(pg_session, _TOKEN, org.id, index_version="eval-fts-1") == [evaluation.id]
    assert set(await _search(pg_session, _TOKEN, org.id, index_versions=["v1", "eval-fts-1"])) == {
        live.id,
        evaluation.id,
    }
    assert await _search(pg_session, _TOKEN, org.id, index_versions=["v2"]) == []
    # An explicit empty allow-list fails closed.
    assert await _search(pg_session, _TOKEN, org.id, index_versions=[]) == []


async def test_no_lexical_match_returns_empty(pg_session: AsyncSession) -> None:
    org, user = await _org(pg_session)
    document = await _document(pg_session, org, user)
    await _chunk(pg_session, document, f"{_TOKEN} vacation days")

    assert await _search(pg_session, f"nomatch{uuid4().hex[:10]}", org.id) == []
    assert await _search(pg_session, "   ", org.id) == []
