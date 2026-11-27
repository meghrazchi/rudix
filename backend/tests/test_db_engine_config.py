"""Engine, pool, and maintenance-session configuration (R04-01)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core import db_metrics, lifespan
from app.core.config import Settings, settings
from app.core.db_metrics import TimedAsyncAdaptedQueuePool
from app.db import session as db_session_module
from app.db.session import (
    build_connect_args,
    build_engine_kwargs,
    create_engine_from_settings,
    dispose_engine,
    maintenance_session,
)
from app.db.tenant_context import RLS_MAINTENANCE_INFO_KEY


def _config(**updates: Any) -> Settings:
    return settings.model_copy(update=updates)


def _sample(name: str) -> float:
    value = db_metrics.registry.get_sample_value(name)
    return float(value or 0.0)


def test_engine_kwargs_default_to_previous_behaviour() -> None:
    kwargs = build_engine_kwargs(
        _config(
            db_pool_size=5,
            db_max_overflow=10,
            db_pool_timeout_seconds=30.0,
            db_statement_timeout_ms=0,
            db_idle_in_transaction_timeout_ms=0,
            db_pgbouncer_mode=False,
        )
    )
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_timeout"] == 30.0
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["poolclass"] is TimedAsyncAdaptedQueuePool
    assert "connect_args" not in kwargs


def test_engine_kwargs_follow_settings() -> None:
    kwargs = build_engine_kwargs(
        _config(
            db_pool_size=3,
            db_max_overflow=0,
            db_pool_timeout_seconds=2.5,
            db_statement_timeout_ms=30000,
            db_idle_in_transaction_timeout_ms=60000,
            db_pgbouncer_mode=False,
        )
    )
    assert (kwargs["pool_size"], kwargs["max_overflow"], kwargs["pool_timeout"]) == (3, 0, 2.5)
    assert kwargs["connect_args"] == {
        "server_settings": {
            "statement_timeout": "30000",
            "idle_in_transaction_session_timeout": "60000",
        }
    }


def test_only_statement_timeout_sets_one_server_setting() -> None:
    connect_args = build_connect_args(
        _config(db_statement_timeout_ms=500, db_idle_in_transaction_timeout_ms=0)
    )
    assert connect_args == {"server_settings": {"statement_timeout": "500"}}


def test_pgbouncer_mode_disables_prepared_statement_caches() -> None:
    connect_args = build_connect_args(
        _config(db_pgbouncer_mode=True, db_statement_timeout_ms=30000)
    )
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    assert "server_settings" not in connect_args  # timeouts move into each transaction
    name_func = connect_args["prepared_statement_name_func"]
    names = {name_func() for _ in range(50)}
    assert len(names) == 50
    assert all(name.startswith("__asyncpg_") for name in names)


def test_settings_read_spec_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "4.5")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "1000")
    monkeypatch.setenv("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS", "2000")
    monkeypatch.setenv("DB_PGBOUNCER_MODE", "true")
    monkeypatch.setenv("DATABASE_MAINTENANCE_URL", "postgresql+asyncpg://m:m@db:5432/rudix")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+asyncpg://o:o@db:5432/rudix")
    loaded = Settings()
    assert loaded.db_pool_size == 7
    assert loaded.db_max_overflow == 0
    assert loaded.db_pool_timeout_seconds == 4.5
    assert loaded.db_statement_timeout_ms == 1000
    assert loaded.db_idle_in_transaction_timeout_ms == 2000
    assert loaded.db_pgbouncer_mode is True
    assert str(loaded.database_maintenance_url).startswith("postgresql+asyncpg://m:m@db")
    assert str(loaded.database_migration_url).startswith("postgresql+asyncpg://o:o@db")


def test_settings_reject_invalid_pool_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    with pytest.raises(ValueError):
        Settings()


def test_application_engine_uses_timed_pool() -> None:
    pool = db_session_module.engine.sync_engine.pool
    assert isinstance(pool, TimedAsyncAdaptedQueuePool)
    assert pool.size() == settings.db_pool_size


async def test_dispose_engine_closes_application_and_maintenance_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_engine = MagicMock(spec=AsyncEngine)
    app_engine.dispose = AsyncMock()
    maintenance_engine = MagicMock(spec=AsyncEngine)
    maintenance_engine.dispose = AsyncMock()
    monkeypatch.setattr(db_session_module, "engine", app_engine)
    monkeypatch.setattr(db_session_module, "_maintenance_engine", maintenance_engine)
    monkeypatch.setattr(db_session_module, "_maintenance_session_factory", object())

    await dispose_engine()

    app_engine.dispose.assert_awaited_once()
    maintenance_engine.dispose.assert_awaited_once()
    assert db_session_module._maintenance_engine is None
    assert db_session_module._maintenance_session_factory is None


async def test_lifespan_disposes_engine_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("init_sentry", "init_langfuse", "init_rabbitmq", "init_qdrant", "init_minio"):
        monkeypatch.setattr(lifespan, name, MagicMock())
    for name in ("init_clamav", "close_rabbitmq", "close_qdrant", "close_minio", "close_clamav"):
        monkeypatch.setattr(lifespan, name, MagicMock())
    monkeypatch.setattr(lifespan, "shutdown_langfuse", MagicMock())
    for name in (
        "init_redis",
        "init_neo4j",
        "run_graph_migrations",
        "probe_local_providers",
        "close_redis",
        "close_neo4j",
    ):
        monkeypatch.setattr(lifespan, name, AsyncMock())
    dispose = AsyncMock()
    monkeypatch.setattr(lifespan, "dispose_engine", dispose)

    async with lifespan.lifespan(FastAPI()):
        dispose.assert_not_awaited()
    dispose.assert_awaited_once()


async def test_maintenance_session_without_url_uses_application_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_maintenance_url", None)
    async with maintenance_session() as session:
        assert session.info[RLS_MAINTENANCE_INFO_KEY] is True
        assert session.bind is db_session_module.engine
    assert db_session_module._maintenance_engine is None


async def test_maintenance_session_with_url_uses_its_own_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maintenance_url = Settings.model_fields["database_maintenance_url"]
    assert maintenance_url.default is None
    monkeypatch.setattr(
        settings,
        "database_maintenance_url",
        "postgresql+asyncpg://maint:maint@127.0.0.1:1/rudix",
    )
    monkeypatch.setattr(db_session_module, "_maintenance_engine", None)
    monkeypatch.setattr(db_session_module, "_maintenance_session_factory", None)
    try:
        async with maintenance_session() as session:
            assert session.info[RLS_MAINTENANCE_INFO_KEY] is True
            bind = session.bind
            assert isinstance(bind, AsyncEngine)
            assert bind is not db_session_module.engine
            assert bind.url.username == "maint"
        first_engine = db_session_module._maintenance_engine
        async with maintenance_session() as session:
            assert session.bind is first_engine  # created once, lazily
    finally:
        if db_session_module._maintenance_engine is not None:
            await db_session_module._maintenance_engine.dispose()


async def _assert_pool_timeout_counted(engine: AsyncEngine) -> None:
    timeouts_before = _sample("rudix_db_pool_timeouts_total")
    waits_before = _sample("rudix_db_pool_wait_seconds_count")
    held = await engine.connect()
    try:
        await held.execute(text("SELECT 1"))
        with pytest.raises(exc.TimeoutError):
            async with engine.connect() as second:
                await second.execute(text("SELECT 1"))
    finally:
        await held.close()
    assert _sample("rudix_db_pool_timeouts_total") == timeouts_before + 1
    # The successful checkout and the timed-out one are both observed.
    assert _sample("rudix_db_pool_wait_seconds_count") >= waits_before + 2
    async with engine.connect() as again:  # the pool recovers once the connection is back
        await again.execute(text("SELECT 1"))


async def test_pool_timeout_counter_increments_sqlite(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}",
        poolclass=TimedAsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    try:
        await _assert_pool_timeout_counted(engine)
    finally:
        await engine.dispose()


@pytest.mark.requires_postgres
async def test_pool_timeout_counter_increments_postgres(pg_migrated_url: str) -> None:
    engine = create_engine_from_settings(
        pg_migrated_url,
        _config(db_pool_size=1, db_max_overflow=0, db_pool_timeout_seconds=0.1),
    )
    try:
        await _assert_pool_timeout_counted(engine)
    finally:
        await engine.dispose()


@pytest.mark.requires_postgres
async def test_server_timeouts_reach_postgres(pg_migrated_url: str) -> None:
    engine = create_engine_from_settings(
        pg_migrated_url,
        _config(db_statement_timeout_ms=1234, db_idle_in_transaction_timeout_ms=5678),
    )
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SHOW statement_timeout"))).scalar() == "1234ms"
            idle = (await conn.execute(text("SHOW idle_in_transaction_session_timeout"))).scalar()
            assert idle == "5678ms"
    finally:
        await engine.dispose()


@pytest.mark.requires_postgres
async def test_pgbouncer_connect_args_work_against_postgres(pg_migrated_url: str) -> None:
    engine = create_engine_from_settings(
        pg_migrated_url, _config(db_pgbouncer_mode=True, db_statement_timeout_ms=1234)
    )
    try:
        async with engine.connect() as conn:
            for value in range(3):
                result = await conn.execute(text("SELECT CAST(:v AS int)"), {"v": value})
                assert result.scalar() == value
            # No startup parameter in PgBouncer mode: the server default is unchanged.
            assert (await conn.execute(text("SHOW statement_timeout"))).scalar() == "0"
    finally:
        await engine.dispose()
