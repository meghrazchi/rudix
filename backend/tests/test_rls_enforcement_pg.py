"""PostgreSQL row-level security enforcement under a non-owner role (R04-08).

The queries below deliberately omit the application's ``organization_id`` filter: they
prove that the database policy alone keeps tenants apart in ``strict`` mode.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import RlsEnforcement, settings
from app.db.tenant_context import (
    apply_tenant_context,
    bind_session_tenant,
    install_sqlalchemy_tenant_guard,
)
from app.models.api_key import ApiKey
from app.models.auth_session import AuthRefreshSession
from app.models.chat import ChatSession
from app.models.collection import Collection
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User
from tests.conftest import RLS_PROBE_ROLE, RlsProbe
from tests.pg_plans import compact_indexes

pytestmark = pytest.mark.requires_postgres

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEEDED_TABLES = ("documents", "collections", "chat_sessions", "usage_events")


@dataclass
class Seed:
    org_a: UUID
    org_b: UUID
    user_a: UUID


async def _seed_two_orgs(session: AsyncSession) -> Seed:
    org_a, org_b = uuid4(), uuid4()
    session.add_all(
        [
            Organization(id=org_a, name="RLS A", slug=f"rls-a-{org_a.hex[:10]}"),
            Organization(id=org_b, name="RLS B", slug=f"rls-b-{org_b.hex[:10]}"),
        ]
    )
    await session.flush()
    users = {}
    for org in (org_a, org_b):
        user = User(
            organization_id=org,
            external_auth_id=f"rls-{uuid4().hex[:10]}",
            email=f"rls-{uuid4().hex[:10]}@example.com",
            display_name="RLS",
        )
        session.add(user)
        await session.flush()
        users[org] = user.id
        session.add_all(
            [
                Document(
                    organization_id=org,
                    uploaded_by_user_id=user.id,
                    filename="rls.pdf",
                    file_type="pdf",
                    storage_bucket="documents",
                    storage_object_key=f"{org}/rls.pdf",
                    status=DocumentStatus.indexed.value,
                ),
                Collection(organization_id=org, owner_id=user.id, name="RLS"),
                ChatSession(organization_id=org, user_id=user.id, title="RLS"),
                UsageEvent(organization_id=org, user_id=user.id, event_type="rls.test"),
                ApiKey(
                    organization_id=org,
                    name="RLS key",
                    key_prefix="rudix_rlstest",
                    key_hash=uuid4().hex + uuid4().hex,
                    scopes=[],
                ),
            ]
        )
    await session.flush()
    return Seed(org_a=org_a, org_b=org_b, user_a=users[org_a])


async def _org_ids(session: AsyncSession, table: str) -> set[UUID]:
    rows = await session.execute(text(f"SELECT DISTINCT organization_id FROM {table}"))
    return {row[0] for row in rows}


async def _count(session: AsyncSession, table: str) -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def test_probe_role_is_not_privileged(rls_probe_session: RlsProbe) -> None:
    await rls_probe_session.become_probe(organization_id=None, mode="strict")
    row = (
        await rls_probe_session.session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()
    assert tuple(row) == (False, False)


async def test_strict_with_tenant_hides_other_orgs(rls_probe_session: RlsProbe) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    await rls_probe_session.become_probe(organization_id=seed.org_a, mode="strict")
    for table in SEEDED_TABLES:
        assert await _org_ids(rls_probe_session.session, table) == {seed.org_a}, table


async def test_strict_without_tenant_returns_no_rows(rls_probe_session: RlsProbe) -> None:
    await _seed_two_orgs(rls_probe_session.session)
    await rls_probe_session.become_probe(organization_id=None, mode="strict")
    for table in SEEDED_TABLES:
        assert await _count(rls_probe_session.session, table) == 0, table


async def test_strict_with_check_rejects_cross_org_insert(rls_probe_session: RlsProbe) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    session = rls_probe_session.session
    await rls_probe_session.become_probe(organization_id=seed.org_a, mode="strict")
    insert = text(
        "INSERT INTO collections (id, organization_id, owner_id, name, access_policy, "
        "is_archived, is_dynamic, review_status, created_at, updated_at) "
        "VALUES (:id, :org, :owner, 'x', "
        "'org_wide', false, false, 'current', now(), now())"
    )
    async with session.begin_nested():
        await session.execute(
            insert, {"id": uuid4(), "org": seed.org_a, "owner": seed.user_a}
        )  # own org: allowed
    with pytest.raises(DBAPIError, match="row-level security"):
        async with session.begin_nested():
            await session.execute(insert, {"id": uuid4(), "org": seed.org_b, "owner": seed.user_a})


@pytest.mark.parametrize("mode", ["soft", "off", ""])
async def test_non_strict_without_tenant_sees_all_rows(
    rls_probe_session: RlsProbe, mode: str
) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    await rls_probe_session.become_probe(organization_id=None, mode=mode)
    for table in SEEDED_TABLES:
        assert {seed.org_a, seed.org_b} <= await _org_ids(rls_probe_session.session, table)


async def test_soft_with_tenant_still_filters(rls_probe_session: RlsProbe) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    await rls_probe_session.become_probe(organization_id=seed.org_b, mode="soft")
    assert await _org_ids(rls_probe_session.session, "documents") == {seed.org_b}


async def test_lookup_table_readable_without_tenant_in_strict(
    rls_probe_session: RlsProbe,
) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    await rls_probe_session.become_probe(organization_id=None, mode="strict")
    assert {seed.org_a, seed.org_b} <= await _org_ids(rls_probe_session.session, "api_keys")
    # A bound tenant still only sees its own lookup rows.
    await rls_probe_session.become_probe(organization_id=seed.org_a, mode="strict")
    assert await _org_ids(rls_probe_session.session, "api_keys") == {seed.org_a}


async def test_identity_tables_span_organizations_under_strict(
    rls_probe_session: RlsProbe,
) -> None:
    """A user of org A who works in org B: user row, memberships, sessions stay reachable."""
    seed = await _seed_two_orgs(rls_probe_session.session)
    session = rls_probe_session.session
    user_id = seed.user_a  # home organization A
    session.add_all(
        [
            OrganizationMember(organization_id=seed.org_a, user_id=user_id, role="member"),
            OrganizationMember(organization_id=seed.org_b, user_id=user_id, role="member"),
            *(
                AuthRefreshSession(
                    organization_id=org,
                    user_id=user_id,
                    session_id=uuid4(),
                    refresh_token_hash=uuid4().hex + uuid4().hex,
                    refresh_token_jti=uuid4().hex,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
                for org in (seed.org_a, seed.org_b)
            ),
        ]
    )
    await session.flush()
    await session.execute(text(f"GRANT UPDATE ON auth_refresh_sessions TO {RLS_PROBE_ROLE}"))
    await rls_probe_session.become_probe(organization_id=seed.org_b, mode="strict")

    params = {"user_id": user_id}
    users = await session.execute(text("SELECT id FROM users WHERE id = :user_id"), params)
    assert users.scalar_one() == user_id  # /auth/session, member lists, invites
    memberships = await session.execute(
        text("SELECT organization_id FROM organization_members WHERE user_id = :user_id"),
        params,
    )
    assert {row[0] for row in memberships} == {seed.org_a, seed.org_b}  # workspace switcher
    revoked = await session.execute(
        text(
            "UPDATE auth_refresh_sessions SET revoked_at = now() "
            "WHERE user_id = :user_id AND revoked_at IS NULL"
        ),
        params,
    )
    assert revoked.rowcount == 2  # logout-all revokes the sessions of every organization


async def test_document_list_plan_uses_org_index_under_policy(
    rls_probe_session: RlsProbe,
) -> None:
    seed = await _seed_two_orgs(rls_probe_session.session)
    session = rls_probe_session.session
    await compact_indexes(session, "documents")  # as the owner, before SET ROLE
    await rls_probe_session.become_probe(organization_id=seed.org_a, mode="strict")
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = await session.execute(
        text(
            "EXPLAIN SELECT id FROM documents WHERE organization_id = :org "
            "ORDER BY created_at DESC LIMIT 20"
        ),
        {"org": seed.org_a},
    )
    plan = "\n".join(row[0] for row in plan_rows)
    assert "idx_documents_org_created" in plan, plan
    assert "Seq Scan on documents" not in plan, plan


# --- after_begin listener on PostgreSQL ------------------------------------------------


async def _settings_in_new_transaction(session: AsyncSession) -> tuple[Any, ...]:
    row = (
        await session.execute(
            text(
                "SELECT current_setting('app.current_organization_id', true), "
                "current_setting('app.rls_mode', true), current_setting('statement_timeout')"
            )
        )
    ).one()
    return tuple(row)


@pytest.fixture
def isolated_engine_url(pg_migrated_url: str) -> str:
    install_sqlalchemy_tenant_guard()  # done by app.db.session at import in the app
    return pg_migrated_url


async def _fresh_session(url: str) -> tuple[Any, AsyncSession]:
    engine = create_async_engine(url, poolclass=NullPool)
    return engine, AsyncSession(bind=engine, expire_on_commit=False)


@pytest.mark.parametrize(
    ("mode", "bound", "expected_org", "expected_mode"),
    [
        (RlsEnforcement.strict, True, "org", "strict"),
        (RlsEnforcement.strict, False, "", "strict"),
        (RlsEnforcement.soft, True, "org", "soft"),
        (RlsEnforcement.soft, False, None, None),
        (RlsEnforcement.off, True, None, None),
    ],
)
async def test_after_begin_sets_session_context(
    isolated_engine_url: str,
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement,
    bound: bool,
    expected_org: str | None,
    expected_mode: str | None,
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    org = uuid4()
    engine, session = await _fresh_session(isolated_engine_url)
    try:
        if bound:
            session.info["organization_id"] = org
        org_value, mode_value, _ = await _settings_in_new_transaction(session)
        # An unset custom setting reads as NULL, or '' once set earlier on the connection.
        assert (org_value or None) == (str(org) if expected_org == "org" else expected_org or None)
        assert (mode_value or None) == expected_mode
    finally:
        await session.close()
        await engine.dispose()


async def test_after_begin_skips_maintenance_sessions(
    isolated_engine_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    engine, session = await _fresh_session(isolated_engine_url)
    try:
        session.info["rls_maintenance"] = True
        org_value, mode_value, _ = await _settings_in_new_transaction(session)
        assert not org_value and not mode_value
    finally:
        await session.close()
        await engine.dispose()


async def test_apply_tenant_context_rebinds_open_transaction(
    isolated_engine_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    engine, session = await _fresh_session(isolated_engine_url)
    org = uuid4()
    try:
        org_value, mode_value, _ = await _settings_in_new_transaction(session)
        assert (org_value, mode_value) == ("", "strict")  # begun before the tenant is known
        bind_session_tenant(session, org)
        await apply_tenant_context(session)
        org_value, mode_value, _ = await _settings_in_new_transaction(session)
        assert (org_value, mode_value) == (str(org), "strict")
        await session.commit()
        org_value, _, _ = await _settings_in_new_transaction(session)
        assert org_value == str(org)  # next transaction gets it from after_begin
    finally:
        await session.close()
        await engine.dispose()


async def test_pgbouncer_mode_sets_timeouts_per_transaction(
    isolated_engine_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.off)
    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    monkeypatch.setattr(settings, "db_statement_timeout_ms", 4321)
    monkeypatch.setattr(settings, "db_idle_in_transaction_timeout_ms", 0)
    engine, session = await _fresh_session(isolated_engine_url)
    try:
        _, _, statement_timeout = await _settings_in_new_transaction(session)
        assert statement_timeout == "4321ms"
        await session.commit()
        async with engine.connect() as raw:  # outside the session: server default
            assert (await raw.execute(text("SHOW statement_timeout"))).scalar() == "0"
    finally:
        await session.close()
        await engine.dispose()


# --- migration round trip ---------------------------------------------------------------


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (result.stderr or result.stdout)[-4000:]


async def _policy_state(url: str) -> tuple[int, int]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            policies = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_policies "
                        "WHERE policyname = 'tenant_isolation_policy'"
                    )
                )
            ).scalar_one()
            strict = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_policies "
                        "WHERE policyname = 'tenant_isolation_policy' "
                        "AND qual LIKE '%app.rls_mode%'"
                    )
                )
            ).scalar_one()
        return int(policies), int(strict)
    finally:
        await engine.dispose()


async def _rls_enabled(url: str, tables: tuple[str, ...]) -> int:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_class "
                    "WHERE relname = ANY(:tables) AND (relrowsecurity OR EXISTS ("
                    "SELECT 1 FROM pg_policies p WHERE p.tablename = pg_class.relname))"
                ),
                {"tables": list(tables)},
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


async def test_migration_round_trip() -> None:
    url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_MIGRATIONS_DATABASE_URL is not set (a database safe to downgrade)")
    _alembic(url, "upgrade", "head")
    total, strict = await _policy_state(url)
    assert total >= 87 and strict >= 72
    assert await _rls_enabled(url, ("users", "organization_members", "auth_refresh_sessions")) == 0
    _alembic(url, "downgrade", "20261127_0003")
    assert await _policy_state(url) == (12, 0)
    _alembic(url, "upgrade", "head")
    assert await _policy_state(url) == (total, strict)


# --- deploy/sql/provision_roles.sql -----------------------------------------------------

PROVISION_SQL = BACKEND_DIR.parent / "deploy" / "sql" / "provision_roles.sql"


async def test_provision_roles_script(rls_probe_session: RlsProbe) -> None:
    session = rls_probe_session.session
    seed = await _seed_two_orgs(session)
    raw = await (await session.connection()).get_raw_connection()
    driver = raw.driver_connection
    assert driver is not None
    sql = PROVISION_SQL.read_text()
    await driver.execute(sql)
    await driver.execute(sql)  # idempotent
    roles = {
        row[0]: (row[1], row[2])
        for row in await session.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('rudix_app', 'rudix_maintenance')"
            )
        )
    }
    assert roles == {"rudix_app": (False, False), "rudix_maintenance": (False, True)}

    await session.execute(text("SET LOCAL ROLE rudix_app"))
    await session.execute(
        text(
            "SELECT set_config('app.current_organization_id', :org, true), "
            "set_config('app.rls_mode', 'strict', true)"
        ),
        {"org": str(seed.org_a)},
    )
    assert await _org_ids(session, "documents") == {seed.org_a}
    await session.execute(text("RESET ROLE"))
    await session.execute(text("SET LOCAL ROLE rudix_maintenance"))
    assert {seed.org_a, seed.org_b} <= await _org_ids(session, "documents")
