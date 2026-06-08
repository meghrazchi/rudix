from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey


class ApiKeysRepository:
    async def list_api_keys(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[ApiKey]:
        result = await db_session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars())

    async def get_api_key(
        self,
        db_session: AsyncSession,
        *,
        key_id: UUID,
        organization_id: UUID,
    ) -> ApiKey | None:
        result = await db_session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_key_by_hash(
        self,
        db_session: AsyncSession,
        *,
        key_hash: str,
    ) -> ApiKey | None:
        result = await db_session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def create_api_key(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: datetime | None,
        created_by_id: UUID | None,
    ) -> ApiKey:
        api_key = ApiKey(
            organization_id=organization_id,
            name=name,
            description=description,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            status="active",
            expires_at=expires_at,
            created_by_id=created_by_id,
        )
        db_session.add(api_key)
        await db_session.flush()
        return api_key

    async def update_api_key(
        self,
        db_session: AsyncSession,
        *,
        api_key: ApiKey,
        name: str | None,
        description: str | None,
    ) -> ApiKey:
        if name is not None:
            api_key.name = name
        if description is not None:
            api_key.description = description
        await db_session.flush()
        return api_key

    async def revoke_api_key(
        self,
        db_session: AsyncSession,
        *,
        api_key: ApiKey,
    ) -> ApiKey:
        api_key.status = "revoked"
        await db_session.flush()
        return api_key

    async def record_usage(
        self,
        db_session: AsyncSession,
        *,
        key_id: UUID,
        used_at: datetime,
        ip_address: str | None,
    ) -> None:
        await db_session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(last_used_at=used_at, last_used_ip=ip_address)
        )
