from __future__ import annotations

import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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

from app.db.base import Base
from app.db.tenant_context import (
    TenantIsolationError,
    bind_session_tenant,
    get_current_tenant_id,
    set_postgres_tenant_context,
    tenant_scoped_session,
)
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_scoped_session_filters_unscoped_select_queries(
    sqlite_session: AsyncSession,
) -> None:
    org_a = uuid4()
    org_b = uuid4()
    user_id = uuid4()

    sqlite_session.add_all(
        [
            Organization(id=org_a, name="Org A", slug=f"org-a-{org_a.hex[:6]}"),
            Organization(id=org_b, name="Org B", slug=f"org-b-{org_b.hex[:6]}"),
            User(id=user_id, email="u@example.com", display_name="User"),
        ]
    )
    await sqlite_session.flush()

    doc_a = Document(
        id=uuid4(),
        organization_id=org_a,
        uploaded_by_user_id=user_id,
        filename="a.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"{org_a}/a.pdf",
        status=DocumentStatus.indexed.value,
    )
    doc_b = Document(
        id=uuid4(),
        organization_id=org_b,
        uploaded_by_user_id=user_id,
        filename="b.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"{org_b}/b.pdf",
        status=DocumentStatus.indexed.value,
    )
    sqlite_session.add_all([doc_a, doc_b])
    await sqlite_session.commit()

    # Inside tenant_scoped_session for Org A, an unscoped SELECT(Document)
    # must only return Org A's document.
    with tenant_scoped_session(sqlite_session, org_a):
        assert get_current_tenant_id() == org_a
        docs = (await sqlite_session.execute(select(Document))).scalars().all()
        assert [d.id for d in docs] == [doc_a.id]

        # Exempt identity models (Organization) remain queryable across orgs
        orgs = (await sqlite_session.execute(select(Organization))).scalars().all()
        assert len(orgs) == 2

        # Explicit bypass option allows system queries across tenants when needed
        all_docs = (
            (
                await sqlite_session.execute(
                    select(Document).execution_options(bypass_tenant_guard=True)
                )
            )
            .scalars()
            .all()
        )
        assert len(all_docs) == 2


@pytest.mark.asyncio
async def test_tenant_scoped_session_blocks_cross_tenant_write(
    sqlite_session: AsyncSession,
) -> None:
    org_a = uuid4()
    org_b = uuid4()
    user_id = uuid4()

    sqlite_session.add_all(
        [
            Organization(id=org_a, name="Org A", slug=f"org-a-{org_a.hex[:6]}"),
            Organization(id=org_b, name="Org B", slug=f"org-b-{org_b.hex[:6]}"),
            User(id=user_id, email="u2@example.com", display_name="User 2"),
        ]
    )
    await sqlite_session.commit()

    with tenant_scoped_session(sqlite_session, org_a):
        cross_tenant_doc = Document(
            id=uuid4(),
            organization_id=org_b,
            uploaded_by_user_id=user_id,
            filename="leak.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"{org_b}/leak.pdf",
            status=DocumentStatus.indexed.value,
        )
        sqlite_session.add(cross_tenant_doc)
        with pytest.raises(TenantIsolationError, match="Cross-tenant write blocked"):
            await sqlite_session.flush()
    await sqlite_session.rollback()


@pytest.mark.asyncio
async def test_bind_session_tenant_and_set_postgres_tenant_context() -> None:
    mock_session = AsyncMock()
    mock_session.info = {}
    org_id = uuid4()

    bound = bind_session_tenant(mock_session, str(org_id))
    assert bound == org_id
    assert mock_session.info["organization_id"] == org_id

    await set_postgres_tenant_context(mock_session, org_id)
    mock_session.execute.assert_awaited_once()
    call_args = mock_session.execute.call_args
    assert "set_config('app.current_organization_id'" in str(call_args.args[0])
    assert call_args.args[1] == {"org_id": str(org_id)}

    with pytest.raises(ValueError, match="Valid organization_id UUID is required"):
        await set_postgres_tenant_context(mock_session, "not-a-uuid")


def test_rls_sql_builders_and_identifier_validation() -> None:
    from app.db.rls import (
        TENANT_RLS_POLICY_NAME,
        TENANT_RLS_TABLES,
        build_disable_rls_sql,
        build_enable_rls_sql,
    )

    assert "documents" in TENANT_RLS_TABLES
    assert "collections" in TENANT_RLS_TABLES

    enable_sql, drop_sql, create_sql = build_enable_rls_sql("documents")
    assert enable_sql == "ALTER TABLE documents ENABLE ROW LEVEL SECURITY"
    assert drop_sql == f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON documents"
    assert "current_setting('app.current_organization_id', true)" in create_sql
    assert "WITH CHECK" in create_sql

    drop_policy_sql, disable_sql = build_disable_rls_sql("documents")
    assert drop_policy_sql == f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON documents"
    assert disable_sql == "ALTER TABLE documents DISABLE ROW LEVEL SECURITY"

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        build_enable_rls_sql("documents; DROP TABLE users")
