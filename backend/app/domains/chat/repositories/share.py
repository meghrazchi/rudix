from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_share import ChatShare


class ChatShareRepository:
    async def create_chat_share(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        shared_by_user_id: UUID,
        token: str,
        expires_at: datetime | None = None,
    ) -> ChatShare:
        share = ChatShare(
            chat_session_id=chat_session_id,
            organization_id=organization_id,
            shared_by_user_id=shared_by_user_id,
            token=token,
            expires_at=expires_at,
            is_revoked=False,
        )
        session.add(share)
        await session.flush()
        await session.refresh(share)
        return share

    async def list_active_chat_shares(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[ChatShare]:
        result = await session.execute(
            select(ChatShare)
            .where(
                ChatShare.chat_session_id == chat_session_id,
                ChatShare.organization_id == organization_id,
                ChatShare.shared_by_user_id == user_id,
                ChatShare.is_revoked.is_(False),
            )
            .order_by(ChatShare.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_active_chat_shares(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(ChatShare.id)).where(
                ChatShare.chat_session_id == chat_session_id,
                ChatShare.organization_id == organization_id,
                ChatShare.shared_by_user_id == user_id,
                ChatShare.is_revoked.is_(False),
            )
        )
        return int(result.scalar_one())

    async def get_chat_share_by_id(
        self,
        session: AsyncSession,
        *,
        share_id: UUID,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> ChatShare | None:
        result = await session.execute(
            select(ChatShare).where(
                ChatShare.id == share_id,
                ChatShare.chat_session_id == chat_session_id,
                ChatShare.organization_id == organization_id,
                ChatShare.shared_by_user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_chat_share_by_token(
        self,
        session: AsyncSession,
        *,
        token: str,
        organization_id: UUID,
    ) -> ChatShare | None:
        now = datetime.now(tz=UTC)
        result = await session.execute(
            select(ChatShare).where(
                ChatShare.token == token,
                ChatShare.organization_id == organization_id,
                ChatShare.is_revoked.is_(False),
                (ChatShare.expires_at.is_(None)) | (ChatShare.expires_at > now),
            )
        )
        return result.scalar_one_or_none()

    async def revoke_chat_share(
        self,
        session: AsyncSession,
        *,
        share_id: UUID,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        share = await self.get_chat_share_by_id(
            session,
            share_id=share_id,
            chat_session_id=chat_session_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        if share is None:
            return False
        share.is_revoked = True
        session.add(share)
        await session.flush()
        return True
