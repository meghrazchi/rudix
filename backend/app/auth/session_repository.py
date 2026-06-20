from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import AuthRefreshSession


class AuthSessionRepository:
    async def create_session(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        session_id: UUID,
        refresh_token_hash: str,
        refresh_token_jti: str,
        device_name: str | None,
        user_agent: str | None,
        ip_address: str | None,
        expires_at: datetime,
    ) -> AuthRefreshSession:
        record = AuthRefreshSession(
            organization_id=organization_id,
            user_id=user_id,
            session_id=session_id,
            refresh_token_hash=refresh_token_hash,
            refresh_token_jti=refresh_token_jti,
            device_name=device_name,
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=expires_at,
        )
        session.add(record)
        await session.flush()
        return record

    async def get_session_by_token_hash(
        self,
        session: AsyncSession,
        *,
        refresh_token_hash: str,
    ) -> AuthRefreshSession | None:
        result = await session.execute(
            select(AuthRefreshSession).where(
                AuthRefreshSession.refresh_token_hash == refresh_token_hash
            )
        )
        return result.scalar_one_or_none()

    async def get_active_session_by_id(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
    ) -> AuthRefreshSession | None:
        result = await session.execute(
            select(AuthRefreshSession)
            .where(AuthRefreshSession.session_id == session_id)
            .where(AuthRefreshSession.revoked_at.is_(None))
            .where(AuthRefreshSession.expires_at > func.now())
            .order_by(AuthRefreshSession.created_at.desc())
        )
        return result.scalars().first()

    async def get_session_by_id(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
    ) -> AuthRefreshSession | None:
        result = await session.execute(
            select(AuthRefreshSession)
            .where(AuthRefreshSession.session_id == session_id)
            .order_by(AuthRefreshSession.created_at.desc())
        )
        return result.scalars().first()

    async def list_active_sessions_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AuthRefreshSession]:
        result = await session.execute(
            select(AuthRefreshSession)
            .where(AuthRefreshSession.user_id == user_id)
            .where(AuthRefreshSession.revoked_at.is_(None))
            .where(AuthRefreshSession.expires_at > func.now())
            .order_by(AuthRefreshSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_active_sessions_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(AuthRefreshSession.id)).where(
                AuthRefreshSession.user_id == user_id,
                AuthRefreshSession.revoked_at.is_(None),
                AuthRefreshSession.expires_at > func.now(),
            )
        )
        return int(result.scalar_one())

    async def mark_session_revoked(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        result = await session.execute(
            update(AuthRefreshSession)
            .where(AuthRefreshSession.session_id == session_id)
            .where(AuthRefreshSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def mark_user_sessions_revoked(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        result = await session.execute(
            update(AuthRefreshSession)
            .where(AuthRefreshSession.user_id == user_id)
            .where(AuthRefreshSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def mark_token_revoked(
        self,
        session: AsyncSession,
        *,
        refresh_token_hash: str,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        result = await session.execute(
            update(AuthRefreshSession)
            .where(AuthRefreshSession.refresh_token_hash == refresh_token_hash)
            .where(AuthRefreshSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def update_last_used(
        self,
        session: AsyncSession,
        *,
        refresh_token_hash: str,
        last_used_at: datetime,
    ) -> int:
        result = await session.execute(
            update(AuthRefreshSession)
            .where(AuthRefreshSession.refresh_token_hash == refresh_token_hash)
            .values(last_used_at=last_used_at)
        )
        return int(getattr(result, "rowcount", 0) or 0)
