"""Reporting replica session against PostgreSQL (0.8.0, R08-04).

``TEST_DATABASE_URL`` doubles as the replica URL: the server is a primary, so the read-only
guarantee must come from the reporting engine itself (``default_transaction_read_only``, or
``SET TRANSACTION READ ONLY`` in simulated PgBouncer mode), not from a hot standby.

The replica session opens its own connection, so the tests that read seeded rows through it
commit them with ``pg_session_factory`` and delete them at the end, scoped by fresh ids.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core import metrics_db_replica
from app.core.config import AuthProvider, RlsEnforcement, settings
from app.db import replica
from app.db import session as db_session_module
from app.db.replica import LagSample, ReplicaLagSampler, query_replica_lag
from app.db.tenant_context import bind_session_tenant
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User
from tests.conftest import RLS_PROBE_ROLE

pytestmark = pytest.mark.requires_postgres

SECRET = "replica-test-secret"
ISSUER = "rudix-test"
AUDIENCE = "rudix-test-audience"


@pytest.fixture
def replica_settings(
    monkeypatch: pytest.MonkeyPatch, pg_migrated_url: str
) -> Iterator[pytest.MonkeyPatch]:
    """Point the replica at TEST_DATABASE_URL with a fresh sampler."""
    monkeypatch.setattr(settings, "database_replica_url", pg_migrated_url)
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(replica, "lag_sampler", ReplicaLagSampler())
    yield monkeypatch


@pytest_asyncio.fixture
async def fresh_reporting_engine(replica_settings: pytest.MonkeyPatch) -> AsyncIterator[None]:
    await db_session_module.dispose_reporting_engine()
    yield
    await db_session_module.dispose_reporting_engine()


async def _assert_rejects_writes(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError) as excinfo:
        # Touches no row; the read-only check runs when the executor starts.
        await session.execute(text("UPDATE organizations SET name = name WHERE false"))
    assert "read-only transaction" in str(excinfo.value)


@pytest.mark.usefixtures("fresh_reporting_engine")
async def test_reporting_session_rejects_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    async with db_session_module.ReportingSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT current_setting('default_transaction_read_only'), "
                    "current_setting('transaction_read_only')"
                )
            )
        ).one()
        assert tuple(row) == ("on", "on")
        await _assert_rejects_writes(session)


@pytest.mark.usefixtures("fresh_reporting_engine")
async def test_reporting_session_rejects_writes_in_pgbouncer_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulated PgBouncer: no startup parameters, so the per-transaction statement does it.
    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    async with db_session_module.ReportingSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT current_setting('default_transaction_read_only'), "
                    "current_setting('transaction_read_only')"
                )
            )
        ).one()
        assert tuple(row) == ("off", "on")
        await _assert_rejects_writes(session)
        await session.rollback()
        # The next transaction on the same session is read-only too.
        await _assert_rejects_writes(session)


async def test_lag_query_returns_zero_on_a_primary(pg_engine: object) -> None:
    assert await query_replica_lag(pg_engine, 500) == 0.0  # type: ignore[arg-type]


@dataclass
class TwoOrgs:
    org_a: UUID
    org_b: UUID
    admin_a: UUID


async def _seed(factory: async_sessionmaker[AsyncSession]) -> TwoOrgs:
    org_a, org_b = uuid4(), uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            [
                Organization(id=org_a, name="Replica A", slug=f"replica-a-{org_a.hex[:10]}"),
                Organization(id=org_b, name="Replica B", slug=f"replica-b-{org_b.hex[:10]}"),
            ]
        )
        await session.flush()
        admin_a = uuid4()
        for org, user_id in ((org_a, admin_a), (org_b, uuid4())):
            session.add(
                User(
                    id=user_id,
                    organization_id=org,
                    external_auth_id=f"replica-{uuid4().hex[:10]}",
                    email=f"replica-{uuid4().hex[:10]}@example.com",
                    display_name="Replica",
                )
            )
            await session.flush()
            session.add(
                OrganizationMember(
                    organization_id=org, user_id=user_id, role=OrganizationRole.admin.value
                )
            )
            for tokens in (100, 250):
                session.add(
                    UsageEvent(
                        organization_id=org,
                        user_id=user_id,
                        event_type="chat.question",
                        model_name="gpt-4o",
                        input_tokens=tokens,
                        output_tokens=tokens // 2,
                        cost_usd=Decimal("0.01"),
                        metadata_json={},
                    )
                )
    return TwoOrgs(org_a=org_a, org_b=org_b, admin_a=admin_a)


async def _cleanup(factory: async_sessionmaker[AsyncSession], seed: TwoOrgs) -> None:
    orgs = [str(seed.org_a), str(seed.org_b)]
    async with factory() as session, session.begin():
        for table in ("usage_events", "organization_members"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE organization_id::text = ANY(:orgs)"),
                {"orgs": orgs},
            )
        await session.execute(
            text("DELETE FROM users WHERE organization_id::text = ANY(:orgs)"), {"orgs": orgs}
        )
        await session.execute(
            text("DELETE FROM organizations WHERE id::text = ANY(:orgs)"), {"orgs": orgs}
        )


@pytest_asyncio.fixture
async def seeded(pg_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[TwoOrgs]:
    seed = await _seed(pg_session_factory)
    try:
        yield seed
    finally:
        await _cleanup(pg_session_factory, seed)


@pytest_asyncio.fixture
async def probe_role(pg_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[str]:
    """The NOBYPASSRLS probe role, committed so the replica connection can SET ROLE to it."""
    async with pg_session_factory() as session, session.begin():
        await session.execute(
            text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RLS_PROBE_ROLE}') "
                f"THEN CREATE ROLE {RLS_PROBE_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        await session.execute(text(f"GRANT USAGE ON SCHEMA public TO {RLS_PROBE_ROLE}"))
        await session.execute(text(f"GRANT SELECT ON usage_events TO {RLS_PROBE_ROLE}"))
    try:
        yield RLS_PROBE_ROLE
    finally:
        async with pg_session_factory() as session, session.begin():
            await session.execute(text(f"REVOKE SELECT ON usage_events FROM {RLS_PROBE_ROLE}"))


@pytest.mark.usefixtures("fresh_reporting_engine")
async def test_replica_session_is_tenant_bound_under_strict_rls(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: async_sessionmaker[AsyncSession],
    seeded: TwoOrgs,
    probe_role: str,
) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    async with pg_session_factory() as primary:
        bind_session_tenant(primary, seed_org := seeded.org_a, enforce_guard=True)
        async with replica.reporting_session(primary) as session:
            assert session is not primary
            row = (
                await session.execute(
                    text(
                        "SELECT current_setting('app.current_organization_id', true), "
                        "current_setting('app.rls_mode', true), "
                        "current_setting('transaction_read_only')"
                    )
                )
            ).one()
            assert tuple(row) == (str(seed_org), "strict", "on")
            await session.execute(text(f"SET LOCAL ROLE {probe_role}"))
            rows = await session.execute(
                text(
                    "SELECT DISTINCT organization_id FROM usage_events "
                    "WHERE organization_id = ANY(:orgs)"
                ),
                {"orgs": [seeded.org_a, seeded.org_b]},
            )
            assert {r[0] for r in rows} == {seeded.org_a}


# --- reporting endpoints: identical bodies via the replica and the primary -----------------


def _token(seed: TwoOrgs) -> str:
    return create_app_access_token(
        user_id=str(seed.admin_a),
        organization_id=str(seed.org_a),
        role=OrganizationRole.admin.value,
        secret=SecretStr(SECRET),
        issuer=ISSUER,
        audience=AUDIENCE,
    )


@pytest_asyncio.fixture
async def report_client(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    from app.main import app

    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "app_auth_issuer", ISSUER)
    monkeypatch.setattr(settings, "app_auth_audience", AUDIENCE)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _primary() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[db_session_module.get_db_session] = _primary
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(db_session_module.get_db_session, None)
        get_auth_provider.cache_clear()


def _report_paths() -> list[str]:
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=7)
    end = today + timedelta(days=1)
    dates = f"from={start.isoformat()}&to={end.isoformat()}"
    stamps = f"from={start.isoformat()}T00:00:00%2B00:00&to={end.isoformat()}T00:00:00%2B00:00"
    prefix = settings.api_prefix
    return [
        f"{prefix}/admin/usage/dashboard?{dates}",
        f"{prefix}/admin/usage-adoption/summary?{dates}",
        f"{prefix}/admin/usage-adoption/charts?{dates}",
        f"{prefix}/admin/usage-adoption/funnel?{dates}",
        f"{prefix}/admin/usage-adoption/users?{dates}",
        f"{prefix}/admin/usage-adoption/export?{dates}",
        f"{prefix}/reports?{stamps}",
        f"{prefix}/reports/answer-quality?{stamps}",
    ]


def _comparable(content: bytes) -> object:
    """The body without ``generated_at``, the one field that is the request time."""
    try:
        body = json.loads(content)
    except ValueError:
        return content

    def strip(node: object) -> object:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "generated_at"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(body)


def _routed_to_replica() -> float:
    counter = metrics_db_replica.DB_REPLICA_ROUTED_TOTAL.labels(target="replica", reason="ok")
    return float(counter._value.get())


@pytest.mark.usefixtures("fresh_reporting_engine")
async def test_report_endpoints_match_on_replica_and_primary(
    monkeypatch: pytest.MonkeyPatch,
    report_client: AsyncClient,
    seeded: TwoOrgs,
    pg_migrated_url: str,
) -> None:
    headers = {"Authorization": f"Bearer {_token(seeded)}"}
    paths = _report_paths()

    monkeypatch.setattr(settings, "database_replica_url", None)
    via_primary: dict[str, object] = {}
    for path in paths:
        response = await report_client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        via_primary[path] = _comparable(response.content)

    monkeypatch.setattr(settings, "database_replica_url", pg_migrated_url)
    before = _routed_to_replica()
    via_replica: dict[str, object] = {}
    for path in paths:
        response = await report_client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        via_replica[path] = _comparable(response.content)
    assert _routed_to_replica() == before + len(paths)
    assert via_replica == via_primary
    # The seeded usage is visible, so the comparison is not between two empty reports.
    dashboard = via_primary[paths[0]]
    assert isinstance(dashboard, dict)
    assert dashboard["totals"]["input_tokens"] == 350


@pytest.mark.usefixtures("fresh_reporting_engine")
async def test_report_endpoint_falls_back_when_the_replica_stops_answering(
    monkeypatch: pytest.MonkeyPatch,
    report_client: AsyncClient,
    seeded: TwoOrgs,
) -> None:
    """A fresh good sample, then the replica refuses connections: the report uses the primary."""
    headers = {"Authorization": f"Bearer {_token(seeded)}"}
    path = _report_paths()[0]
    monkeypatch.setattr(settings, "database_replica_url", None)
    via_primary = await report_client.get(path, headers=headers)
    assert via_primary.status_code == 200, via_primary.text

    # Port 1 on loopback refuses connections at once.
    monkeypatch.setattr(
        settings, "database_replica_url", "postgresql+asyncpg://rudix:rudix@127.0.0.1:1/rudix"
    )
    sampler = replica.lag_sampler
    sampler._sample = LagSample(lag_seconds=0.0, sampled_at=sampler.now())
    failed = metrics_db_replica.DB_REPLICA_ROUTED_TOTAL.labels(
        target="primary", reason="sample_failed"
    )
    before = float(failed._value.get())
    response = await report_client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert _comparable(response.content) == _comparable(via_primary.content)
    assert float(failed._value.get()) == before + 1
    assert sampler.last_sample is not None and sampler.last_sample.lag_seconds is None
