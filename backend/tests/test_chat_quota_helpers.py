"""Unit tests for app.application.chat.quota and the chat quota-denied metric (R02-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.application.chat import quota as chat_quota
from app.core import metrics
from app.core.config import settings
from app.domains.quota.schemas.quota_schemas import QuotaType

_PLAN_LIMIT = HTTPException(
    status_code=403,
    detail={
        "code": "plan_limit_exceeded",
        "message": "Chat Questions usage would exceed the plan limit (1/0).",
        "quota_type": "questions",
        "organization_id": "org-secret",
        "current_value": 0,
        "retryable": True,
        "next_reset_at": "2026-11-27T00:00:00+00:00",
    },
)


def _counter_value(transport: str) -> float:
    return metrics.CHAT_QUOTA_DENIED_TOTAL.labels(transport=transport)._value.get()


def test_chat_quota_denial_returns_only_safe_fields() -> None:
    assert chat_quota.chat_quota_denial(_PLAN_LIMIT) == {
        "quota_type": "questions",
        "retryable": True,
        "next_reset_at": "2026-11-27T00:00:00+00:00",
    }


@pytest.mark.parametrize(
    "exc",
    [
        HTTPException(status_code=403, detail="No active organization context for principal"),
        HTTPException(status_code=403, detail={"code": "forbidden"}),
    ],
)
def test_chat_quota_denial_ignores_other_errors(exc: HTTPException) -> None:
    assert chat_quota.chat_quota_denial(exc) is None


@pytest.mark.asyncio
async def test_ensure_chat_quota_passes_today_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure = AsyncMock()
    monkeypatch.setattr(chat_quota.plan_enforcement_service, "ensure_within_limit", ensure)
    org_id = uuid4()
    session = AsyncMock()

    await chat_quota.ensure_chat_quota(session, organization_id=org_id, transport="http")

    ensure.assert_awaited_once_with(
        session,
        organization_id=org_id,
        quota_type=QuotaType.questions,
        requested_amount=1,
        resource="chat questions",
        guidance="Upgrade your plan or reduce chat volume.",
    )


@pytest.mark.asyncio
async def test_ensure_chat_quota_counts_denial_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(
        chat_quota.plan_enforcement_service,
        "ensure_within_limit",
        AsyncMock(side_effect=_PLAN_LIMIT),
    )
    before = _counter_value("ws")

    with pytest.raises(HTTPException) as raised:
        await chat_quota.ensure_chat_quota(AsyncMock(), organization_id=uuid4(), transport="ws")

    assert raised.value is _PLAN_LIMIT
    assert _counter_value("ws") == before + 1


@pytest.mark.asyncio
async def test_ensure_chat_quota_does_not_count_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    other = HTTPException(status_code=500, detail="boom")
    monkeypatch.setattr(
        chat_quota.plan_enforcement_service,
        "ensure_within_limit",
        AsyncMock(side_effect=other),
    )
    before = _counter_value("http")

    with pytest.raises(HTTPException) as raised:
        await chat_quota.ensure_chat_quota(AsyncMock(), organization_id=uuid4(), transport="http")

    assert raised.value is other
    assert _counter_value("http") == before


@pytest.mark.asyncio
async def test_record_chat_usage_records_one_question(monkeypatch: pytest.MonkeyPatch) -> None:
    record = AsyncMock()
    monkeypatch.setattr(chat_quota.plan_enforcement_service, "record_usage", record)
    org_id = uuid4()
    session = AsyncMock()

    await chat_quota.record_chat_usage(session, organization_id=org_id)

    record.assert_awaited_once_with(
        session, organization_id=org_id, quota_type=QuotaType.questions, amount=1
    )


def test_record_chat_quota_denied_is_noop_when_metrics_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    before = _counter_value("http")

    metrics.record_chat_quota_denied("http")

    assert _counter_value("http") == before


def test_record_chat_quota_denied_swallows_metric_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)

    class _Broken:
        def labels(self, **_kwargs: str) -> object:
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr(metrics, "CHAT_QUOTA_DENIED_TOTAL", _Broken())

    metrics.record_chat_quota_denied("ws")
