from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.usage_touch_sql import apply_max_guarded_usage
from app.models.service_account import ServiceAccount, ServiceAccountToken


class ServiceAccountsRepository:
    async def list_service_accounts(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[ServiceAccount]:
        result = await db_session.execute(
            select(ServiceAccount)
            .where(ServiceAccount.organization_id == organization_id)
            .order_by(ServiceAccount.created_at.desc())
        )
        return list(result.scalars())

    async def get_service_account(
        self,
        db_session: AsyncSession,
        *,
        account_id: UUID,
        organization_id: UUID,
    ) -> ServiceAccount | None:
        result = await db_session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == account_id,
                ServiceAccount.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_service_account(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        environment: str,
        scopes: list[str],
        created_by_id: UUID | None,
    ) -> ServiceAccount:
        account = ServiceAccount(
            organization_id=organization_id,
            name=name,
            description=description,
            environment=environment,
            scopes=scopes,
            is_active=True,
            created_by_id=created_by_id,
        )
        db_session.add(account)
        await db_session.flush()
        return account

    async def update_service_account(
        self,
        db_session: AsyncSession,
        *,
        account: ServiceAccount,
        name: str | None,
        description: str | None,
        environment: str | None,
    ) -> ServiceAccount:
        if name is not None:
            account.name = name
        if description is not None:
            account.description = description
        if environment is not None:
            account.environment = environment
        await db_session.flush()
        return account

    async def deactivate_service_account(
        self,
        db_session: AsyncSession,
        *,
        account: ServiceAccount,
    ) -> ServiceAccount:
        account.is_active = False
        await db_session.flush()
        return account

    async def reactivate_service_account(
        self,
        db_session: AsyncSession,
        *,
        account: ServiceAccount,
    ) -> ServiceAccount:
        account.is_active = True
        await db_session.flush()
        return account

    async def apply_account_usage_touches(
        self,
        db_session: AsyncSession,
        *,
        touches: Sequence[tuple[UUID, datetime, str | None]],
    ) -> None:
        """Bulk-apply buffered account touches (no IP column); never moves time backwards."""
        await apply_max_guarded_usage(
            db_session, model=ServiceAccount, touches=touches, with_ip=False
        )

    # ── Token operations ──────────────────────────────────────────────────────

    async def list_tokens(
        self,
        db_session: AsyncSession,
        *,
        service_account_id: UUID,
        organization_id: UUID,
    ) -> list[ServiceAccountToken]:
        result = await db_session.execute(
            select(ServiceAccountToken)
            .where(
                ServiceAccountToken.service_account_id == service_account_id,
                ServiceAccountToken.organization_id == organization_id,
            )
            .order_by(ServiceAccountToken.created_at.desc())
        )
        return list(result.scalars())

    async def get_token(
        self,
        db_session: AsyncSession,
        *,
        token_id: UUID,
        service_account_id: UUID,
        organization_id: UUID,
    ) -> ServiceAccountToken | None:
        result = await db_session.execute(
            select(ServiceAccountToken).where(
                ServiceAccountToken.id == token_id,
                ServiceAccountToken.service_account_id == service_account_id,
                ServiceAccountToken.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_token_by_hash(
        self,
        db_session: AsyncSession,
        *,
        token_hash: str,
    ) -> ServiceAccountToken | None:
        result = await db_session.execute(
            select(ServiceAccountToken).where(
                ServiceAccountToken.token_hash == token_hash,
                ServiceAccountToken.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def create_token(
        self,
        db_session: AsyncSession,
        *,
        service_account_id: UUID,
        organization_id: UUID,
        name: str,
        token_prefix: str,
        token_hash: str,
        expires_at: datetime | None,
        created_by_id: UUID | None,
    ) -> ServiceAccountToken:
        token = ServiceAccountToken(
            service_account_id=service_account_id,
            organization_id=organization_id,
            name=name,
            token_prefix=token_prefix,
            token_hash=token_hash,
            status="active",
            expires_at=expires_at,
            created_by_id=created_by_id,
        )
        db_session.add(token)
        await db_session.flush()
        return token

    async def revoke_token(
        self,
        db_session: AsyncSession,
        *,
        token: ServiceAccountToken,
    ) -> ServiceAccountToken:
        token.status = "revoked"
        await db_session.flush()
        return token

    async def apply_token_usage_touches(
        self,
        db_session: AsyncSession,
        *,
        touches: Sequence[tuple[UUID, datetime, str | None]],
    ) -> None:
        """Bulk-apply buffered ``(token_id, used_at, ip)`` touches; never moves time backwards."""
        await apply_max_guarded_usage(
            db_session, model=ServiceAccountToken, touches=touches, with_ip=True
        )
