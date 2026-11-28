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

from app.application.realtime.publisher import install_realtime_listeners
from app.core.cache_invalidation import install_cache_invalidation_listeners
from app.core.config import Settings, settings
from app.core.db_metrics import (
    TimedAsyncAdaptedQueuePool,
    install_db_metrics,
    install_query_counter,
)
from app.db.tenant_context import RLS_MAINTENANCE_INFO_KEY, install_sqlalchemy_tenant_guard

install_sqlalchemy_tenant_guard()
install_cache_invalidation_listeners()
install_realtime_listeners()


def _prepared_statement_name() -> str:
    # PgBouncer transaction pooling can hand a backend to another client between
    # statements; unique names avoid "prepared statement already exists" collisions.
    return f"__asyncpg_{uuid4().hex}__"


def build_connect_args(config: Settings, *, read_only: bool = False) -> dict[str, Any]:
    """asyncpg connect arguments for the configured pool mode and server timeouts.

    ``read_only`` (the reporting replica engine, R08-04) makes every transaction read-only
    through ``default_transaction_read_only``. PgBouncer ignores startup parameters, so in
    that mode the replica session runs ``SET TRANSACTION READ ONLY`` instead (``replica.py``).
    """
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
    if read_only:
        server_settings["default_transaction_read_only"] = "on"
    return {"server_settings": server_settings} if server_settings else {}


def build_engine_kwargs(
    config: Settings,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    read_only: bool = False,
) -> dict[str, Any]:
    """Keyword arguments for ``create_async_engine`` derived from settings."""
    kwargs: dict[str, Any] = {
        "echo": config.database_echo,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "poolclass": TimedAsyncAdaptedQueuePool,
        "pool_size": config.db_pool_size if pool_size is None else pool_size,
        "max_overflow": config.db_max_overflow if max_overflow is None else max_overflow,
        "pool_timeout": config.db_pool_timeout_seconds,
    }
    connect_args = build_connect_args(config, read_only=read_only)
    if connect_args:
        kwargs["connect_args"] = connect_args
    return kwargs


def create_engine_from_settings(
    url: str,
    config: Settings = settings,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    read_only: bool = False,
) -> AsyncEngine:
    return create_async_engine(
        url,
        **build_engine_kwargs(
            config, pool_size=pool_size, max_overflow=max_overflow, read_only=read_only
        ),
    )


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
    """Close pooled connections of the application, maintenance, and replica engines."""
    global _maintenance_engine, _maintenance_session_factory
    await engine.dispose()
    if _maintenance_engine is not None:
        await _maintenance_engine.dispose()
        _maintenance_engine = None
        _maintenance_session_factory = None
    await dispose_reporting_engine()


# --- Reporting read replica (0.8.0, R08-04) --------------------------------------------

READ_ONLY_TRANSACTION_INFO_KEY = "read_only_transaction"

_reporting_engine: AsyncEngine | None = None
_reporting_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_reporting_engine() -> AsyncEngine | None:
    """The read-only replica engine, built on first use; None when no replica is set."""
    global _reporting_engine, _reporting_session_factory
    if settings.database_replica_url is None:
        return None
    if _reporting_engine is None:
        _reporting_engine = create_engine_from_settings(
            str(settings.database_replica_url),
            pool_size=settings.db_replica_pool_size,
            max_overflow=settings.db_replica_max_overflow,
            read_only=True,
        )
        install_query_counter(_reporting_engine)
        # Without PgBouncer the connection default makes transactions read-only; with it,
        # the after_begin listener in ``replica.py`` runs SET TRANSACTION READ ONLY.
        info = {READ_ONLY_TRANSACTION_INFO_KEY: True} if settings.db_pgbouncer_mode else {}
        _reporting_session_factory = async_sessionmaker(
            bind=_reporting_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
            info=info,
        )
    return _reporting_engine


class _ReportingSessionFactory:
    """``ReportingSessionLocal()`` opens a read-only session on the replica engine."""

    def __call__(self) -> AsyncSession:
        if get_reporting_engine() is None or _reporting_session_factory is None:
            raise RuntimeError("DATABASE_REPLICA_URL is not set")
        return _reporting_session_factory()


ReportingSessionLocal = _ReportingSessionFactory()


async def dispose_reporting_engine() -> None:
    global _reporting_engine, _reporting_session_factory
    if _reporting_engine is not None:
        await _reporting_engine.dispose()
        _reporting_engine = None
        _reporting_session_factory = None


async def check_database_health() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
