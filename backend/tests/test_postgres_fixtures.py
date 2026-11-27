import os
from uuid import uuid4

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

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  # register all mappers for relationship resolution
from app.models.organization import Organization

pytestmark = pytest.mark.requires_postgres


def _new_org() -> Organization:
    suffix = uuid4().hex
    return Organization(name=f"PG fixture {suffix}", slug=f"pg-fixture-{suffix}")


async def test_pg_session_runs_on_migrated_schema(pg_session: AsyncSession) -> None:
    rows = (await pg_session.execute(text("SELECT version_num FROM alembic_version"))).all()

    assert len(rows) == 1
    assert rows[0][0]


async def test_pg_session_commit_does_not_escape_test_transaction(
    pg_session: AsyncSession,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org = _new_org()
    pg_session.add(org)
    await pg_session.commit()

    assert await pg_session.get(Organization, org.id) is not None
    async with pg_session_factory() as other:
        assert await other.get(Organization, org.id) is None


async def test_pg_session_factory_uses_distinct_committed_connections(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org = _new_org()
    async with pg_session_factory() as writer, pg_session_factory() as reader:
        try:
            writer_pid = (await writer.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            reader_pid = (await reader.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            assert writer_pid != reader_pid

            writer.add(org)
            await writer.commit()

            await reader.rollback()  # start a fresh snapshot after the writer's commit
            assert await reader.get(Organization, org.id) is not None
        finally:
            await reader.rollback()
            await writer.execute(delete(Organization).where(Organization.id == org.id))
            await writer.commit()
