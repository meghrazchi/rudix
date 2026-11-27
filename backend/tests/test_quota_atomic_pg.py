"""R02-07: atomic quota accounting under real PostgreSQL concurrency."""

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

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  # register all mappers for relationship resolution
from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.quota_service import increment_quota_usage
from app.models.organization import Organization
from app.models.quotas import OrgQuotaUsage

pytestmark = pytest.mark.requires_postgres

QT = QuotaType.questions.value


async def _create_org(factory: async_sessionmaker[AsyncSession]) -> UUID:
    suffix = uuid4().hex
    org = Organization(name=f"PG quota {suffix}", slug=f"pg-quota-{suffix}")
    async with factory() as session:
        session.add(org)
        await session.commit()
        return org.id


async def _cleanup(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> None:
    async with factory() as session:
        await session.execute(delete(OrgQuotaUsage).where(OrgQuotaUsage.organization_id == org_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


async def _read_usage(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> OrgQuotaUsage:
    async with factory() as session:
        result = await session.execute(
            select(OrgQuotaUsage).where(
                OrgQuotaUsage.organization_id == org_id,
                OrgQuotaUsage.quota_type == QT,
            )
        )
        return result.scalar_one()


async def test_concurrent_repository_increments_do_not_lose_updates(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _create_org(pg_session_factory)
    try:

        async def one() -> None:
            async with pg_session_factory() as session:
                await QuotaRepository().increment_usage(
                    session, organization_id=org_id, quota_type=QT, amount=1
                )
                await session.commit()

        await asyncio.gather(*(one() for _ in range(50)))

        usage = await _read_usage(pg_session_factory, org_id)
        assert usage.current_value == 50
    finally:
        await _cleanup(pg_session_factory, org_id)


async def test_concurrent_service_increments_do_not_lose_updates(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _create_org(pg_session_factory)
    try:

        async def one() -> None:
            async with pg_session_factory() as session:
                await increment_quota_usage(
                    session, organization_id=org_id, quota_type=QuotaType.questions
                )
                await session.commit()

        await asyncio.gather(*(one() for _ in range(50)))

        usage = await _read_usage(pg_session_factory, org_id)
        assert usage.current_value == 50
    finally:
        await _cleanup(pg_session_factory, org_id)


async def test_concurrent_increments_reset_expired_window_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _create_org(pg_session_factory)
    try:
        async with pg_session_factory() as session:
            session.add(
                OrgQuotaUsage(
                    organization_id=org_id,
                    quota_type=QT,
                    current_value=100,
                    next_reset_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await session.commit()

        async def one() -> None:
            async with pg_session_factory() as session:
                await increment_quota_usage(
                    session, organization_id=org_id, quota_type=QuotaType.questions
                )
                await session.commit()

        await asyncio.gather(*(one() for _ in range(10)))

        usage = await _read_usage(pg_session_factory, org_id)
        assert usage.current_value == 10
        assert usage.next_reset_at is not None
        assert usage.next_reset_at > datetime.now(UTC)
    finally:
        await _cleanup(pg_session_factory, org_id)
