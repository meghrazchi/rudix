"""Async SQLAlchemy engine, session factory, and maintenance sessions (R04-01, R04-08)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, settings
from app.core.db_metrics import TimedAsyncAdaptedQueuePool, install_db_metrics
from app.db.tenant_context import RLS_MAINTENANCE_INFO_KEY, install_sqlalchemy_tenant_guard

install_sqlalchemy_tenant_guard()


def _prepared_statement_name() -> str:
    # PgBouncer transaction pooling can hand a backend to another client between
    # statements; unique names avoid "prepared statement already exists" collisions.
    return f"__asyncpg_{uuid4().hex}__"


def build_connect_args(config: Settings) -> dict[str, Any]:
    """asyncpg connect arguments for the configured pool mode and server timeouts."""
    if config.db_pgbouncer_mode:
        # Startup parameters are ignored by PgBouncer in transaction mode; the timeouts are
        # set per transaction by the session-context statement instead.
        return {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": _prepared_statement_name,
        }
    server_settings: dict[str, str] = {}
    if config.db_statement_timeout_ms > 0:
        server_settings["statement_timeout"] = str(config.db_statement_timeout_ms)
    if config.db_idle_in_transaction_timeout_ms > 0:
        server_settings["idle_in_transaction_session_timeout"] = str(
            config.db_idle_in_transaction_timeout_ms
        )
    return {"server_settings": server_settings} if server_settings else {}


def build_engine_kwargs(config: Settings) -> dict[str, Any]:
    """Keyword arguments for ``create_async_engine`` derived from settings."""
    kwargs: dict[str, Any] = {
        "echo": config.database_echo,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "poolclass": TimedAsyncAdaptedQueuePool,
        "pool_size": config.db_pool_size,
        "max_overflow": config.db_max_overflow,
        "pool_timeout": config.db_pool_timeout_seconds,
    }
    connect_args = build_connect_args(config)
    if connect_args:
        kwargs["connect_args"] = connect_args
    return kwargs


def create_engine_from_settings(url: str, config: Settings = settings) -> AsyncEngine:
    return create_async_engine(url, **build_engine_kwargs(config))


engine = create_engine_from_settings(str(settings.database_url))
install_db_metrics(engine)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

_maintenance_engine: AsyncEngine | None = None
_maintenance_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_maintenance_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory for cross-tenant maintenance; lazily builds its own engine."""
    global _maintenance_engine, _maintenance_session_factory
    if settings.database_maintenance_url is None:
        return SessionLocal
    if _maintenance_session_factory is None:
        _maintenance_engine = create_engine_from_settings(str(settings.database_maintenance_url))
        _maintenance_session_factory = async_sessionmaker(
            bind=_maintenance_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
    return _maintenance_session_factory


@asynccontextmanager
async def maintenance_session() -> AsyncIterator[AsyncSession]:
    """Session for cross-tenant beat tasks.

    Binds to ``DATABASE_MAINTENANCE_URL`` (a ``BYPASSRLS`` role) when set, else to the
    application engine. It never binds a tenant and is excluded from soft-mode counting.
    """
    factory = _get_maintenance_session_factory()
    async with factory() as session:
        session.info[RLS_MAINTENANCE_INFO_KEY] = True
        yield session


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    """Close pooled connections of the application and maintenance engines."""
    global _maintenance_engine, _maintenance_session_factory
    await engine.dispose()
    if _maintenance_engine is not None:
        await _maintenance_engine.dispose()
        _maintenance_engine = None
        _maintenance_session_factory = None


async def check_database_health() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
