"""R02-06: hybrid retrieval with three sub-queries on real PostgreSQL has no branch failures."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest

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

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  # register all mappers
from app.core.config import settings
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalResult
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.chat.services.parallel_retrieval_optimizer import (
    ParallelRetrievalBudget,
    ParallelRetrievalOptimizer,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document, DocumentChunk
from app.models.organization import Organization
from app.models.user import User

pytestmark = pytest.mark.requires_postgres


class _Query:
    embedding_model = "test-embedding"

    async def embed_query(self, *, question: str) -> tuple[list[float], int]:
        return [0.0] * 3, 1

    def retrieve_candidates(self, **kwargs: Any) -> list[Any]:
        return []


class _Graph:
    async def expand(self, **kwargs: Any) -> GraphRetrievalResult:
        return GraphRetrievalResult(
            graph_context_enabled=False, graph_context_used=False, graph_context_reason="disabled"
        )


async def test_three_subqueries_run_keyword_search_without_branch_failures(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    suffix = uuid4().hex
    texts = ["alpha budget policy", "beta travel policy", "gamma leave policy"]
    org_id = None
    user_id = None
    document_id = None
    chunk_ids: list[Any] = []
    try:
        async with pg_session_factory() as seed:
            org = Organization(name=f"R02-06 {suffix}", slug=f"r02-06-{suffix}")
            seed.add(org)
            await seed.flush()
            org_id = org.id
            user = User(
                organization_id=org.id,
                external_auth_id=f"r02-06-{suffix}",
                email=f"r02-06-{suffix}@example.com",
                display_name="R02-06 test user",
            )
            seed.add(user)
            await seed.flush()
            user_id = user.id
            repo = DocumentRepository()
            document = await repo.create_document(
                seed,
                organization_id=org.id,
                uploaded_by_user_id=user_id,
                filename=f"policy-{suffix}.txt",
                file_type="txt",
                storage_bucket="documents",
                storage_object_key=f"r02-06/{suffix}.txt",
                status="indexed",
            )
            document_id = document.id
            for index, text in enumerate(texts):
                chunk = await repo.create_document_chunk(
                    seed,
                    document_id=document.id,
                    chunk_index=index,
                    text=text,
                    token_count=5,
                    embedding_model=settings.openai_embedding_model,
                    index_version=settings.document_index_version,
                    qdrant_point_id=f"{suffix}:{index}",
                )
                chunk_ids.append(chunk.id)
            await seed.commit()

        optimizer = ParallelRetrievalOptimizer(session_factory=pg_session_factory)
        async with pg_session_factory() as caller:
            result = await optimizer.execute(
                session=caller,
                organization_id=org_id,
                document_ids=None,
                queries=["alpha", "beta", "gamma"],
                query_retrieval_service=_Query(),  # type: ignore[arg-type]
                keyword_retrieval_service=KeywordRetrievalService(),
                graph_retrieval_service=_Graph(),  # type: ignore[arg-type]
                graph_enabled=False,
                keyword_enabled=True,
                qdrant_client=None,
                top_k=5,
                exact_match_boost=1.5,
                budget=ParallelRetrievalBudget(
                    max_parallel_calls=4, timeout_ms=5000, max_retry_attempts=0
                ),
            )

        keyword_records = [r for r in result.branch_records if r.branch_name == "keyword_search"]
        assert len(keyword_records) == 3
        assert all(r.succeeded for r in keyword_records)
        for record in result.query_records:
            assert record.keyword_candidates is not None
            assert record.keyword_candidates.candidates
    finally:
        async with pg_session_factory() as cleanup:
            if chunk_ids:
                await cleanup.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
            if document_id is not None:
                await cleanup.execute(delete(Document).where(Document.id == document_id))
            if user_id is not None:
                await cleanup.execute(delete(User).where(User.id == user_id))
            if org_id is not None:
                await cleanup.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup.commit()
