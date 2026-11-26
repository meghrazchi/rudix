import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool, StaticPool

from app.db.base import Base


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_: JSONB, compiler: object, **kwargs: object) -> str:
    return "JSON"


@compiles(TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_: TSVECTOR, compiler: object, **kwargs: object) -> str:
    return "TEXT"


def get_test_client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_sqlite_functions(dbapi_connection: object, _: object) -> None:
        create_function = getattr(dbapi_connection, "create_function", None)
        if create_function is None:
            return
        create_function(
            "to_tsvector",
            2,
            lambda _lang, text: text or "",
            deterministic=True,
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-backed tests")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// driver")
    return url


@pytest_asyncio.fixture
async def pg_engine(pg_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_database_url, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT version_num FROM alembic_version"))
        except Exception:
            pytest.fail(
                "PostgreSQL at TEST_DATABASE_URL is not migrated; run `alembic upgrade head` "
                "against it first (make test-postgres does this)"
            )
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session bound to an outer transaction that is rolled back at teardown.

    Code under test may call ``commit()``; the commit releases a savepoint and everything
    is rolled back at teardown, so nothing persists between tests.
    """
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if trans.is_active:
                await trans.rollback()


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory for concurrency tests.

    Each session uses its own real connection and commits are real. Tests must delete
    the rows they create, scoped by a unique organization ID.
    """
    return async_sessionmaker(bind=pg_engine, class_=AsyncSession, expire_on_commit=False)
