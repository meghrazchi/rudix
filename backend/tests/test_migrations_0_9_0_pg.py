"""0.9.0 migrations round trip on PostgreSQL (S1): tables, constraints, RLS policies.

Needs ``TEST_MIGRATIONS_DATABASE_URL``: a database that is safe to downgrade (never the one
``TEST_DATABASE_URL`` names, which other tests share).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db import rls

pytestmark = pytest.mark.requires_postgres

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_REVISION = "20261128_0003"
NEW_TABLES = (
    "auth_one_time_tokens",
    "user_mfa_factors",
    "user_mfa_recovery_codes",
    "org_login_policies",
    "billing_plans",
    "billing_customers",
    "billing_subscriptions",
    "billing_invoices",
    "billing_webhook_events",
)
NEW_COLUMNS = (
    ("users", "email_verified_at"),
    ("auth_refresh_sessions", "auth_method"),
    ("auth_refresh_sessions", "mfa_verified_at"),
    ("org_quota_policy", "stage_limits"),
)
EVENT_TYPE_CHECK = "ck_email_delivery_logs_email_delivery_logs_event_type_allowed"
PREFERENCE_CHECK = "ck_user_notification_preferences_user_notif_pref_event__ba46"


def _url() -> str:
    url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_MIGRATIONS_DATABASE_URL is not set (a database safe to downgrade)")
    return url


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


async def _state(url: str) -> dict[str, object]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            tables = set(
                (
                    await conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                ).scalars()
            )
            columns = {
                (row[0], row[1])
                for row in await conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            policies = {
                row[0]: row[1]
                for row in await conn.execute(
                    text(
                        "SELECT tablename, qual FROM pg_policies "
                        "WHERE policyname = 'tenant_isolation_policy'"
                    )
                )
            }
            checks = {
                row[0]: (row[1], row[2])
                for row in await conn.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid), convalidated "
                        "FROM pg_constraint WHERE contype = 'c'"
                    )
                )
            }
            partial = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = 'uq_user_mfa_factors_user_type_active'"
                    )
                )
            ).scalar_one_or_none()
            head = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        return {
            "tables": tables,
            "columns": columns,
            "policies": policies,
            "checks": checks,
            "partial": partial,
            "head": head,
        }
    finally:
        await engine.dispose()


def _assert_upgraded(state: dict[str, object]) -> None:
    tables = state["tables"]
    columns = state["columns"]
    policies = state["policies"]
    checks = state["checks"]
    assert isinstance(tables, set) and isinstance(columns, set)
    assert isinstance(policies, dict) and isinstance(checks, dict)
    assert state["head"] == "20261129_0003"
    assert set(NEW_TABLES) <= tables
    assert set(NEW_COLUMNS) <= columns
    for table in rls.RLS_LOOKUP_TABLES_0_9_0:
        assert "app.rls_mode" not in policies[table], table
    for table in rls.RLS_STRICT_TABLES_0_9_0:
        assert "app.rls_mode" in policies[table], table
    for table in ("user_mfa_factors", "user_mfa_recovery_codes", "billing_plans"):
        assert table not in policies
    definition, validated = checks[EVENT_TYPE_CHECK]
    assert validated is True
    for event_type in ("email_verification", "password_reset", "onboarding_reminder"):
        assert event_type in definition
        assert event_type in checks[PREFERENCE_CHECK][0]
    assert checks["ck_auth_refresh_sessions_auth_method_allowed"][1] is True
    assert "mfa_challenge" in checks["ck_auth_one_time_tokens_purpose_allowed"][0]
    assert "past_due" in checks["ck_billing_subscriptions_status_allowed"][0]
    assert "processed" in checks["ck_billing_webhook_events_status_allowed"][0]
    assert "ck_org_login_policies_mfa_grace_period_days_range" in checks
    assert "WHERE" in str(state["partial"]) and "active" in str(state["partial"])


async def test_0_9_0_migrations_round_trip() -> None:
    url = _url()
    _alembic(url, "upgrade", "head")
    _assert_upgraded(await _state(url))

    _alembic(url, "downgrade", BASE_REVISION)
    down = await _state(url)
    tables = down["tables"]
    columns = down["columns"]
    policies = down["policies"]
    checks = down["checks"]
    assert isinstance(tables, set) and isinstance(columns, set)
    assert isinstance(policies, dict) and isinstance(checks, dict)
    assert down["head"] == BASE_REVISION
    assert not set(NEW_TABLES) & tables
    assert not set(NEW_COLUMNS) & columns
    assert not set(NEW_TABLES) & set(policies)
    assert "ck_auth_refresh_sessions_auth_method_allowed" not in checks
    # The previous lists are back (NOT VALID, so rows with new event types do not block it).
    restored = checks[EVENT_TYPE_CHECK][0]
    assert "security_alert" in restored and "password_reset" not in restored
    assert "password_reset" not in checks[PREFERENCE_CHECK][0]

    _alembic(url, "upgrade", "head")
    _assert_upgraded(await _state(url))


async def test_downgrade_one_step_and_back() -> None:
    url = _url()
    _alembic(url, "upgrade", "head")
    _alembic(url, "downgrade", "-1")
    state = await _state(url)
    tables = state["tables"]
    assert isinstance(tables, set)
    assert state["head"] == "20261129_0002"
    assert "billing_plans" not in tables and "user_mfa_factors" in tables
    _alembic(url, "upgrade", "head")
    _assert_upgraded(await _state(url))
