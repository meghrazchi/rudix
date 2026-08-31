"""One-time first-admin bootstrap for a fresh deployment.

Unlike scripts/seed_dev.py (local-dev only, seeds demo content on every run),
this is safe to invoke on every deploy of a real environment: it does nothing
unless the database has zero organizations, so it never touches an existing
admin's password or creates duplicate orgs on redeploys.

Required environment variables:
    BOOTSTRAP_ADMIN_EMAIL
    BOOTSTRAP_ADMIN_PASSWORD

Optional:
    BOOTSTRAP_ORG_NAME   (default: "Rudix")
    BOOTSTRAP_ORG_SLUG   (default: "default")
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Organization, OrganizationMember, User
from app.models.enums import OrganizationRole

_PASSWORD_HASHER = build_password_hasher(
    PasswordHashConfig(
        memory_cost=settings.app_auth_password_hash_memory_cost_kib,
        time_cost=settings.app_auth_password_hash_time_cost,
        parallelism=settings.app_auth_password_hash_parallelism,
        hash_length=settings.app_auth_password_hash_length,
        salt_length=settings.app_auth_password_salt_length,
    )
)


async def bootstrap() -> None:
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or not password:
        print("Bootstrap skipped: BOOTSTRAP_ADMIN_EMAIL/BOOTSTRAP_ADMIN_PASSWORD not set.")
        return

    org_name = os.environ.get("BOOTSTRAP_ORG_NAME", "Rudix")
    org_slug = os.environ.get("BOOTSTRAP_ORG_SLUG", "default")

    async with SessionLocal() as session:
        existing_org = (
            await session.execute(select(Organization.id).limit(1))
        ).scalar_one_or_none()
        if existing_org is not None:
            print("Bootstrap skipped: an organization already exists.")
            return

        organization = Organization(name=org_name, slug=org_slug)
        session.add(organization)
        await session.flush()

        user = User(
            organization_id=organization.id,
            external_auth_id=email,
            email=email,
            display_name="Admin",
            hashed_password=hash_password(password, _PASSWORD_HASHER),
            password_state="active",
            password_changed_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()

        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.owner.value,
            )
        )
        await session.commit()
        print(
            f"Bootstrap admin created: org={organization.slug} ({organization.id}) user={user.email}"
        )


def main() -> None:
    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()
