from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quotas import OrgQuotaChangeLog, OrgQuotaOverride, OrgQuotaPolicy, OrgQuotaUsage


class QuotaRepository:
    # ------------------------------------------------------------------
    # Policy (one row per org — upsert pattern)
    # ------------------------------------------------------------------

    async def get_policy(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> OrgQuotaPolicy | None:
        stmt = select(OrgQuotaPolicy).where(OrgQuotaPolicy.organization_id == organization_id)
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_policy(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        limits: dict,
        updated_by_id: UUID | None,
        bump_version: bool = True,
    ) -> OrgQuotaPolicy:
        existing = await self.get_policy(db_session, organization_id=organization_id)
        if existing is not None:
            existing.limits = limits
            existing.updated_by_id = updated_by_id
            if bump_version:
                existing.version = (existing.version or 1) + 1
            await db_session.flush()
            return existing

        policy = OrgQuotaPolicy(
            organization_id=organization_id,
            limits=limits,
            updated_by_id=updated_by_id,
            version=1,
        )
        db_session.add(policy)
        await db_session.flush()
        return policy

    async def delete_policy(self, db_session: AsyncSession, policy: OrgQuotaPolicy) -> None:
        await db_session.delete(policy)
        await db_session.flush()

    # ------------------------------------------------------------------
    # Usage counters
    # ------------------------------------------------------------------

    async def get_usage(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: str,
    ) -> OrgQuotaUsage | None:
        stmt = select(OrgQuotaUsage).where(
            OrgQuotaUsage.organization_id == organization_id,
            OrgQuotaUsage.quota_type == quota_type,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_usage(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[OrgQuotaUsage]:
        stmt = select(OrgQuotaUsage).where(OrgQuotaUsage.organization_id == organization_id)
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_usage(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: str,
        current_value: int,
        next_reset_at: object | None = None,
    ) -> OrgQuotaUsage:
        existing = await self.get_usage(
            db_session, organization_id=organization_id, quota_type=quota_type
        )
        if existing is not None:
            existing.current_value = current_value
            if next_reset_at is not None:
                existing.next_reset_at = next_reset_at
            await db_session.flush()
            return existing

        usage = OrgQuotaUsage(
            organization_id=organization_id,
            quota_type=quota_type,
            current_value=current_value,
            next_reset_at=next_reset_at,
        )
        db_session.add(usage)
        await db_session.flush()
        return usage

    async def increment_usage(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: str,
        amount: int = 1,
        next_reset_at: object | None = None,
    ) -> OrgQuotaUsage:
        """Atomically add ``amount`` to the counter, creating the row if needed.

        A single ``INSERT ... ON CONFLICT DO UPDATE`` runs in the database, so
        concurrent callers never lose increments. The value floors at 0.
        ``next_reset_at`` only applies when the row is created.
        """
        dialect = db_session.get_bind().dialect.name
        if dialect == "postgresql":
            insert_fn: Any = pg_insert
            floor_fn: Any = func.greatest
        elif dialect == "sqlite":
            insert_fn = sqlite_insert
            floor_fn = func.max  # two-argument scalar max() in SQLite
        else:
            raise RuntimeError(f"increment_usage does not support dialect {dialect!r}")

        stmt = (
            insert_fn(OrgQuotaUsage)
            .values(
                id=uuid4(),
                organization_id=organization_id,
                quota_type=quota_type,
                current_value=max(0, amount),
                next_reset_at=next_reset_at,
            )
            .on_conflict_do_update(
                index_elements=["organization_id", "quota_type"],
                set_={"current_value": floor_fn(0, OrgQuotaUsage.current_value + amount)},
            )
        )
        await db_session.execute(stmt)

        reread = (
            select(OrgQuotaUsage)
            .where(
                OrgQuotaUsage.organization_id == organization_id,
                OrgQuotaUsage.quota_type == quota_type,
            )
            .execution_options(populate_existing=True)
        )
        result = await db_session.execute(reread)
        return result.scalar_one()

    async def reset_usage(
        self,
        db_session: AsyncSession,
        usage: OrgQuotaUsage,
        *,
        next_reset_at: object | None,
        now: datetime,
    ) -> bool:
        """Zero an expired counter once per window.

        The WHERE clause mirrors ``_reset_window_expired``: a NULL ``next_reset_at``
        is a permanent cap and is never reset. Under PostgreSQL READ COMMITTED a
        second concurrent reset re-evaluates the WHERE after the first commits and
        matches no rows. Returns True when this call performed the reset.
        """
        stmt = (
            update(OrgQuotaUsage)
            .where(
                OrgQuotaUsage.id == usage.id,
                OrgQuotaUsage.next_reset_at.is_not(None),
                OrgQuotaUsage.next_reset_at <= now,
            )
            .values(current_value=0, next_reset_at=next_reset_at)
            .execution_options(synchronize_session=False)
        )
        result = await db_session.execute(stmt)
        await db_session.refresh(usage)
        return bool(getattr(result, "rowcount", 0) == 1)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    async def get_override(
        self,
        db_session: AsyncSession,
        *,
        override_id: UUID,
        organization_id: UUID,
    ) -> OrgQuotaOverride | None:
        stmt = select(OrgQuotaOverride).where(
            OrgQuotaOverride.id == override_id,
            OrgQuotaOverride.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_overrides(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgQuotaOverride]:
        stmt = (
            select(OrgQuotaOverride)
            .where(OrgQuotaOverride.organization_id == organization_id)
            .order_by(OrgQuotaOverride.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_overrides(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        stmt = select(func.count(OrgQuotaOverride.id)).where(
            OrgQuotaOverride.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def create_override(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        quota_type: str,
        target_user_id: UUID | None,
        hard_limit_override: int | None,
        reason: str,
        created_by_id: UUID | None,
        expires_at: object | None,
    ) -> OrgQuotaOverride:
        override = OrgQuotaOverride(
            organization_id=organization_id,
            quota_type=quota_type,
            target_user_id=target_user_id,
            hard_limit_override=hard_limit_override,
            reason=reason,
            created_by_id=created_by_id,
            expires_at=expires_at,
        )
        db_session.add(override)
        await db_session.flush()
        return override

    async def delete_override(
        self,
        db_session: AsyncSession,
        override: OrgQuotaOverride,
    ) -> None:
        await db_session.delete(override)
        await db_session.flush()

    # ------------------------------------------------------------------
    # Change log
    # ------------------------------------------------------------------

    async def create_change_log_entry(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        policy_id: UUID | None,
        version_number: int,
        policy_snapshot: dict,
        change_note: str | None,
        changed_by_id: UUID | None,
    ) -> OrgQuotaChangeLog:
        entry = OrgQuotaChangeLog(
            organization_id=organization_id,
            org_quota_policy_id=policy_id,
            version_number=version_number,
            policy_snapshot=policy_snapshot,
            change_note=change_note,
            changed_by_id=changed_by_id,
        )
        db_session.add(entry)
        await db_session.flush()
        return entry

    async def list_change_log(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgQuotaChangeLog]:
        stmt = (
            select(OrgQuotaChangeLog)
            .where(OrgQuotaChangeLog.organization_id == organization_id)
            .order_by(OrgQuotaChangeLog.version_number.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_change_log(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        stmt = select(func.count(OrgQuotaChangeLog.id)).where(
            OrgQuotaChangeLog.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()
