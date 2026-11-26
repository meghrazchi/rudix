import os
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
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

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_BACKEND_SQLITE = "sqlite"
DB_BACKEND_POSTGRES = "postgres"
_MIGRATION_ERROR_TAIL_CHARS = 4000


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "both_dialects: run db_session tests on SQLite and, when TEST_DATABASE_URL is set, "
        "on a migrated PostgreSQL database",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``both_dialects`` tests that use ``db_session`` over both backends.

    Tests in a ``both_dialects`` module that do not use ``db_session`` are left alone, so
    pure-function tests are not collected twice.
    """
    if metafunc.definition.get_closest_marker("both_dialects") is None:
        return
    if "db_session" not in metafunc.fixturenames:
        return
    metafunc.parametrize(
        "db_backend",
        [
            DB_BACKEND_SQLITE,
            pytest.param(DB_BACKEND_POSTGRES, marks=pytest.mark.requires_postgres),
        ],
        indirect=True,
    )


@pytest.fixture
def db_backend(request: pytest.FixtureRequest) -> str:
    return str(getattr(request, "param", DB_BACKEND_SQLITE))


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_: JSONB, compiler: object, **kwargs: object) -> str:
    return "JSON"


@compiles(TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_: TSVECTOR, compiler: object, **kwargs: object) -> str:
    return "TEXT"


def _register_sqlite_functions(dbapi_connection: object, _: object = None) -> None:
    """Register the PostgreSQL functions the models use (``to_tsvector``) on SQLite."""
    create_function = getattr(dbapi_connection, "create_function", None)
    if create_function is None:
        return
    create_function(
        "to_tsvector",
        2,
        lambda _lang, text: text or "",
        deterministic=True,
    )


def _configure_sqlite_connection(dbapi_connection: object, _: object = None) -> None:
    """Per-test SQLite file: register functions and skip fsync (the file is thrown away)."""
    _register_sqlite_functions(dbapi_connection)
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA journal_mode=MEMORY")
    finally:
        cursor.close()


def build_sqlite_template(path: Path) -> Path:
    """Create every table once in a SQLite file at ``path`` (same compile shims as tests)."""
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    event.listen(engine, "connect", _configure_sqlite_connection)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return path


@pytest.fixture(scope="session")
def sqlite_template_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schema template built once per session; ``db_session`` copies it for each test."""
    return build_sqlite_template(tmp_path_factory.mktemp("sqlite-template") / "template.db")


def get_test_client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest_asyncio.fixture
async def db_session(
    request: pytest.FixtureRequest, db_backend: str
) -> AsyncIterator[AsyncSession]:
    """Fresh per-test SQLite session, or a rolled-back PostgreSQL session for ``both_dialects``.

    ``db_backend`` is ``"sqlite"`` unless ``pytest_generate_tests`` parametrized it.
    """
    if db_backend == DB_BACKEND_POSTGRES:
        # ``pg_engine`` is async and cannot be requested from inside this running fixture,
        # so resolve the sync migration fixture and build the engine the same way.
        pg_url: str = request.getfixturevalue("pg_migrated_url")
        async with _checked_pg_engine(pg_url) as pg_engine_:
            async with _rolled_back_pg_session(pg_engine_) as pg_session_:
                yield pg_session_
        return

    # Copy the session-wide schema template instead of running ``create_all`` per test.
    # Every test still gets its own fresh database file, so isolation is unchanged.
    template: Path = request.getfixturevalue("sqlite_template_db")
    tmp_dir: Path = request.getfixturevalue("tmp_path_factory").mktemp("db", numbered=True)
    db_file = tmp_dir / "test.db"
    shutil.copyfile(template, db_file)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        poolclass=StaticPool,
    )
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
        db_file.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-backed tests")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// driver")
    return url


@pytest.fixture(scope="session")
def pg_migrated_url(pg_database_url: str) -> str:
    """Run ``alembic upgrade head`` against TEST_DATABASE_URL once per test session.

    ``alembic/env.py`` reads ``settings.database_url`` and calls ``asyncio.run``, so it
    cannot run inside the test event loop; it runs in a subprocess instead.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": pg_database_url},
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-_MIGRATION_ERROR_TAIL_CHARS:]
        pytest.fail(
            f"alembic upgrade head failed against TEST_DATABASE_URL "
            f"(exit {result.returncode}):\n{tail}"
        )
    return pg_database_url


@asynccontextmanager
async def _checked_pg_engine(url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT version_num FROM alembic_version"))
        except Exception:
            pytest.fail(
                "PostgreSQL at TEST_DATABASE_URL has no alembic_version table after "
                "`alembic upgrade head`"
            )
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_engine(pg_migrated_url: str) -> AsyncIterator[AsyncEngine]:
    async with _checked_pg_engine(pg_migrated_url) as engine:
        yield engine


@asynccontextmanager
async def _rolled_back_pg_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
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
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session bound to an outer transaction that is rolled back at teardown.

    Code under test may call ``commit()``; the commit releases a savepoint and everything
    is rolled back at teardown, so nothing persists between tests.
    """
    async with _rolled_back_pg_session(pg_engine) as session:
        yield session


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory for concurrency tests.

    Each session uses its own real connection and commits are real. Tests must delete
    the rows they create, scoped by a unique organization ID.
    """
    return async_sessionmaker(bind=pg_engine, class_=AsyncSession, expire_on_commit=False)
