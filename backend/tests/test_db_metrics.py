"""Tests for DB pool and per-request query metrics (R03-09)."""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from app.core import db_metrics
from app.core.config import settings
from app.core.db_metrics import (
    DbPoolCollector,
    begin_request_query_count,
    current_query_counter,
    end_request_query_count,
    install_pool_collector,
    install_query_counter,
    remove_query_counter,
)
from app.core.metrics import attach_metrics_middleware, registry

ROUTE = "/load-probe/{n}"


def _hist(suffix: str, route: str = ROUTE, method: str = "GET") -> float:
    value = registry.get_sample_value(
        f"rudix_db_queries_per_request_{suffix}", {"method": method, "route": route}
    )
    return float(value or 0.0)


@pytest.fixture
async def probe_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    install_query_counter(engine)
    yield engine
    remove_query_counter(engine)
    await engine.dispose()


def _build_app(engine: AsyncEngine) -> FastAPI:
    app = FastAPI()
    attach_metrics_middleware(app)

    async def _one() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    @app.get(ROUTE)
    async def probe(n: int) -> dict[str, Any]:
        counter_seen = current_query_counter() is not None
        # Half the statements run sequentially, the rest in gathered tasks, so the
        # test proves child tasks share the request's counter.
        sequential = n // 2
        for _ in range(sequential):
            await _one()
        await asyncio.gather(*(_one() for _ in range(n - sequential)))
        return {"counter_seen": counter_seen}

    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.fixture
def metrics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_db_query_counting_enabled", True)


@pytest.mark.parametrize("n", [1, 4, 7])
async def test_request_records_exact_query_count(
    probe_engine: AsyncEngine, metrics_on: None, n: int
) -> None:
    app = _build_app(probe_engine)
    count_before = _hist("count")
    sum_before = _hist("sum")

    response = await _get(app, f"/load-probe/{n}")

    assert response.status_code == 200
    assert response.json() == {"counter_seen": True}
    assert _hist("count") == count_before + 1
    assert _hist("sum") == sum_before + n


async def test_queries_outside_a_request_are_not_counted(
    probe_engine: AsyncEngine, metrics_on: None
) -> None:
    assert current_query_counter() is None
    sum_before = _hist("sum")
    count_before = _hist("count")

    async with probe_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.execute(text("SELECT 2"))

    assert current_query_counter() is None
    assert _hist("sum") == sum_before
    assert _hist("count") == count_before


async def test_counter_is_cleared_after_request(
    probe_engine: AsyncEngine, metrics_on: None
) -> None:
    app = _build_app(probe_engine)
    await _get(app, "/load-probe/2")
    assert current_query_counter() is None


async def test_disabled_setting_has_no_listener_effect(
    probe_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_db_query_counting_enabled", False)
    app = _build_app(probe_engine)
    count_before = _hist("count")
    sum_before = _hist("sum")

    response = await _get(app, "/load-probe/3")

    assert response.status_code == 200
    assert response.json() == {"counter_seen": False}
    assert _hist("count") == count_before
    assert _hist("sum") == sum_before


async def test_metrics_disabled_skips_query_counting(
    probe_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    monkeypatch.setattr(settings, "metrics_db_query_counting_enabled", True)
    assert begin_request_query_count() is None
    count_before = _hist("count")

    response = await _get(_build_app(probe_engine), "/load-probe/2")

    assert response.json() == {"counter_seen": False}
    assert _hist("count") == count_before


def test_end_with_none_scope_is_noop() -> None:
    count_before = _hist("count", route="/noop")
    end_request_query_count(None, "GET", "/noop")
    assert _hist("count", route="/noop") == count_before


def test_end_from_foreign_context_clears_counter(metrics_on: None) -> None:
    scope = contextvars.copy_context().run(begin_request_query_count)
    assert scope is not None
    scope.counter.count = 3
    sum_before = _hist("sum", route="/foreign")

    end_request_query_count(scope, "GET", "/foreign")

    assert current_query_counter() is None
    assert _hist("sum", route="/foreign") == sum_before + 3


def test_install_query_counter_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    install_query_counter(engine)
    install_query_counter(engine)
    assert event.contains(engine, "before_cursor_execute", db_metrics._count_statement)
    remove_query_counter(engine)
    remove_query_counter(engine)
    assert not event.contains(engine, "before_cursor_execute", db_metrics._count_statement)
    engine.dispose()


def test_application_engine_has_db_metrics_installed() -> None:
    from app.db.session import engine

    assert event.contains(engine.sync_engine, "before_cursor_execute", db_metrics._count_statement)
    assert db_metrics._pool_collector is not None


def _samples(collector: DbPoolCollector) -> dict[str, float]:
    out: dict[str, float] = {}
    for family in collector.collect():
        for sample in family.samples:
            out[sample.name] = sample.value
    return out


@pytest.mark.parametrize("poolclass", [StaticPool, NullPool])
def test_pool_collector_does_not_raise_on_pools_without_stats(poolclass: Any) -> None:
    engine = create_engine("sqlite://", poolclass=poolclass)
    collector = DbPoolCollector(lambda: engine.pool)

    families = list(collector.collect())

    assert [f.name for f in families] == [
        "rudix_db_pool_checked_out",
        "rudix_db_pool_size",
        "rudix_db_pool_overflow",
    ]
    assert all(not f.samples for f in families)
    assert [m.name for m in collector.describe()] == [f.name for f in families]
    engine.dispose()


def test_pool_collector_reads_queue_pool(tmp_path: Any) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool, pool_size=3, max_overflow=2
    )
    collector = DbPoolCollector(lambda: engine.pool)
    with engine.connect():
        samples = _samples(collector)
    assert samples["rudix_db_pool_checked_out"] == 1.0
    assert samples["rudix_db_pool_size"] == 3.0
    assert "rudix_db_pool_overflow" in samples
    assert _samples(collector)["rudix_db_pool_checked_out"] == 0.0
    engine.dispose()


def test_pool_collector_tolerates_failing_getter_and_reader() -> None:
    def _boom() -> Any:
        raise RuntimeError("no pool")

    assert _samples(DbPoolCollector(_boom)) == {}

    class _BrokenPool:
        def size(self) -> int:
            raise RuntimeError("broken")

    assert _samples(DbPoolCollector(lambda: _BrokenPool())) == {}


def test_install_pool_collector_retargets_registered_collector(tmp_path: Any) -> None:
    from app.db.session import engine as app_engine

    other = create_engine(f"sqlite:///{tmp_path / 'other.db'}", poolclass=QueuePool, pool_size=4)
    try:
        collector = install_pool_collector(other)
        assert collector is db_metrics._pool_collector
        assert registry.get_sample_value("rudix_db_pool_size") == 4.0
    finally:
        install_pool_collector(app_engine)
        other.dispose()


def test_install_pool_collector_registers_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from prometheus_client import CollectorRegistry

    monkeypatch.setattr(db_metrics, "_pool_collector", None)
    fresh = CollectorRegistry()
    engine = create_engine("sqlite://", poolclass=StaticPool)

    collector = install_pool_collector(engine, fresh)

    assert collector is db_metrics._pool_collector
    assert fresh.get_sample_value("rudix_db_pool_size") is None
    fresh.unregister(collector)
    engine.dispose()
