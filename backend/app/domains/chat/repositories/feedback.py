from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_feedback import MessageFeedback


class FeedbackRepository:
    async def upsert_feedback(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        user_id: UUID,
        organization_id: UUID,
        rating: str,
        reason: str | None,
        comment: str | None,
    ) -> MessageFeedback:
        existing = await self.get_feedback(
            session,
            message_id=message_id,
            user_id=user_id,
            organization_id=organization_id,
        )
        if existing is not None:
            existing.rating = rating
            existing.reason = reason
            existing.comment = comment
            session.add(existing)
            await session.flush()
            await session.refresh(existing)
            return existing

        feedback = MessageFeedback(
            message_id=message_id,
            user_id=user_id,
            organization_id=organization_id,
            rating=rating,
            reason=reason,
            comment=comment,
        )
        session.add(feedback)
        await session.flush()
        await session.refresh(feedback)
        return feedback

    async def get_feedback(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        user_id: UUID,
        organization_id: UUID,
    ) -> MessageFeedback | None:
        result = await session.execute(
            select(MessageFeedback).where(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user_id,
                MessageFeedback.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_feedback(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        existing = await self.get_feedback(
            session,
            message_id=message_id,
            user_id=user_id,
            organization_id=organization_id,
        )
        if existing is None:
            return False
        await session.delete(existing)
        await session.flush()
        return True

    async def list_feedback_for_session(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[MessageFeedback]:
        from app.models.chat import ChatMessage

        result = await session.execute(
            select(MessageFeedback)
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(
                ChatMessage.chat_session_id == chat_session_id,
                MessageFeedback.organization_id == organization_id,
                MessageFeedback.user_id == user_id,
            )
            .order_by(MessageFeedback.created_at.asc())
        )
        return list(result.scalars().all())
