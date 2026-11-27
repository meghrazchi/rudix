"""Hot queries can use an index on PostgreSQL (R04-02).

The test tables are empty, so the planner would pick a sequential scan on cost alone.
``SET LOCAL enable_seqscan = off`` makes a sequential scan the last resort: when a plan
still shows ``Seq Scan`` on the target table, no usable index exists. This proves the
indexes are usable for these query shapes, not that the planner prefers them on real data.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.auth_session import AuthRefreshSession
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.document import Document
from app.models.notification import Notification
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog, UsageEvent

pytestmark = pytest.mark.requires_postgres

ORG_ID = UUID("00000000-0000-4000-8000-0000000000a1")
USER_ID = UUID("00000000-0000-4000-8000-0000000000b1")
SESSION_ID = UUID("00000000-0000-4000-8000-0000000000c1")
MESSAGE_IDS = [UUID(f"00000000-0000-4000-8000-0000000000d{i}") for i in range(1, 4)]
RANGE_END = datetime(2026, 11, 27, tzinfo=UTC)
RANGE_START = RANGE_END - timedelta(days=30)


@dataclass(frozen=True)
class HotQuery:
    name: str
    table: str
    statement: Select[Any]
    expected_indexes: frozenset[str]


HOT_QUERIES = (
    HotQuery(
        "document_list",
        "documents",
        select(Document.id)
        .where(Document.organization_id == ORG_ID)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(20),
        frozenset({"idx_documents_org_created"}),
    ),
    HotQuery(
        "session_list",
        "chat_sessions",
        select(ChatSession.id)
        .where(ChatSession.organization_id == ORG_ID, ChatSession.user_id == USER_ID)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(20),
        frozenset({"idx_chat_sessions_org_user_updated"}),
    ),
    HotQuery(
        "message_list",
        "chat_messages",
        select(ChatMessage.id)
        .where(ChatMessage.chat_session_id == SESSION_ID)
        .order_by(ChatMessage.created_at),
        frozenset({"idx_chat_messages_session"}),
    ),
    HotQuery(
        "citations_by_messages",
        "citations",
        select(Citation.id).where(Citation.chat_message_id.in_(MESSAGE_IDS)),
        frozenset({"idx_citations_message"}),
    ),
    HotQuery(
        "notification_list",
        "notifications",
        select(Notification.id)
        .where(Notification.user_id == USER_ID, Notification.organization_id == ORG_ID)
        .order_by(Notification.created_at.desc())
        .limit(20),
        # Either index serves this shape; on empty tables the choice is not meaningful.
        frozenset({"idx_notifications_user_org", "idx_notifications_org_created"}),
    ),
    HotQuery(
        "audit_log_range",
        "audit_logs",
        select(AuditLog.id)
        .where(
            AuditLog.organization_id == ORG_ID,
            AuditLog.created_at >= RANGE_START,
            AuditLog.created_at < RANGE_END,
        )
        .order_by(AuditLog.created_at.desc()),
        frozenset({"idx_audit_logs_org_created"}),
    ),
    HotQuery(
        "usage_event_range",
        "usage_events",
        select(UsageEvent.id).where(
            UsageEvent.organization_id == ORG_ID,
            UsageEvent.created_at >= RANGE_START,
            UsageEvent.created_at < RANGE_END,
        ),
        frozenset({"idx_usage_org_created", "idx_usage_org_provider_created"}),
    ),
    HotQuery(
        "memberships_by_user",
        "organization_members",
        select(OrganizationMember.id).where(OrganizationMember.user_id == USER_ID),
        frozenset({"idx_organization_members_user"}),
    ),
    HotQuery(
        "api_key_by_hash",
        "api_keys",
        select(ApiKey.id).where(ApiKey.key_hash == "0" * 64),
        frozenset({"uq_api_keys_key_hash", "idx_api_keys_key_hash"}),
    ),
    HotQuery(
        "auth_session_by_id",
        "auth_refresh_sessions",
        select(AuthRefreshSession.id).where(AuthRefreshSession.session_id == SESSION_ID),
        frozenset({"idx_auth_refresh_sessions_session"}),
    ),
)


def _plan_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


async def _explain(session: AsyncSession, statement: Select[Any]) -> list[dict[str, Any]]:
    bind = session.get_bind()
    sql = str(statement.compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True}))
    raw = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"))).scalar_one()
    document = json.loads(raw) if isinstance(raw, str) else raw
    return _plan_nodes(document[0]["Plan"])


def test_hot_query_list_covers_ten_queries() -> None:
    assert len({query.name for query in HOT_QUERIES}) == 10


@pytest.mark.parametrize("query", HOT_QUERIES, ids=lambda query: query.name)
async def test_hot_query_uses_an_index(pg_session: AsyncSession, query: HotQuery) -> None:
    await pg_session.execute(text("SET LOCAL enable_seqscan = off"))
    nodes = await _explain(pg_session, query.statement)

    seq_scans = [
        node
        for node in nodes
        if node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == query.table
    ]
    assert not seq_scans, f"{query.name}: sequential scan on {query.table}"

    used = {str(node["Index Name"]) for node in nodes if "Index Name" in node}
    assert used & query.expected_indexes, (
        f"{query.name}: expected one of {sorted(query.expected_indexes)}, plan used "
        f"{sorted(used) or 'no index'}"
    )
