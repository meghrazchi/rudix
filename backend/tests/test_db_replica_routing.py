"""Read-replica routing for reporting routes, without a database (0.8.0, R08-04).

The Postgres lane (``test_db_replica_pg.py``) proves read-only enforcement, tenant binding,
and identical report bodies against a real server.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import dependencies as auth_dependencies
from app.auth.models import AuthenticatedPrincipal
from app.core import metrics_db_replica, metrics_infra
from app.core.config import settings
from app.core.settings.snapshot import sanitized_snapshot
from app.db import replica
from app.db import session as db_session_module
from app.db.replica import (
    LAG_QUERY,
    LagSample,
    ReplicaLagSampler,
    RouteDecision,
    decide_route,
    parse_lag,
)
from app.db.session import (
    READ_ONLY_TRANSACTION_INFO_KEY,
    build_connect_args,
    build_engine_kwargs,
)

REPLICA_URL = "postgresql+asyncpg://reader:pw@replica.invalid:5432/rudix"


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


@pytest.fixture(autouse=True)
def _fresh_sampler(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    clock = FakeClock()
    sampler = ReplicaLagSampler(clock=clock)
    monkeypatch.setattr(replica, "lag_sampler", sampler)
    monkeypatch.setattr(settings, "metrics_enabled", True)
    yield clock


@pytest.fixture
async def _no_replica_engine() -> AsyncIterator[None]:
    await db_session_module.dispose_reporting_engine()
    yield
    await db_session_module.dispose_reporting_engine()


def _routed(target: str, reason: str) -> float:
    value = metrics_db_replica.DB_REPLICA_ROUTED_TOTAL.labels(
        target=target, reason=reason
    )._value.get()
    return float(value)


# --- lag parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0.0),
        (Decimal("1.250000"), 1.25),
        (3.5, 3.5),
        ("7", 7.0),
        (Decimal("-2.0"), 0.0),
        (None, None),
        (True, None),
        ("not-a-number", None),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_parse_lag(raw: Any, expected: float | None) -> None:
    assert parse_lag(raw) == expected


def test_lag_query_covers_primary_and_caught_up_standby() -> None:
    assert "pg_is_in_recovery()" in LAG_QUERY
    assert "pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0" in LAG_QUERY
    assert LAG_QUERY.endswith("ELSE 0 END")


# --- routing decision --------------------------------------------------------------------


def _decide(sample: LagSample | None, *, now: float = 100.0, configured: bool = True) -> Any:
    return decide_route(
        replica_configured=configured,
        sample=sample,
        now=now,
        max_lag_seconds=30.0,
        check_interval_seconds=10.0,
    )


def test_unset_replica_routes_to_primary() -> None:
    assert _decide(LagSample(0.0, 100.0), configured=False) == RouteDecision(
        "primary", "replica_unset"
    )


def test_missing_or_failed_sample_routes_to_primary() -> None:
    assert _decide(None) == RouteDecision("primary", "sample_failed")
    assert _decide(LagSample(None, 100.0)) == RouteDecision("primary", "sample_failed")


def test_stale_sample_routes_to_primary() -> None:
    assert _decide(LagSample(0.0, 89.0)) == RouteDecision("primary", "sample_failed")


def test_lag_above_limit_routes_to_primary() -> None:
    assert _decide(LagSample(30.5, 100.0)) == RouteDecision("primary", "lag_exceeded")


def test_fresh_small_lag_routes_to_replica() -> None:
    assert _decide(LagSample(30.0, 95.0)) == RouteDecision("replica", "ok")
    assert _decide(LagSample(0.0, 90.0)) == RouteDecision("replica", "ok")


# --- sampler -----------------------------------------------------------------------------


async def test_sampler_caches_within_interval_and_resamples_after(
    monkeypatch: pytest.MonkeyPatch, _fresh_sampler: FakeClock
) -> None:
    clock = _fresh_sampler
    monkeypatch.setattr(settings, "db_replica_lag_check_interval_seconds", 10.0)
    values = iter([1.5, 4.0])
    calls: list[int] = []

    async def fake_query(_engine: Any, timeout_ms: int) -> float | None:
        calls.append(timeout_ms)
        return next(values)

    monkeypatch.setattr(replica, "query_replica_lag", fake_query)
    sampler = replica.lag_sampler
    first = await sampler.current(object())  # type: ignore[arg-type]
    assert first.lag_seconds == 1.5
    assert metrics_infra.DB_REPLICA_LAG_SECONDS._value.get() == 1.5
    clock.value += 5
    assert (await sampler.current(object())).lag_seconds == 1.5  # type: ignore[arg-type]
    clock.value += 6
    assert (await sampler.current(object())).lag_seconds == 4.0  # type: ignore[arg-type]
    assert calls == [settings.db_replica_lag_query_timeout_ms] * 2
    assert sampler.last_sample is not None and sampler.last_sample.sampled_at == clock.value
    sampler.reset()
    assert sampler.last_sample is None


async def test_sampler_failure_and_unknown_lag_give_failed_samples(
    monkeypatch: pytest.MonkeyPatch, _fresh_sampler: FakeClock
) -> None:
    async def broken(_engine: Any, _timeout_ms: int) -> float | None:
        raise OSError("connection refused")

    monkeypatch.setattr(replica, "query_replica_lag", broken)
    metrics_infra.DB_REPLICA_LAG_SECONDS.set(9.0)
    sample = await replica.lag_sampler.current(object())  # type: ignore[arg-type]
    assert sample.lag_seconds is None
    # A failed sample leaves the gauge at its last good value.
    assert metrics_infra.DB_REPLICA_LAG_SECONDS._value.get() == 9.0

    async def unknown(_engine: Any, _timeout_ms: int) -> float | None:
        return None

    monkeypatch.setattr(replica, "query_replica_lag", unknown)
    _fresh_sampler.value += 60
    assert (await replica.lag_sampler.current(object())).lag_seconds is None  # type: ignore[arg-type]


async def test_sampler_times_out_slow_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_replica_lag_query_timeout_ms", 20)

    async def slow(_engine: Any, _timeout_ms: int) -> float | None:
        await asyncio.sleep(5)
        return 0.0

    monkeypatch.setattr(replica, "query_replica_lag", slow)
    sample = await replica.lag_sampler.current(object())  # type: ignore[arg-type]
    assert sample.lag_seconds is None


async def test_concurrent_requests_share_one_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_query(_engine: Any, _timeout_ms: int) -> float | None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return 0.0

    monkeypatch.setattr(replica, "query_replica_lag", fake_query)
    samples = await asyncio.gather(
        *(replica.lag_sampler.current(object()) for _ in range(5))  # type: ignore[arg-type]
    )
    assert calls == 1
    assert {sample.lag_seconds for sample in samples} == {0.0}


async def test_query_replica_lag_sets_local_timeout_and_parses() -> None:
    executed: list[str] = []

    class FakeResult:
        def scalar(self) -> Any:
            return Decimal("2.5")

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def execute(self, statement: Any) -> FakeResult:
            executed.append(str(statement))
            return FakeResult()

        async def rollback(self) -> None:
            executed.append("ROLLBACK")

    engine = SimpleNamespace(connect=FakeConnection)
    assert await replica.query_replica_lag(engine, 250) == 2.5  # type: ignore[arg-type]
    assert executed == ["SET LOCAL statement_timeout = 250", LAG_QUERY, "ROLLBACK"]


# --- choose_reporting_target and reporting_session ----------------------------------------


@pytest.mark.usefixtures("_no_replica_engine")
async def test_unset_url_routes_to_primary_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_replica_url", None)
    before = _routed("primary", "replica_unset")
    primary = AsyncSession()
    async with replica.reporting_session(primary) as session:
        assert session is primary
    assert _routed("primary", "replica_unset") == before + 1


async def test_lag_exceeded_and_failed_sample_route_to_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replica, "get_reporting_engine", lambda: object())
    monkeypatch.setattr(settings, "db_replica_max_lag_seconds", 30.0)

    async def high(_engine: Any, _timeout_ms: int) -> float | None:
        return 31.0

    monkeypatch.setattr(replica, "query_replica_lag", high)
    before = _routed("primary", "lag_exceeded")
    primary = AsyncSession()
    async with replica.reporting_session(primary) as session:
        assert session is primary
    assert _routed("primary", "lag_exceeded") == before + 1

    async def broken(_engine: Any, _timeout_ms: int) -> float | None:
        raise TimeoutError

    replica.lag_sampler.reset()
    monkeypatch.setattr(replica, "query_replica_lag", broken)
    before = _routed("primary", "sample_failed")
    assert await replica.choose_reporting_target() == RouteDecision("primary", "sample_failed")
    assert _routed("primary", "sample_failed") == before + 1


async def test_fresh_replica_session_binds_the_primary_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_replica = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(bind=fake_replica, class_=AsyncSession)
    monkeypatch.setattr(replica, "get_reporting_engine", lambda: fake_replica)
    monkeypatch.setattr(replica, "ReportingSessionLocal", factory)

    async def zero(_engine: Any, _timeout_ms: int) -> float | None:
        return 0.0

    monkeypatch.setattr(replica, "query_replica_lag", zero)
    organization_id = uuid4()
    primary = AsyncSession()
    primary.info["organization_id"] = organization_id
    primary.info["enforce_tenant_guard"] = True
    before = _routed("replica", "ok")
    try:
        async with replica.reporting_session(primary) as session:
            assert session is not primary
            assert session.info["organization_id"] == organization_id
            assert session.info["enforce_tenant_guard"] is True
        assert _routed("replica", "ok") == before + 1
    finally:
        await fake_replica.dispose()


async def test_replica_that_fails_to_connect_falls_back_to_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # A fresh sample said the replica was fine, then the replica went away.
    unreachable = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/missing/dir/replica.db")
    factory = async_sessionmaker(bind=unreachable, class_=AsyncSession)
    monkeypatch.setattr(replica, "get_reporting_engine", lambda: unreachable)
    monkeypatch.setattr(replica, "ReportingSessionLocal", factory)
    samples: list[int] = []

    async def zero(_engine: Any, _timeout_ms: int) -> float | None:
        samples.append(1)
        return 0.0

    monkeypatch.setattr(replica, "query_replica_lag", zero)
    ok_before = _routed("replica", "ok")
    failed_before = _routed("primary", "sample_failed")
    primary = AsyncSession()
    try:
        async with replica.reporting_session(primary) as session:
            assert session is primary
        assert _routed("primary", "sample_failed") == failed_before + 1
        assert _routed("replica", "ok") == ok_before
        last = replica.lag_sampler.last_sample
        assert last is not None and last.lag_seconds is None
        # The rest of the interval skips the replica without sampling or connecting again.
        async with replica.reporting_session(primary) as session:
            assert session is primary
        assert samples == [1]
        assert _routed("primary", "sample_failed") == failed_before + 2
    finally:
        await unreachable.dispose()


async def test_replica_connect_is_bounded_by_the_lag_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_replica_lag_query_timeout_ms", 20)

    class HangingSession:
        def __init__(self) -> None:
            self.info: dict[str, Any] = {}

        async def __aenter__(self) -> HangingSession:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def connection(self) -> None:
            await asyncio.sleep(5)

    monkeypatch.setattr(replica, "get_reporting_engine", lambda: object())
    monkeypatch.setattr(replica, "ReportingSessionLocal", HangingSession)

    async def zero(_engine: Any, _timeout_ms: int) -> float | None:
        return 0.0

    monkeypatch.setattr(replica, "query_replica_lag", zero)
    primary = AsyncSession()
    async with asyncio.timeout(2):
        async with replica.reporting_session(primary) as session:
            assert session is primary


async def test_metrics_disabled_skips_the_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    before = _routed("primary", "replica_unset")
    metrics_db_replica.record_replica_route("primary", "replica_unset")
    assert _routed("primary", "replica_unset") == before


# --- dependency --------------------------------------------------------------------------


@pytest.mark.usefixtures("_no_replica_engine")
def test_dependency_yields_the_overridden_primary_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_replica_url", None)
    marker = AsyncSession()
    seen: list[AsyncSession] = []
    app = FastAPI()

    @app.get("/probe")
    async def probe(
        session: Annotated[AsyncSession, Depends(auth_dependencies.get_reporting_db_session)],
    ) -> dict[str, bool]:
        seen.append(session)
        return {"ok": True}

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield marker

    async def override_principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id=str(uuid4()),
            organization_id=str(uuid4()),
            roles=["admin"],
            auth_provider="test",
        )

    app.dependency_overrides[db_session_module.get_db_session] = override_db
    app.dependency_overrides[auth_dependencies.get_current_principal] = override_principal
    with TestClient(app) as client:
        assert client.get("/probe").json() == {"ok": True}
    assert seen == [marker]


def test_reporting_routes_use_the_reporting_dependency() -> None:
    from app.interfaces.http import admin, admin_usage_adoption, reports

    expected = {
        ("GET", "/admin/usage/dashboard"),
        ("GET", "/admin/usage-adoption/summary"),
        ("GET", "/admin/usage-adoption/charts"),
        ("GET", "/admin/usage-adoption/funnel"),
        ("GET", "/admin/usage-adoption/users"),
        ("GET", "/admin/usage-adoption/export"),
        ("GET", "/reports"),
        ("GET", "/reports/answer-quality"),
    }
    found: set[tuple[str, str]] = set()
    for router in (admin.router, admin_usage_adoption.router, reports.router):
        for route in router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            calls = {dep.call for dep in dependant.dependencies}
            if auth_dependencies.get_reporting_db_session in calls:
                for method in getattr(route, "methods", set()):
                    found.add((method, route.path))  # type: ignore[attr-defined]
    assert found == expected


# --- engine and session factory ----------------------------------------------------------


def test_read_only_connect_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    monkeypatch.setattr(settings, "db_statement_timeout_ms", 0)
    monkeypatch.setattr(settings, "db_idle_in_transaction_timeout_ms", 0)
    assert build_connect_args(settings) == {}
    assert build_connect_args(settings, read_only=True) == {
        "server_settings": {"default_transaction_read_only": "on"}
    }
    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    # PgBouncer ignores startup parameters; the session flag covers read-only instead.
    assert "server_settings" not in build_connect_args(settings, read_only=True)


def test_engine_kwargs_take_the_replica_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = build_engine_kwargs(settings, pool_size=3, max_overflow=0)
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 0
    defaults = build_engine_kwargs(settings)
    assert defaults["pool_size"] == settings.db_pool_size
    assert defaults["max_overflow"] == settings.db_max_overflow


@pytest.mark.usefixtures("_no_replica_engine")
async def test_reporting_engine_is_lazy_and_disposed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_replica_url", None)
    assert db_session_module.get_reporting_engine() is None
    with pytest.raises(RuntimeError):
        db_session_module.ReportingSessionLocal()

    monkeypatch.setattr(settings, "database_replica_url", REPLICA_URL)
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    monkeypatch.setattr(settings, "db_replica_pool_size", 2)
    engine = db_session_module.get_reporting_engine()
    assert engine is not None
    assert db_session_module.get_reporting_engine() is engine
    assert engine.pool.size() == 2  # type: ignore[attr-defined]
    session = db_session_module.ReportingSessionLocal()
    assert READ_ONLY_TRANSACTION_INFO_KEY not in session.info
    await session.close()

    await db_session_module.dispose_engine()
    assert db_session_module._reporting_engine is None

    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    db_session_module.get_reporting_engine()
    session = db_session_module.ReportingSessionLocal()
    assert session.info[READ_ONLY_TRANSACTION_INFO_KEY] is True
    await session.close()


def _begin_args(flag: bool, *, nested: bool = False, dialect: str = "postgresql") -> Any:
    executed: list[str] = []
    session = SimpleNamespace(info={READ_ONLY_TRANSACTION_INFO_KEY: True} if flag else {})
    transaction = SimpleNamespace(nested=nested)
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect),
        execute=lambda statement: executed.append(str(statement)),
    )
    return (session, transaction, connection), executed


@pytest.mark.parametrize(
    ("flag", "nested", "dialect", "expected"),
    [
        (True, False, "postgresql", ["SET TRANSACTION READ ONLY"]),
        (False, False, "postgresql", []),
        (True, True, "postgresql", []),
        (True, False, "sqlite", []),
    ],
)
def test_after_begin_marks_flagged_transactions_read_only(
    flag: bool, nested: bool, dialect: str, expected: list[str]
) -> None:
    args, executed = _begin_args(flag, nested=nested, dialect=dialect)
    replica._on_after_begin_read_only(*args)
    assert executed == expected


def test_read_only_guard_is_installed_once() -> None:
    replica.install_read_only_guard()
    replica.install_read_only_guard()
    assert replica._READ_ONLY_GUARD_INSTALLED is True


def test_snapshot_reports_replica_without_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_replica_url", REPLICA_URL)
    snapshot = sanitized_snapshot(settings)
    infrastructure = snapshot["infrastructure"]
    assert infrastructure["database_replica_url_set"] is True
    assert infrastructure["db_replica_max_lag_seconds"] == settings.db_replica_max_lag_seconds
    assert "replica.invalid" not in str(snapshot)
