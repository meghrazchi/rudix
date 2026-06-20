import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

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
