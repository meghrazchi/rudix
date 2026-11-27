"""Soft RLS mode detection and session-context wiring on SQLite (R04-08)."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import dependencies
from app.auth.models import AuthenticatedPrincipal
from app.core.config import Environment, RlsEnforcement, Settings, settings
from app.core.metrics import registry
from app.db import tenant_context
from app.db.tenant_context import (
    RLS_MAINTENANCE_INFO_KEY,
    SESSION_CONTEXT_MARKER,
    apply_tenant_context,
    bind_session_tenant,
    build_session_context_statement,
)
from app.models.api_key import ApiKey
from app.models.collection import Collection
from app.models.document import Document
from app.models.organization import Organization


class _RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture
def soft_log(monkeypatch: pytest.MonkeyPatch) -> Iterator[_RecordingLogger]:
    recorder = _RecordingLogger()
    monkeypatch.setattr(tenant_context, "_rls_logger", recorder)
    monkeypatch.setattr(tenant_context, "_soft_denial_last_logged", {})
    yield recorder


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: RlsEnforcement | None) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", mode)


def _denials(table: str) -> float:
    value = registry.get_sample_value("rudix_rls_soft_denials_total", {"table": table})
    return float(value or 0.0)


# --- settings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "configured", "expected"),
    [
        (Environment.development, None, RlsEnforcement.off),
        (Environment.test, None, RlsEnforcement.off),
        (Environment.staging, None, RlsEnforcement.soft),
        (Environment.production, None, RlsEnforcement.soft),
        (Environment.production, RlsEnforcement.strict, RlsEnforcement.strict),
        (Environment.development, RlsEnforcement.soft, RlsEnforcement.soft),
        (Environment.staging, RlsEnforcement.off, RlsEnforcement.off),
    ],
)
def test_effective_rls_enforcement(
    environment: Environment, configured: RlsEnforcement | None, expected: RlsEnforcement
) -> None:
    config = settings.model_copy(update={"environment": environment, "rls_enforcement": configured})
    assert config.effective_rls_enforcement == expected


def test_strict_is_not_the_default() -> None:
    assert Settings.model_fields["rls_enforcement"].default is None
    for environment in Environment:
        config = settings.model_copy(update={"environment": environment, "rls_enforcement": None})
        assert config.effective_rls_enforcement != RlsEnforcement.strict


# --- session-context statement ----------------------------------------------------------


def test_context_statement_sets_org_and_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    org = uuid4()
    built = build_session_context_statement(org, RlsEnforcement.strict, include_tenant=True)
    assert built is not None
    sql, params = built
    assert sql.startswith(f"{SESSION_CONTEXT_MARKER} SELECT ")
    assert "set_config('app.current_organization_id', :org, true)" in sql
    assert "set_config('app.rls_mode', :mode, true)" in sql
    assert params == {"org": str(org), "mode": "strict"}


def test_context_statement_strict_without_org_sends_empty_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    built = build_session_context_statement(None, RlsEnforcement.strict, include_tenant=True)
    assert built is not None
    assert built[1] == {"org": "", "mode": "strict"}


def test_context_statement_none_when_nothing_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    assert build_session_context_statement(None, RlsEnforcement.off, include_tenant=False) is None


def test_context_statement_pgbouncer_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    monkeypatch.setattr(settings, "db_statement_timeout_ms", 30000)
    monkeypatch.setattr(settings, "db_idle_in_transaction_timeout_ms", 60000)
    built = build_session_context_statement(None, RlsEnforcement.off, include_tenant=False)
    assert built is not None
    sql, params = built
    assert "app.current_organization_id" not in sql
    assert "set_config('statement_timeout', :statement_timeout, true)" in sql
    assert "set_config('idle_in_transaction_session_timeout', :idle_timeout, true)" in sql
    assert params == {"statement_timeout": "30000", "idle_timeout": "60000"}


def test_context_statement_pgbouncer_without_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_pgbouncer_mode", True)
    monkeypatch.setattr(settings, "db_statement_timeout_ms", 0)
    monkeypatch.setattr(settings, "db_idle_in_transaction_timeout_ms", 0)
    assert build_session_context_statement(None, RlsEnforcement.off, include_tenant=False) is None


@pytest.mark.parametrize(
    ("mode", "bound", "maintenance", "expect_tenant"),
    [
        (RlsEnforcement.off, True, False, False),
        (RlsEnforcement.soft, False, False, False),
        (RlsEnforcement.soft, True, False, True),
        (RlsEnforcement.strict, False, False, True),
        (RlsEnforcement.strict, True, True, False),
    ],
)
def test_context_statement_for_session(
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement,
    bound: bool,
    maintenance: bool,
    expect_tenant: bool,
) -> None:
    _set_mode(monkeypatch, mode)
    monkeypatch.setattr(settings, "db_pgbouncer_mode", False)
    info: dict[str, Any] = {"organization_id": uuid4() if bound else None}
    if maintenance:
        info[RLS_MAINTENANCE_INFO_KEY] = True
    built = tenant_context._context_statement_for(SimpleNamespace(info=info))
    assert (built is not None) is expect_tenant


async def test_apply_tenant_context_is_noop_on_sqlite(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.strict)
    await apply_tenant_context(db_session)  # not in a transaction: nothing to do
    await db_session.execute(select(Organization).limit(1))
    assert db_session.in_transaction()
    await apply_tenant_context(db_session)  # SQLite: skipped without error


# --- soft-mode detector -----------------------------------------------------------------


async def test_soft_mode_logs_and_counts_unbound_select(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    before = _denials("documents")
    await db_session.execute(select(Document))
    assert _denials("documents") == before + 1
    assert soft_log.events == [("rls.soft_denial", {"table": "documents", "operation": "select"})]


async def test_soft_mode_throttles_logs_but_counts_every_statement(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    clock = [1000.0]
    monkeypatch.setattr(tenant_context.time, "monotonic", lambda: clock[0])
    before = _denials("collections")
    await db_session.execute(select(Collection))
    await db_session.execute(select(Collection))
    assert _denials("collections") == before + 2
    assert len(soft_log.events) == 1
    clock[0] += tenant_context.SOFT_DENIAL_LOG_INTERVAL_SECONDS
    await db_session.execute(select(Collection))
    assert len(soft_log.events) == 2


async def test_soft_mode_counts_unbound_flush(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    org_id = uuid4()
    db_session.add(Organization(id=org_id, name="Org", slug=f"org-{org_id.hex[:8]}"))
    await db_session.flush()
    _set_mode(monkeypatch, RlsEnforcement.soft)
    before = _denials("collections")
    collection = Collection(organization_id=org_id, name="Soft")
    db_session.add(collection)
    await db_session.flush()
    collection.name = "Soft 2"
    await db_session.flush()
    await db_session.delete(collection)
    await db_session.flush()
    assert _denials("collections") == before + 3
    operations = [fields["operation"] for _, fields in soft_log.events]
    assert operations == ["insert"]  # later log lines for the same table are throttled


async def test_soft_mode_ignores_bound_session(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    bind_session_tenant(db_session, uuid4())
    before = _denials("documents")
    await db_session.execute(select(Document))
    assert _denials("documents") == before
    assert soft_log.events == []


async def test_soft_mode_uses_context_var_tenant(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    token = tenant_context._CURRENT_TENANT_ID.set(uuid4())
    try:
        before = _denials("documents")
        await db_session.execute(select(Document))
        assert _denials("documents") == before
    finally:
        tenant_context._CURRENT_TENANT_ID.reset(token)
    assert soft_log.events == []


async def test_soft_mode_ignores_maintenance_session(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    db_session.info[RLS_MAINTENANCE_INFO_KEY] = True
    before = _denials("documents")
    await db_session.execute(select(Document))
    assert _denials("documents") == before
    assert soft_log.events == []


async def test_soft_mode_ignores_lookup_tables(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, soft_log: _RecordingLogger
) -> None:
    _set_mode(monkeypatch, RlsEnforcement.soft)
    before = _denials("api_keys")
    await db_session.execute(select(ApiKey))
    assert _denials("api_keys") == before
    assert soft_log.events == []


@pytest.mark.parametrize("mode", [RlsEnforcement.off, RlsEnforcement.strict])
async def test_detector_inactive_outside_soft(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    soft_log: _RecordingLogger,
    mode: RlsEnforcement,
) -> None:
    _set_mode(monkeypatch, mode)
    before = _denials("documents")
    await db_session.execute(select(Document))
    assert _denials("documents") == before
    assert soft_log.events == []


# --- get_current_principal --------------------------------------------------------------


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(uuid4()),
        organization_id=str(uuid4()),
        roles=["member"],
        auth_provider="app",
    )


@pytest.mark.parametrize(
    ("mode", "expect_guard"),
    [
        (RlsEnforcement.off, False),
        (RlsEnforcement.soft, False),
        (RlsEnforcement.strict, True),
    ],
)
async def test_get_current_principal_binds_and_applies_context(
    monkeypatch: pytest.MonkeyPatch, mode: RlsEnforcement, expect_guard: bool
) -> None:
    _set_mode(monkeypatch, mode)
    principal = _principal()
    monkeypatch.setattr(
        dependencies, "authenticate_bearer_request", AsyncMock(return_value=principal)
    )
    apply_spy = AsyncMock()
    monkeypatch.setattr(dependencies, "apply_tenant_context", apply_spy)
    session = MagicMock()
    session.info = {}
    request = SimpleNamespace(state=SimpleNamespace())

    result = await dependencies.get_current_principal(request, session)  # type: ignore[arg-type]

    assert result is principal
    apply_spy.assert_awaited_once_with(session)
    assert str(session.info["organization_id"]) == principal.organization_id
    assert session.info.get("enforce_tenant_guard", False) is expect_guard
