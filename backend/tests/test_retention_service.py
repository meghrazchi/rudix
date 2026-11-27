"""R04-09: per-organisation batched retention with a frozen clock (SQLite and PostgreSQL)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")

from app.core import maintenance_metrics
from app.core.config import Settings, settings
from app.db.partitioning import EnsureResult
from app.domains.admin.repositories.retention import RETENTION_TABLES
from app.domains.admin.services.retention_service import (
    RETENTION_WINDOW_SETTINGS,
    RetentionConfig,
    RetentionService,
    effective_audit_retention_days,
    partition_drop_window_days,
)
from app.models.activity_timeline import ActivityTimelineEvent
from app.models.authorization import AuthorizationDecisionLog
from app.models.chat import ChatSession
from app.models.governance import OrganizationGovernancePolicy
from app.models.organization import Organization
from app.models.usage import AuditLog, UsageEvent
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery
from app.workers import retention_tasks

pytestmark = pytest.mark.both_dialects

NOW = datetime(2026, 11, 27, 3, 15, 0, tzinfo=UTC)
KEEP_ALL = {table: None for table in RETENTION_TABLES}


def _config(
    windows: dict[str, int | None] | None = None,
    *,
    enabled: bool = True,
    batch_size: int = 100,
    max_batches: int = 200,
) -> RetentionConfig:
    return RetentionConfig(
        enabled=enabled,
        windows={**KEEP_ALL, **(windows or {})},
        batch_size=batch_size,
        max_batches_per_run=max_batches,
    )


async def _org(session: AsyncSession) -> UUID:
    suffix = uuid4().hex
    org = Organization(name=f"Retention org {suffix}", slug=f"retention-{suffix}")
    session.add(org)
    await session.flush()
    return org.id


async def _usage(session: AsyncSession, org_id: UUID, *ages_days: float) -> None:
    for age in ages_days:
        session.add(
            UsageEvent(
                organization_id=org_id,
                event_type="chat.query",
                created_at=NOW - timedelta(days=age),
            )
        )
    await session.flush()


async def _audit(session: AsyncSession, org_id: UUID, *ages_days: float) -> None:
    for age in ages_days:
        session.add(
            AuditLog(
                organization_id=org_id,
                action="admin.test",
                resource_type="test",
                created_at=NOW - timedelta(days=age),
            )
        )
    await session.flush()


async def _count(session: AsyncSession, model: Any, org_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(model).where(model.organization_id == org_id)
    )
    return int(result.scalar_one())


async def _override(session: AsyncSession, org_id: UUID, days: int | None) -> None:
    session.add(OrganizationGovernancePolicy(organization_id=org_id, audit_log_retention_days=days))
    await session.flush()


def _deleted_metric(table: str) -> float:
    return maintenance_metrics.RETENTION_ROWS_DELETED_TOTAL.labels(table=table)._value.get()


@pytest.mark.asyncio
async def test_rows_older_than_window_deleted_newer_kept(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)  # the counter is asserted below
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 1, 29.9, 30.1, 45, 400)
    await db_session.commit()
    before = _deleted_metric("usage_events")

    result = await RetentionService().purge(
        db_session,
        now=NOW,
        config=_config({"usage_events": 30}),
        organization_ids=[org_id],
    )

    assert await _count(db_session, UsageEvent, org_id) == 2
    usage = result.tables[0]
    assert (usage.table, usage.rows_deleted, usage.organizations_purged) == ("usage_events", 3, 1)
    assert result.rows_deleted == 3
    assert result.as_dict()["tables"]["usage_events"]["rows_deleted"] == 3
    assert _deleted_metric("usage_events") - before == 3


@pytest.mark.asyncio
async def test_other_organisations_rows_untouched(db_session: AsyncSession) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    await _usage(db_session, org_a, 1, 50)
    await _usage(db_session, org_b, 1, 50)
    await db_session.commit()

    await RetentionService().purge(
        db_session, now=NOW, config=_config({"usage_events": 30}), organization_ids=[org_a]
    )

    assert await _count(db_session, UsageEvent, org_a) == 1
    assert await _count(db_session, UsageEvent, org_b) == 2


@pytest.mark.asyncio
async def test_audit_org_override_wins_over_platform_default(db_session: AsyncSession) -> None:
    default_org = await _org(db_session)
    short_org = await _org(db_session)
    long_org = await _org(db_session)
    for org_id in (default_org, short_org, long_org):
        await _audit(db_session, org_id, 10, 40, 100, 400)
    await _override(db_session, short_org, 30)
    await _override(db_session, long_org, 365)
    await db_session.commit()

    await RetentionService().purge(
        db_session,
        now=NOW,
        config=_config({"audit_logs": 90}),
        organization_ids=[default_org, short_org, long_org],
    )

    assert await _count(db_session, AuditLog, default_org) == 2  # 10, 40
    assert await _count(db_session, AuditLog, short_org) == 1  # 10
    assert await _count(db_session, AuditLog, long_org) == 3  # 10, 40, 100


@pytest.mark.asyncio
async def test_audit_override_applies_when_platform_keeps(db_session: AsyncSession) -> None:
    keep_org = await _org(db_session)
    override_org = await _org(db_session)
    for org_id in (keep_org, override_org):
        await _audit(db_session, org_id, 10, 400)
    await _override(db_session, override_org, 30)
    await db_session.commit()

    await RetentionService().purge(
        db_session, now=NOW, config=_config(), organization_ids=[keep_org, override_org]
    )

    assert await _count(db_session, AuditLog, keep_org) == 2
    assert await _count(db_session, AuditLog, override_org) == 1


@pytest.mark.asyncio
async def test_none_everywhere_keeps_everything(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 1, 5000)
    await _audit(db_session, org_id, 1, 5000)
    await db_session.commit()

    result = await RetentionService().purge(
        db_session, now=NOW, config=_config(), organization_ids=[org_id]
    )

    assert result.enabled is True
    assert result.tables == []
    assert await _count(db_session, UsageEvent, org_id) == 2
    assert await _count(db_session, AuditLog, org_id) == 2


@pytest.mark.asyncio
async def test_batch_limit_honoured_and_rerun_continues(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, *[40 + i for i in range(25)], 1)
    await db_session.commit()
    config = _config({"usage_events": 30}, batch_size=10, max_batches=2)

    first = await RetentionService().purge(
        db_session, now=NOW, config=config, organization_ids=[org_id]
    )
    assert (first.tables[0].rows_deleted, first.tables[0].batches) == (20, 2)
    assert first.tables[0].truncated is True
    assert await _count(db_session, UsageEvent, org_id) == 6
    # The oldest rows went first: the newest expired row (40 days) is still there.
    remaining = await db_session.execute(
        select(func.min(UsageEvent.created_at)).where(UsageEvent.organization_id == org_id)
    )
    oldest_left = remaining.scalar_one()
    assert oldest_left.replace(tzinfo=UTC) >= NOW - timedelta(days=45)

    second = await RetentionService().purge(
        db_session, now=NOW, config=config, organization_ids=[org_id]
    )
    assert (second.tables[0].rows_deleted, second.tables[0].truncated) == (5, False)
    assert await _count(db_session, UsageEvent, org_id) == 1


@pytest.mark.asyncio
async def test_rerun_is_noop(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 1, 60)
    await db_session.commit()
    config = _config({"usage_events": 30})

    await RetentionService().purge(db_session, now=NOW, config=config, organization_ids=[org_id])
    again = await RetentionService().purge(
        db_session, now=NOW, config=config, organization_ids=[org_id]
    )

    assert again.rows_deleted == 0
    assert (again.tables[0].batches, again.tables[0].organizations_purged) == (0, 0)
    assert await _count(db_session, UsageEvent, org_id) == 1


@pytest.mark.asyncio
async def test_kill_switch_deletes_nothing(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 60)
    await db_session.commit()

    result = await RetentionService().purge(
        db_session,
        now=NOW,
        config=_config({"usage_events": 30}, enabled=False),
        organization_ids=[org_id],
    )

    assert result.enabled is False
    assert result.as_dict() == {"enabled": False, "rows_deleted": 0, "tables": {}}
    assert await _count(db_session, UsageEvent, org_id) == 1


@pytest.mark.asyncio
async def test_all_five_tables_purged_per_window(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    user = User(organization_id=org_id, external_auth_id=uuid4().hex, email=f"{uuid4()}@x.io")
    db_session.add(user)
    await db_session.flush()
    chat = ChatSession(organization_id=org_id, user_id=user.id)
    hook = Webhook(
        organization_id=org_id,
        name="hook",
        url="https://example.com/hook",
        secret_prefix="whsec_x",
        secret_hash="0" * 64,
    )
    db_session.add_all([chat, hook])
    await db_session.flush()
    for age in (5, 50):
        created = NOW - timedelta(days=age)
        db_session.add_all(
            [
                UsageEvent(organization_id=org_id, event_type="e", created_at=created),
                AuditLog(organization_id=org_id, action="a", resource_type="r", created_at=created),
                AuthorizationDecisionLog(
                    organization_id=org_id,
                    subject_type="user",
                    subject_value="u",
                    resource_type="document",
                    action="read_only",
                    decision="allow",
                    created_at=created,
                ),
                ActivityTimelineEvent(
                    organization_id=org_id,
                    chat_session_id=chat.id,
                    sequence=age,
                    step_key="retrieve",
                    label="Retrieve",
                    created_at=created,
                ),
                WebhookDelivery(
                    webhook_id=hook.id,
                    organization_id=org_id,
                    event_type="document.indexed",
                    created_at=created,
                ),
            ]
        )
    await db_session.commit()

    result = await RetentionService().purge(
        db_session,
        now=NOW,
        config=_config({table: 30 for table in RETENTION_TABLES}),
        organization_ids=[org_id],
    )

    assert {item.table: item.rows_deleted for item in result.tables} == {
        table: 1 for table in RETENTION_TABLES
    }
    for model in (
        UsageEvent,
        AuditLog,
        AuthorizationDecisionLog,
        ActivityTimelineEvent,
        WebhookDelivery,
    ):
        assert await _count(db_session, model, org_id) == 1


@pytest.mark.asyncio
async def test_without_org_filter_walks_every_organisation(db_session: AsyncSession) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    await _usage(db_session, org_a, 60)
    await _usage(db_session, org_b, 60, 1)
    await db_session.commit()

    result = await RetentionService().purge(
        db_session, now=NOW, config=_config({"usage_events": 30})
    )

    assert result.rows_deleted >= 2
    assert await _count(db_session, UsageEvent, org_a) == 0
    assert await _count(db_session, UsageEvent, org_b) == 1


@pytest.mark.asyncio
async def test_empty_org_filter_deletes_nothing(db_session: AsyncSession) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 60)
    await db_session.commit()

    result = await RetentionService().purge(
        db_session, now=NOW, config=_config({"usage_events": 30}), organization_ids=[]
    )

    assert result.rows_deleted == 0
    assert await _count(db_session, UsageEvent, org_id) == 1


@pytest.mark.asyncio
async def test_purge_task_uses_maintenance_session(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id = await _org(db_session)
    await _usage(db_session, org_id, 60, 1)
    await db_session.commit()

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(retention_tasks, "maintenance_session", _session)
    monkeypatch.setattr(settings, "retention_usage_events_days", 30)

    summary = await retention_tasks._purge_async(NOW)

    assert summary["enabled"] is True
    assert summary["tables"]["usage_events"]["rows_deleted"] >= 1
    assert await _count(db_session, UsageEvent, org_id) == 1


@pytest.mark.asyncio
async def test_ensure_task_is_noop_on_unpartitioned_tables(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(retention_tasks, "maintenance_session", _session)

    summary = await retention_tasks._ensure_partitions_async(NOW)

    assert summary["failed"] == 0
    assert summary["tables"] == {table: {"partitioned": False} for table in RETENTION_TABLES}


def test_effective_audit_retention() -> None:
    assert effective_audit_retention_days(None, None) is None
    assert effective_audit_retention_days(None, 90) == 90
    assert effective_audit_retention_days(45, 90) == 45
    assert effective_audit_retention_days(400, None) == 400


def test_partition_drop_window() -> None:
    org = uuid4()
    cfg = _config({"audit_logs": 90, "usage_events": 30})
    assert partition_drop_window_days("usage_events", config=cfg, audit_overrides={}) == 30
    assert partition_drop_window_days("webhook_deliveries", config=cfg, audit_overrides={}) is None
    assert partition_drop_window_days("audit_logs", config=cfg, audit_overrides={org: 30}) == 90
    assert partition_drop_window_days("audit_logs", config=cfg, audit_overrides={org: 365}) == 365
    assert partition_drop_window_days("audit_logs", config=cfg, audit_overrides={}) == 90
    disabled = replace(cfg, enabled=False)
    assert partition_drop_window_days("usage_events", config=disabled, audit_overrides={}) is None


def test_config_from_settings_defaults_keep_everything() -> None:
    cfg = RetentionConfig.from_settings()
    assert set(cfg.windows) == set(RETENTION_TABLES) == set(RETENTION_WINDOW_SETTINGS)
    assert cfg.enabled is True
    assert all(value is None for value in cfg.windows.values())
    assert (cfg.batch_size, cfg.max_batches_per_run) == (5000, 200)


def test_settings_reject_windows_below_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETENTION_USAGE_EVENTS_DAYS", "6")
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]
    monkeypatch.setenv("RETENTION_USAGE_EVENTS_DAYS", "7")
    monkeypatch.setenv("RETENTION_AUDIT_LOGS_DAYS", "29")
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]
    monkeypatch.setenv("RETENTION_AUDIT_LOGS_DAYS", "30")
    monkeypatch.setenv("RETENTION_DELETE_BATCH_SIZE", "99")
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]
    monkeypatch.setenv("RETENTION_DELETE_BATCH_SIZE", "100")
    loaded = Settings()  # type: ignore[call-arg]
    assert (loaded.retention_usage_events_days, loaded.retention_audit_logs_days) == (7, 30)


@pytest.mark.asyncio
async def test_ensure_task_reports_failures_and_continues(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _boom(*_: object, **__: object) -> None:
        raise TimeoutError("lock timeout")

    reported: list[str] = []

    async def _report(_conn: object, table: str, *, now: datetime) -> bool:
        reported.append(table)
        raise RuntimeError("still down")

    monkeypatch.setattr(retention_tasks, "maintenance_session", _session)
    monkeypatch.setattr(retention_tasks, "ensure_future_partitions", _boom)
    monkeypatch.setattr(retention_tasks, "report_missing_partition", _report)

    summary = await retention_tasks._ensure_partitions_async(NOW)

    assert summary["failed"] == len(RETENTION_TABLES)
    assert summary["tables"]["usage_events"] == {"error_type": "TimeoutError"}
    assert reported == list(RETENTION_TABLES)


@pytest.mark.asyncio
async def test_ensure_task_drops_expired_on_partitioned_table(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _ensure(_conn: object, table: str, *, now: datetime) -> EnsureResult:
        return EnsureResult(table=table, partitioned=table == "usage_events", created=("p",))

    cutoffs: list[datetime] = []

    async def _drop(_conn: object, table: str, *, cutoff: datetime) -> list[str]:
        cutoffs.append(cutoff)
        return [f"{table}_p202601"]

    monkeypatch.setattr(retention_tasks, "maintenance_session", _session)
    monkeypatch.setattr(retention_tasks, "ensure_future_partitions", _ensure)
    monkeypatch.setattr(retention_tasks, "drop_expired_partitions", _drop)
    monkeypatch.setattr(settings, "retention_usage_events_days", 30)

    summary = await retention_tasks._ensure_partitions_async(NOW)

    assert summary["tables"]["usage_events"] == {
        "partitioned": True,
        "created": ["p"],
        "dropped": ["usage_events_p202601"],
        "next_month_missing": False,
    }
    assert cutoffs == [NOW - timedelta(days=30)]
    assert summary["tables"]["audit_logs"] == {"partitioned": False}


def test_metric_helpers_respect_metrics_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    gauge = maintenance_metrics.PARTITION_MISSING
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before = _deleted_metric("webhook_deliveries")
    maintenance_metrics.record_retention_rows_deleted("webhook_deliveries", 3)
    maintenance_metrics.record_retention_rows_deleted("webhook_deliveries", 0)
    assert _deleted_metric("webhook_deliveries") - before == 3
    maintenance_metrics.set_partition_missing("probe_table", True)
    assert gauge.labels(table="probe_table")._value.get() == 1
    monkeypatch.setattr(settings, "metrics_enabled", False)
    maintenance_metrics.record_retention_rows_deleted("webhook_deliveries", 5)
    maintenance_metrics.set_partition_missing("probe_table", False)
    assert _deleted_metric("webhook_deliveries") - before == 3
    assert gauge.labels(table="probe_table")._value.get() == 1
