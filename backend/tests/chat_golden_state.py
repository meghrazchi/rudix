"""Persisted rows of a chat golden transcript (R05-01)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.usage import UsageEvent


def _decimal(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


async def persisted_state(db_session: AsyncSession, organization_id: UUID) -> dict[str, Any]:
    db_session.expire_all()
    sessions = list(
        (
            await db_session.execute(
                select(ChatSession)
                .where(ChatSession.organization_id == organization_id)
                .order_by(ChatSession.created_at)
            )
        )
        .scalars()
        .all()
    )
    session_ids = [row.id for row in sessions]
    messages: list[ChatMessage] = []
    if session_ids:
        messages = list(
            (
                await db_session.execute(
                    select(ChatMessage).where(ChatMessage.chat_session_id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
    messages.sort(key=lambda m: (m.created_at, 0 if m.role == "user" else 1))
    message_ids = [row.id for row in messages]
    citations: list[Citation] = []
    if message_ids:
        citations = list(
            (
                await db_session.execute(
                    select(Citation).where(Citation.chat_message_id.in_(message_ids))
                )
            )
            .scalars()
            .all()
        )
    order = {message_id: index for index, message_id in enumerate(message_ids)}
    # Not by created_at: it has one-second resolution on SQLite, so ties depend on timing.
    citations.sort(key=lambda c: (order[c.chat_message_id], c.text_snippet or "", str(c.chunk_id)))
    usage = list(
        (
            await db_session.execute(
                select(UsageEvent)
                .where(UsageEvent.organization_id == organization_id)
                .order_by(UsageEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "chat_sessions": [{"id": str(row.id), "title": row.title} for row in sessions],
        "chat_messages": [
            {
                "id": str(row.id),
                "chat_session_id": str(row.chat_session_id),
                "role": row.role,
                "content": row.content,
                "confidence_score": _decimal(row.confidence_score),
                "model_name": row.model_name,
                "token_input_count": row.token_input_count,
                "token_output_count": row.token_output_count,
                "cost_usd": _decimal(row.cost_usd),
                "prompt_template_version_id": (
                    str(row.prompt_template_version_id)
                    if row.prompt_template_version_id is not None
                    else None
                ),
                "trust_metadata_json": row.trust_metadata_json,
            }
            for row in messages
        ],
        "citations": [
            {
                "chat_message_id": str(row.chat_message_id),
                "document_id": str(row.document_id),
                "chunk_id": str(row.chunk_id),
                "page_number": row.page_number,
                "text_snippet": row.text_snippet,
                "similarity_score": _decimal(row.similarity_score),
                "rerank_score": _decimal(row.rerank_score),
            }
            for row in citations
        ],
        "usage_events": [
            {
                "event_type": row.event_type,
                "model_name": row.model_name,
                "provider_key": row.provider_key,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": _decimal(row.cost_usd),
                "metadata": row.metadata_json,
            }
            for row in usage
        ],
    }
