from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_feedback import MessageFeedback

_DEFAULT_RETENTION_DAYS = 90


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
        category: str | None = None,
        question_text: str | None = None,
        answer_text: str | None = None,
        citations_json: dict | None = None,
        retrieval_diagnostics_json: dict | None = None,
        model_name: str | None = None,
        rag_profile_id: UUID | None = None,
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
            existing.category = category
            if question_text is not None:
                existing.question_text = question_text
            if answer_text is not None:
                existing.answer_text = answer_text
            if citations_json is not None:
                existing.citations_json = citations_json
            if retrieval_diagnostics_json is not None:
                existing.retrieval_diagnostics_json = retrieval_diagnostics_json
            if model_name is not None:
                existing.model_name = model_name
            if rag_profile_id is not None:
                existing.rag_profile_id = rag_profile_id
            session.add(existing)
            await session.flush()
            await session.refresh(existing)
            return existing

        retain_until = datetime.now(tz=timezone.utc) + timedelta(days=_DEFAULT_RETENTION_DAYS)
        feedback = MessageFeedback(
            message_id=message_id,
            user_id=user_id,
            organization_id=organization_id,
            rating=rating,
            reason=reason,
            comment=comment,
            category=category,
            question_text=question_text,
            answer_text=answer_text,
            citations_json=citations_json,
            retrieval_diagnostics_json=retrieval_diagnostics_json,
            model_name=model_name,
            rag_profile_id=rag_profile_id,
            retain_until=retain_until,
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

    async def get_feedback_by_id(
        self,
        session: AsyncSession,
        *,
        feedback_id: UUID,
        organization_id: UUID,
    ) -> MessageFeedback | None:
        result = await session.execute(
            select(MessageFeedback).where(
                MessageFeedback.id == feedback_id,
                MessageFeedback.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def redact_feedback(
        self,
        session: AsyncSession,
        *,
        feedback_id: UUID,
        organization_id: UUID,
    ) -> MessageFeedback | None:
        feedback = await self.get_feedback_by_id(
            session, feedback_id=feedback_id, organization_id=organization_id
        )
        if feedback is None:
            return None
        feedback.question_text = None
        feedback.answer_text = None
        feedback.citations_json = None
        feedback.retrieval_diagnostics_json = None
        feedback.comment = None
        feedback.redacted_at = datetime.now(tz=timezone.utc)
        session.add(feedback)
        await session.flush()
        await session.refresh(feedback)
        return feedback

    async def mark_converted(
        self,
        session: AsyncSession,
        *,
        feedback_id: UUID,
        eval_question_id: UUID,
    ) -> MessageFeedback | None:
        result = await session.execute(
            select(MessageFeedback).where(MessageFeedback.id == feedback_id)
        )
        feedback = result.scalar_one_or_none()
        if feedback is None:
            return None
        feedback.converted_to_eval_question_id = eval_question_id
        session.add(feedback)
        await session.flush()
        await session.refresh(feedback)
        return feedback

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
