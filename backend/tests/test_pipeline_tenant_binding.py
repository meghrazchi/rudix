"""Tenant binding of chat pipeline sessions (R05-02, plan contract 4.2.9)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RlsEnforcement, settings
from app.db.tenant_context import (
    bind_pipeline_session,
    get_current_tenant_id,
    tenant_context_scope,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]


@pytest.mark.parametrize(
    ("mode", "guard"),
    [(RlsEnforcement.strict, True), (RlsEnforcement.soft, False), (RlsEnforcement.off, False)],
)
async def test_bind_pipeline_session_binds_tenant_and_guard_by_mode(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement,
    guard: bool,
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    organization_id = uuid4()
    db_session.info.pop("enforce_tenant_guard", None)

    with tenant_context_scope(None):
        bound = await bind_pipeline_session(db_session, str(organization_id))

        assert bound == organization_id
        assert db_session.info["organization_id"] == organization_id
        assert bool(db_session.info.get("enforce_tenant_guard")) is guard
        assert get_current_tenant_id() == organization_id


async def test_bind_pipeline_session_sets_postgres_context_for_open_transaction(
    db_session: AsyncSession,
    db_backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    organization_id = uuid4()
    await db_session.execute(text("SELECT 1"))  # an open transaction

    await bind_pipeline_session(db_session, organization_id)

    if db_backend == "postgres":
        value = await db_session.scalar(
            text("SELECT current_setting('app.current_organization_id', true)")
        )
        assert value == str(organization_id)
        mode = await db_session.scalar(text("SELECT current_setting('app.rls_mode', true)"))
        assert mode == "strict"
    db_session.info.pop("enforce_tenant_guard", None)


async def test_tenant_context_scope_restores_previous_value_and_reaches_child_tasks() -> None:
    outer, inner = uuid4(), uuid4()
    seen: list[object] = []

    async def child() -> None:
        seen.append(get_current_tenant_id())

    with tenant_context_scope(outer):
        with tenant_context_scope(str(inner)) as bound:
            assert bound == inner
            await asyncio.gather(asyncio.create_task(child()))
        assert get_current_tenant_id() == outer
    assert seen == [inner]
