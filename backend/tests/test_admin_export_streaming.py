"""R04-04: streamed admin exports are byte-identical to the old in-memory exports.

The oracle functions below are copies of the pre-streaming handler bodies (load all rows,
slice in Python for usage, ``json.dumps(payload, sort_keys=True)``), applied to the same
rows. The streamed responses must match them byte for byte, with the limit pushed to SQL.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.interfaces.http.admin as admin_api
from app.application.admin import exports
from app.models.usage import AuditLog, UsageEvent
from tests.list_endpoint_seed import Tenant, api_client, configure_app_auth, seed_tenant
from tests.query_count import count_queries

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

FIXED_NOW = datetime.now(UTC)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> _FixedDatetime:  # type: ignore[override]
        moment = FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)
        return cls.combine(moment.date(), moment.timetz())


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_app_auth(monkeypatch)
    monkeypatch.setattr(admin_api, "datetime", _FixedDatetime)
    # Small batches so the multi-batch path (header once, item separators) is exercised.
    monkeypatch.setattr(exports, "EXPORT_BATCH_SIZE", 2)


def _range() -> tuple[date, date]:
    today = FIXED_NOW.date()
    return today - timedelta(days=6), today + timedelta(days=1)


# ── oracle: the old export code, verbatim apart from taking rows as input ─────────────


def _old_usage_csv(events: list[UsageEvent]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "created_at",
            "organization_id",
            "user_id",
            "event_type",
            "model_name",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
        ],
    )
    writer.writeheader()
    for e in events:
        writer.writerow(
            {
                "id": str(e.id),
                "created_at": e.created_at.isoformat(),
                "organization_id": str(e.organization_id),
                "user_id": str(e.user_id) if e.user_id else "",
                "event_type": e.event_type,
                "model_name": e.model_name or "",
                "input_tokens": e.input_tokens if e.input_tokens is not None else "",
                "output_tokens": e.output_tokens if e.output_tokens is not None else "",
                "estimated_cost_usd": str(e.cost_usd) if e.cost_usd is not None else "",
            }
        )
    return output.getvalue()


def _old_usage_json(
    events: list[UsageEvent], organization_id: UUID, resolved: tuple[date, date], limit: int
) -> str:
    resolved_from, resolved_to = resolved
    payload = {
        "organization_id": str(organization_id),
        "exported_at": FIXED_NOW.isoformat(),
        "is_cost_estimate": True,
        "range": {"from": resolved_from.isoformat(), "to": resolved_to.isoformat()},
        "returned": len(events),
        "max_rows": limit,
        "items": [
            {
                "id": str(e.id),
                "created_at": e.created_at.isoformat(),
                "organization_id": str(e.organization_id),
                "user_id": str(e.user_id) if e.user_id else None,
                "event_type": e.event_type,
                "model_name": e.model_name,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "estimated_cost_usd": str(e.cost_usd) if e.cost_usd is not None else None,
            }
            for e in events
        ],
    }
    return json.dumps(payload, sort_keys=True)


def _old_audit_json(
    items: list[Any], organization_id: UUID, resolved: tuple[date, date], limit: int
) -> str:
    resolved_from, resolved_to = resolved
    payload = {
        "organization_id": str(organization_id),
        "exported_at": FIXED_NOW.isoformat(),
        "range": {"from": resolved_from.isoformat(), "to": resolved_to.isoformat()},
        "filters": {
            "actor": None,
            "user_id": None,
            "action": None,
            "entity": None,
            "resource_id": None,
            "document_id": None,
            "collection_id": None,
            "request_id": None,
            "session_id": None,
            "ip_address": None,
            "result": "all",
            "severity": None,
            "search": None,
        },
        "returned": len(items),
        "max_rows": limit,
        "items": [item.model_dump(mode="json") for item in items],
    }
    return json.dumps(payload, sort_keys=True)


# ── seeding ────────────────────────────────────────────────────────────────────────────


def _seed_usage(db_session: AsyncSession, tenant: Tenant, count: int) -> None:
    db_session.add_all(
        UsageEvent(
            organization_id=tenant.org_id,
            user_id=tenant.user.id if index % 2 else None,
            event_type="chat.completion",
            model_name="model-a" if index % 3 else None,
            input_tokens=index * 10,
            output_tokens=None if index == 1 else index,
            cost_usd=Decimal("0.001200") if index % 2 else None,
            metadata_json={"note": 'naïve, "quoted"'},
        )
        for index in range(count)
    )


def _seed_audit(db_session: AsyncSession, tenant: Tenant, count: int) -> None:
    db_session.add_all(
        AuditLog(
            organization_id=tenant.org_id,
            user_id=tenant.user.id,
            action="document.viewed",
            resource_type="document",
            resource_id=uuid4(),
            metadata_json={
                "request_id": f"req-{index}",
                "ip_address": "10.0.0.1",
                "note": "line,with\ncomma ünicode",
                "api_key": "should-be-redacted",
            },
        )
        for index in range(count)
    )


async def _usage_rows(db_session: AsyncSession, tenant: Tenant) -> list[UsageEvent]:
    result = await db_session.execute(
        select(UsageEvent)
        .where(UsageEvent.organization_id == tenant.org_id)
        .order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
    )
    return list(result.scalars().all())


async def _audit_items(db_session: AsyncSession, tenant: Tenant) -> list[Any]:
    result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.organization_id == tenant.org_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    return [admin_api._to_audit_log_item(log) for log in result.scalars().all()]


async def _export(
    client: AsyncClient, db_session: AsyncSession, tenant: Tenant, url: str
) -> tuple[bytes, Any, list[str]]:
    resolved_from, resolved_to = _range()
    full = f"{url}&from={resolved_from.isoformat()}&to={resolved_to.isoformat()}"
    async with count_queries(db_session) as counter:
        response = await client.get(full, headers=tenant.headers)
    assert response.status_code == 200, response.text
    return response.content, response.headers, counter.statements


# ── tests ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count,limit", [(0, 10), (5, 10), (7, 4)])
async def test_usage_export_matches_old_bytes(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, count: int, limit: int
) -> None:
    tenant = await seed_tenant(db_session)
    other = await seed_tenant(db_session)
    _seed_usage(db_session, tenant, count)
    _seed_usage(db_session, other, 3)
    await db_session.commit()
    events = (await _usage_rows(db_session, tenant))[:limit]

    async with api_client(monkeypatch, db_session) as client:
        csv_body, headers, statements = await _export(
            client, db_session, tenant, f"/api/v1/admin/usage/export?format=csv&limit={limit}"
        )
        assert csv_body == _old_usage_csv(events).encode()
        assert headers["content-type"] == "text/csv; charset=utf-8"
        resolved_from, resolved_to = _range()
        assert headers["content-disposition"] == (
            f'attachment; filename="usage-{resolved_from.isoformat()}-'
            f'{resolved_to.isoformat()}.csv"'
        )
        usage_selects = [s for s in statements if "FROM usage_events" in s]
        assert usage_selects and all("LIMIT" in s.upper() for s in usage_selects)

        json_body, headers, _ = await _export(
            client, db_session, tenant, f"/api/v1/admin/usage/export?format=json&limit={limit}"
        )
        assert json_body == _old_usage_json(events, tenant.org_id, _range(), limit).encode()
        assert headers["content-type"] == "application/json"
        assert json.loads(json_body)["returned"] == min(count, limit)


@pytest.mark.parametrize("count,limit", [(0, 10), (5, 10), (7, 3)])
async def test_audit_export_matches_old_bytes(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, count: int, limit: int
) -> None:
    tenant = await seed_tenant(db_session)
    other = await seed_tenant(db_session)
    _seed_audit(db_session, tenant, count)
    _seed_audit(db_session, other, 2)
    await db_session.commit()
    items = (await _audit_items(db_session, tenant))[:limit]

    async with api_client(monkeypatch, db_session) as client:
        csv_body, headers, statements = await _export(
            client, db_session, tenant, f"/api/v1/admin/audit-logs/export?format=csv&limit={limit}"
        )
        assert csv_body == admin_api._serialize_audit_logs_csv(items).encode()
        assert b"should-be-redacted" not in csv_body
        assert headers["content-disposition"].startswith('attachment; filename="audit-logs-')
        audit_selects = [s for s in statements if "FROM audit_logs" in s]
        assert audit_selects and all("LIMIT" in s.upper() for s in audit_selects)

        json_body, _, _ = await _export(
            client,
            db_session,
            tenant,
            f"/api/v1/admin/audit-logs/export?format=json&limit={limit}",
        )
        assert json_body == _old_audit_json(items, tenant.org_id, _range(), limit).encode()
        assert b"should-be-redacted" not in json_body


async def test_stream_json_rejects_misordered_keys() -> None:
    async def _no_batches() -> Any:
        if False:  # pragma: no cover - empty async generator
            yield []

    with pytest.raises(ValueError):
        async for _ in exports.stream_json(
            head={"organization_id": "x"}, batches=_no_batches(), tail=lambda _: {}
        ):
            pass
    chunks = [
        chunk
        async for chunk in exports.stream_json(head={}, batches=_no_batches(), tail=lambda _: {})
    ]
    assert "".join(chunks) == json.dumps({"items": []}, sort_keys=True)


async def test_logged_stream_reports_failure() -> None:
    async def _broken() -> Any:
        yield "partial"
        raise RuntimeError("boom")

    received: list[str] = []
    with pytest.raises(RuntimeError):
        async for chunk in exports.logged_stream(
            _broken(),
            export="usage",
            export_format="csv",
            organization_id=uuid4(),
            user_id=None,
        ):
            received.append(chunk)
    assert received == ["partial"]
