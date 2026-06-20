from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization_invitation import OrganizationInvitation


class InvitationRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        email: str,
        role: str,
        token_hash: str,
        expires_at: datetime,
        invited_by_user_id: UUID | None,
        member_id: UUID | None,
    ) -> OrganizationInvitation:
        inv = OrganizationInvitation(
            organization_id=organization_id,
            email=email,
            role=role,
            token_hash=token_hash,
            status="pending",
            expires_at=expires_at,
            invited_by_user_id=invited_by_user_id,
            resend_count=0,
            last_sent_at=datetime.now(UTC),
            member_id=member_id,
        )
        session.add(inv)
        await session.flush()
        return inv

    async def get(
        self,
        session: AsyncSession,
        *,
        invitation_id: UUID,
        organization_id: UUID,
    ) -> OrganizationInvitation | None:
        result = await session.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.organization_id == organization_id,
            )
            .options(selectinload(OrganizationInvitation.invited_by))
        )
        return result.scalar_one_or_none()

    async def get_by_token_hash(
        self,
        session: AsyncSession,
        *,
        token_hash: str,
    ) -> OrganizationInvitation | None:
        result = await session.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.token_hash == token_hash)
            .options(selectinload(OrganizationInvitation.invited_by))
        )
        return result.scalar_one_or_none()

    async def get_pending_by_email(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        email: str,
    ) -> OrganizationInvitation | None:
        result = await session.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == "pending",
            )
            .order_by(OrganizationInvitation.created_at.desc())
        )
        return result.scalars().first()

    async def list_pending(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int,
        offset: int,
    ) -> list[OrganizationInvitation]:
        result = await session.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.status == "pending",
            )
            .options(selectinload(OrganizationInvitation.invited_by))
            .order_by(OrganizationInvitation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_pending(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(OrganizationInvitation.id)).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.status == "pending",
            )
        )
        return int(result.scalar_one())

    async def mark_accepted(
        self,
        session: AsyncSession,
        *,
        invitation: OrganizationInvitation,
        accepted_by_user_id: UUID,
    ) -> None:
        now = datetime.now(UTC)
        invitation.status = "accepted"
        invitation.accepted_at = now
        invitation.accepted_by_user_id = accepted_by_user_id
        await session.flush()

    async def mark_revoked(
        self,
        session: AsyncSession,
        *,
        invitation: OrganizationInvitation,
        revoked_by_user_id: UUID,
    ) -> None:
        now = datetime.now(UTC)
        invitation.status = "revoked"
        invitation.revoked_at = now
        invitation.revoked_by_user_id = revoked_by_user_id
        await session.flush()

    async def mark_resent(
        self,
        session: AsyncSession,
        *,
        invitation: OrganizationInvitation,
        new_token_hash: str,
        new_expires_at: datetime,
    ) -> None:
        now = datetime.now(UTC)
        invitation.token_hash = new_token_hash
        invitation.expires_at = new_expires_at
        invitation.resend_count = (invitation.resend_count or 0) + 1
        invitation.last_sent_at = now
        await session.flush()

    async def expire_stale(self, session: AsyncSession) -> int:
        now = datetime.now(UTC)
        result = await session.execute(
            update(OrganizationInvitation)
            .where(
                OrganizationInvitation.status == "pending",
                OrganizationInvitation.expires_at < now,
            )
            .values(status="expired")
        )
        return int(getattr(result, "rowcount", 0) or 0)
