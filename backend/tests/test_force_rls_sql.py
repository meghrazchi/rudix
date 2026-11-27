"""Operator SQL for FORCE ROW LEVEL SECURITY (0.5.0, S3).

``deploy/sql/force_rls.sql`` and ``unforce_rls.sql`` are rendered from ``app.db.rls`` by
``scripts/render_force_rls_sql.py``; the committed files must equal the rendered output.
On PostgreSQL the forced SQL is applied inside the rolled-back test transaction to show that
a non-superuser role that owns the tables sees only its tenant under ``strict``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import RLS_IDENTITY_TABLES, RLS_LOOKUP_TABLES, RLS_STRICT_TABLES
from app.models.chat import ChatSession
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User

BACKEND_DIR = Path(__file__).resolve().parents[1]
OWNER_ROLE = "rudix_force_owner_probe"
OWNED_TABLES = ("documents", "chat_sessions")


def _load_script() -> ModuleType:
    path = BACKEND_DIR / "scripts" / "render_force_rls_sql.py"
    spec = importlib.util.spec_from_file_location("render_force_rls_sql", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _statements(sql: str) -> list[str]:
    return [line.rstrip(";") for line in sql.splitlines() if line.startswith("ALTER TABLE ")]


@pytest.mark.parametrize("name", [script.FORCE_FILE, script.UNFORCE_FILE])
def test_committed_files_equal_rendered_output(name: str) -> None:
    committed = (script.DEPLOY_SQL_DIR / name).read_text(encoding="utf-8")
    assert committed == script.rendered_files()[name], (
        f"deploy/sql/{name} is stale; run: cd backend && python scripts/render_force_rls_sql.py"
    )


def test_rendered_tables_are_every_policy_table_and_no_identity_table() -> None:
    expected = sorted(set(RLS_STRICT_TABLES) | set(RLS_LOOKUP_TABLES))
    assert script.forced_tables() == expected
    force = _statements(script.render_force_sql())
    unforce = _statements(script.render_unforce_sql())
    assert force == [f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in expected]
    assert unforce == [f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY" for t in expected]
    for table in RLS_IDENTITY_TABLES:
        assert f" {table} " not in script.render_force_sql()
    # Operator SQL, never a transaction block of its own: ``psql -1`` wraps it.
    assert "BEGIN" not in script.render_force_sql() and "COMMIT" not in script.render_force_sql()


def test_check_mode_reports_stale_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["--check"], directory=tmp_path) == 1
    assert "stale" in capsys.readouterr().err
    assert script.main([], directory=tmp_path) == 0
    assert script.main(["--check"], directory=tmp_path) == 0
    (tmp_path / script.UNFORCE_FILE).write_text("-- edited\n", encoding="utf-8")
    assert script.main(["--check"], directory=tmp_path) == 1


def test_committed_files_pass_check() -> None:
    assert script.main(["--check"]) == 0


# --- PostgreSQL ------------------------------------------------------------------------


async def _seed_two_orgs(session: AsyncSession) -> tuple[UUID, UUID]:
    org_a, org_b = uuid4(), uuid4()
    session.add_all(
        [
            Organization(id=org_a, name="Force A", slug=f"force-a-{org_a.hex[:10]}"),
            Organization(id=org_b, name="Force B", slug=f"force-b-{org_b.hex[:10]}"),
        ]
    )
    await session.flush()
    for org in (org_a, org_b):
        user = User(
            organization_id=org,
            external_auth_id=f"force-{uuid4().hex[:10]}",
            email=f"force-{uuid4().hex[:10]}@example.com",
        )
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Document(
                    organization_id=org,
                    uploaded_by_user_id=user.id,
                    filename="force.pdf",
                    file_type="pdf",
                    storage_bucket="documents",
                    storage_object_key=f"{org}/force.pdf",
                    status=DocumentStatus.indexed.value,
                ),
                ChatSession(organization_id=org, user_id=user.id, title="Force"),
            ]
        )
    await session.flush()
    return org_a, org_b


async def _as_owner_sees(session: AsyncSession, table: str, org: UUID | None) -> set[UUID]:
    await session.execute(text(f"SET LOCAL ROLE {OWNER_ROLE}"))
    await session.execute(
        text(
            "SELECT set_config('app.current_organization_id', :org, true), "
            "set_config('app.rls_mode', 'strict', true)"
        ),
        {"org": "" if org is None else str(org)},
    )
    rows = await session.execute(text(f"SELECT DISTINCT organization_id FROM {table}"))
    seen = {row[0] for row in rows}
    await session.execute(text("RESET ROLE"))
    return seen


async def _execute_file(session: AsyncSession, name: str) -> None:
    sql = (script.DEPLOY_SQL_DIR / name).read_text(encoding="utf-8")
    for statement in _statements(sql):
        await session.execute(text(statement))


@pytest.mark.requires_postgres
async def test_force_rls_sql_applies_policies_to_a_non_superuser_owner(
    pg_session: AsyncSession,
) -> None:
    session = pg_session
    org_a, org_b = await _seed_two_orgs(session)
    # A non-superuser, non-BYPASSRLS role that owns the tables, as a deployment that still
    # connects as the owner would. Role, ownership, and FORCE vanish with the rollback.
    await session.execute(text(f"CREATE ROLE {OWNER_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
    await session.execute(text(f"GRANT USAGE, CREATE ON SCHEMA public TO {OWNER_ROLE}"))
    for table in OWNED_TABLES:
        await session.execute(text(f"ALTER TABLE {table} OWNER TO {OWNER_ROLE}"))

    for table in OWNED_TABLES:
        # Without FORCE the owner bypasses the policy, even under strict with a tenant.
        assert {org_a, org_b} <= await _as_owner_sees(session, table, org_a), table

    await _execute_file(session, script.FORCE_FILE)
    forced = await session.execute(
        text(
            "SELECT relname FROM pg_class WHERE relforcerowsecurity "
            "AND relname = ANY(:names) AND relkind IN ('r', 'p')"
        ),
        {"names": script.forced_tables()},
    )
    assert {row[0] for row in forced} == set(script.forced_tables())
    for table in OWNED_TABLES:
        assert await _as_owner_sees(session, table, org_a) == {org_a}, table
        assert await _as_owner_sees(session, table, org_b) == {org_b}, table
        assert await _as_owner_sees(session, table, None) == set(), table

    await _execute_file(session, script.UNFORCE_FILE)
    for table in OWNED_TABLES:
        assert {org_a, org_b} <= await _as_owner_sees(session, table, org_a), table
