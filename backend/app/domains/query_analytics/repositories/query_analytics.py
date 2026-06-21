from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.message_feedback import MessageFeedback
from app.models.query_analytics import KnowledgeGap


class QueryAnalyticsRepository:
    async def count_user_messages(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
        )
        return result.scalar_one() or 0

    async def load_assistant_messages(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[ChatMessage]:
        result = await session.execute(
            select(ChatMessage)
            .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= from_dt,
                ChatMessage.created_at <= to_dt,
            )
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars().all())

    async def load_feedback(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[MessageFeedback]:
        result = await session.execute(
            select(MessageFeedback).where(
                MessageFeedback.organization_id == organization_id,
                MessageFeedback.created_at >= from_dt,
                MessageFeedback.created_at <= to_dt,
            )
        )
        return list(result.scalars().all())

    # ── Knowledge gap CRUD ─────────────────────────────────────────────────────

    async def create_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_type: str,
        topic_label: str,
        description: str | None = None,
        gap_source: str = "admin",
        occurrence_count: int = 1,
        avg_confidence: float | None = None,
        example_query: str | None = None,
        collection_id: UUID | None = None,
    ) -> KnowledgeGap:
        gap = KnowledgeGap(
            id=uuid4(),
            organization_id=organization_id,
            gap_type=gap_type,
            topic_label=topic_label,
            description=description,
            gap_source=gap_source,
            occurrence_count=occurrence_count,
            avg_confidence=avg_confidence,
            example_query=example_query,
            status="open",
            collection_id=collection_id,
        )
        session.add(gap)
        await session.flush()
        return gap

    async def get_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_id: UUID,
    ) -> KnowledgeGap | None:
        result = await session.execute(
            select(KnowledgeGap).where(
                KnowledgeGap.id == gap_id,
                KnowledgeGap.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_gaps(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        gap_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeGap], int]:
        query = select(KnowledgeGap).where(KnowledgeGap.organization_id == organization_id)
        count_query = select(func.count(KnowledgeGap.id)).where(
            KnowledgeGap.organization_id == organization_id
        )
        if status:
            query = query.where(KnowledgeGap.status == status)
            count_query = count_query.where(KnowledgeGap.status == status)
        if gap_type:
            query = query.where(KnowledgeGap.gap_type == gap_type)
            count_query = count_query.where(KnowledgeGap.gap_type == gap_type)

        total_result = await session.execute(count_query)
        total = total_result.scalar_one() or 0

        items_result = await session.execute(
            query.order_by(KnowledgeGap.created_at.desc()).limit(limit).offset(offset)
        )
        return list(items_result.scalars().all()), total

    async def exists_similar_gap(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        gap_type: str,
        topic_label: str,
    ) -> bool:
        result = await session.execute(
            select(KnowledgeGap.id).where(
                KnowledgeGap.organization_id == organization_id,
                KnowledgeGap.gap_type == gap_type,
                KnowledgeGap.topic_label == topic_label,
                KnowledgeGap.status != "dismissed",
            )
        )
        return result.first() is not None
