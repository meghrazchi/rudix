from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_scim_config import OrgSCIMConfig
from app.models.organization_member import OrganizationMember
from app.models.user import User

_TOKEN_BYTES = 32  # 64-char hex token


def _generate_token() -> str:
    return secrets.token_hex(_TOKEN_BYTES)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _token_hint(raw_token: str) -> str:
    return raw_token[-4:]


class SCIMService:
    # ── Config management ─────────────────────────────────────────────────────

    async def get_config(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> OrgSCIMConfig | None:
        result = await db.execute(
            select(OrgSCIMConfig).where(
                OrgSCIMConfig.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def get_config_by_token_hash(
        self, db: AsyncSession, *, token_hash: str
    ) -> OrgSCIMConfig | None:
        result = await db.execute(
            select(OrgSCIMConfig).where(
                OrgSCIMConfig.token_hash == token_hash,
                OrgSCIMConfig.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def enable(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        actor_id: UUID | None,
    ) -> tuple[OrgSCIMConfig, str]:
        """Enable SCIM and generate a new bearer token. Returns (config, raw_token)."""
        raw_token = _generate_token()
        existing = await self.get_config(db, organization_id=organization_id)

        if existing is None:
            config = OrgSCIMConfig(
                organization_id=organization_id,
                enabled=True,
                token_hash=_hash_token(raw_token),
                token_hint=_token_hint(raw_token),
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            db.add(config)
        else:
            config = existing
            config.enabled = True
            config.token_hash = _hash_token(raw_token)
            config.token_hint = _token_hint(raw_token)
            config.updated_by_id = actor_id

        await db.flush()
        await db.refresh(config)
        return config, raw_token

    async def rotate_token(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        actor_id: UUID | None,
    ) -> tuple[OrgSCIMConfig, str]:
        """Rotate the SCIM bearer token. Returns (config, new_raw_token)."""
        config = await self.get_config(db, organization_id=organization_id)
        if config is None:
            raise ValueError("SCIM is not configured for this organization.")
        raw_token = _generate_token()
        config.token_hash = _hash_token(raw_token)
        config.token_hint = _token_hint(raw_token)
        config.updated_by_id = actor_id
        await db.flush()
        await db.refresh(config)
        return config, raw_token

    async def disable(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> bool:
        config = await self.get_config(db, organization_id=organization_id)
        if config is None:
            return False
        await db.delete(config)
        await db.flush()
        return True

    # ── SCIM user operations ──────────────────────────────────────────────────

    async def list_users(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        start_index: int = 1,
        count: int = 100,
        filter_email: str | None = None,
    ) -> tuple[list[User], int]:
        """Return (page_of_users, total_count) scoped to org."""
        base_query = select(User).where(User.organization_id == organization_id)
        if filter_email:
            base_query = base_query.where(
                User.email == filter_email.strip().lower()
            )

        total_result = await db.execute(
            select(User.id).where(User.organization_id == organization_id)
        )
        total = len(total_result.scalars().all())

        paginated = (
            base_query
            .order_by(User.created_at)
            .offset(max(0, start_index - 1))
            .limit(min(count, 200))
        )
        users_result = await db.execute(paginated)
        return list(users_result.scalars().all()), total

    async def get_user_by_scim_id(
        self,
        db: AsyncSession,
        *,
        scim_external_id: str,
        organization_id: UUID,
    ) -> User | None:
        result = await db.execute(
            select(User).where(
                User.scim_external_id == scim_external_id,
                User.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(
        self,
        db: AsyncSession,
        *,
        email: str,
        organization_id: UUID,
    ) -> User | None:
        result = await db.execute(
            select(User).where(
                User.email == email.strip().lower(),
                User.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def provision_user(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        scim_external_id: str,
        email: str,
        display_name: str | None,
        is_active: bool,
        config: OrgSCIMConfig,
    ) -> User:
        """Create a new user via SCIM provisioning."""
        from app.models.enums import OrganizationRole

        clean_email = email.strip().lower()
        existing = await self.get_user_by_email(
            db, email=clean_email, organization_id=organization_id
        )
        if existing is not None:
            # Update existing user with SCIM external ID
            existing.scim_external_id = scim_external_id
            existing.provisioned_by = "scim"
            existing.is_active = is_active
            if display_name:
                existing.display_name = display_name
            await db.flush()
            return existing

        user = User(
            organization_id=organization_id,
            external_auth_id=f"scim:{organization_id}:{scim_external_id}",
            email=clean_email,
            display_name=display_name,
            is_active=is_active,
            provisioned_by="scim",
            scim_external_id=scim_external_id,
        )
        db.add(user)
        await db.flush()

        db.add(
            OrganizationMember(
                organization_id=organization_id,
                user_id=user.id,
                role=OrganizationRole.member.value,
            )
        )
        await db.flush()

        # Update sync counter
        config.provisioned_count = (config.provisioned_count or 0) + 1
        config.last_sync_at = datetime.now(UTC)
        config.last_sync_error = None

        await db.refresh(user)
        return user

    async def update_user(
        self,
        db: AsyncSession,
        *,
        user: User,
        display_name: str | None,
        is_active: bool,
        config: OrgSCIMConfig,
    ) -> User:
        """Update an existing SCIM-managed user."""
        was_active = user.is_active
        user.display_name = display_name
        user.is_active = is_active

        if was_active and not is_active:
            config.deprovisioned_count = (config.deprovisioned_count or 0) + 1
        elif not was_active and is_active:
            config.provisioned_count = (config.provisioned_count or 0) + 1

        config.last_sync_at = datetime.now(UTC)
        config.last_sync_error = None

        await db.flush()
        await db.refresh(user)
        return user

    async def deprovision_user(
        self,
        db: AsyncSession,
        *,
        user: User,
        config: OrgSCIMConfig,
    ) -> None:
        """Deactivate user and remove org membership (SCIM DELETE)."""
        user.is_active = False

        # Remove org membership so the user cannot access org resources
        result = await db.execute(
            select(OrganizationMember).where(
                and_(
                    OrganizationMember.organization_id == user.organization_id,
                    OrganizationMember.user_id == user.id,
                )
            )
        )
        membership = result.scalar_one_or_none()
        if membership is not None:
            await db.delete(membership)

        config.deprovisioned_count = (config.deprovisioned_count or 0) + 1
        config.last_sync_at = datetime.now(UTC)
        config.last_sync_error = None

        await db.flush()

    def authenticate_scim_request(self, authorization_header: str | None) -> str | None:
        """Extract and hash the Bearer token from an Authorization header.
        Returns the SHA-256 hex digest or None if header is missing/malformed.
        """
        if not authorization_header:
            return None
        parts = authorization_header.strip().split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        raw_token = parts[1].strip()
        if not raw_token:
            return None
        return _hash_token(raw_token)
