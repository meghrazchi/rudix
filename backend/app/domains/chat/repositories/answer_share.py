from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer_share import AnswerShare


class AnswerShareRepository:
    async def create_answer_share(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
        organization_id: UUID,
        shared_by_user_id: UUID,
        token: str,
        access_mode: str = "org_only",
        allowed_user_ids: list[str] | None = None,
        password_hash: str | None = None,
        expires_at: datetime | None = None,
    ) -> AnswerShare:
        share = AnswerShare(
            chat_message_id=chat_message_id,
            organization_id=organization_id,
            shared_by_user_id=shared_by_user_id,
            token=token,
            access_mode=access_mode,
            allowed_user_ids=allowed_user_ids,
            password_hash=password_hash,
            expires_at=expires_at,
            is_revoked=False,
        )
        session.add(share)
        await session.flush()
        await session.refresh(share)
        return share

    async def list_active_answer_shares(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[AnswerShare]:
        result = await session.execute(
            select(AnswerShare)
            .where(
                AnswerShare.chat_message_id == chat_message_id,
                AnswerShare.organization_id == organization_id,
                AnswerShare.shared_by_user_id == user_id,
                AnswerShare.is_revoked.is_(False),
            )
            .order_by(AnswerShare.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_active_answer_shares(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(AnswerShare.id)).where(
                AnswerShare.chat_message_id == chat_message_id,
                AnswerShare.organization_id == organization_id,
                AnswerShare.shared_by_user_id == user_id,
                AnswerShare.is_revoked.is_(False),
            )
        )
        return int(result.scalar_one())

    async def get_answer_share_by_id(
        self,
        session: AsyncSession,
        *,
        share_id: UUID,
        chat_message_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> AnswerShare | None:
        result = await session.execute(
            select(AnswerShare).where(
                AnswerShare.id == share_id,
                AnswerShare.chat_message_id == chat_message_id,
                AnswerShare.organization_id == organization_id,
                AnswerShare.shared_by_user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_answer_share_by_token(
        self,
        session: AsyncSession,
        *,
        token: str,
        organization_id: UUID,
    ) -> AnswerShare | None:
        """Return a non-revoked, non-expired share for the given org. Password check is caller's responsibility."""
        now = datetime.now(tz=UTC)
        result = await session.execute(
            select(AnswerShare).where(
                AnswerShare.token == token,
                AnswerShare.organization_id == organization_id,
                AnswerShare.is_revoked.is_(False),
                (AnswerShare.expires_at.is_(None)) | (AnswerShare.expires_at > now),
            )
        )
        return result.scalar_one_or_none()

    async def revoke_answer_share(
        self,
        session: AsyncSession,
        *,
        share_id: UUID,
        chat_message_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        share = await self.get_answer_share_by_id(
            session,
            share_id=share_id,
            chat_message_id=chat_message_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        if share is None:
            return False
        share.is_revoked = True
        session.add(share)
        await session.flush()
        return True
