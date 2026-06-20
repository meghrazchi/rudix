from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.models.enums import OrganizationRole


def _principal(*, roles: list[str]) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        organization_id="org-1",
        email="user@example.com",
        roles=roles,
        auth_provider="app",
    )


@pytest.mark.asyncio
async def test_require_roles_accepts_iterable_roles_and_enums() -> None:
    dependency = require_roles([OrganizationRole.owner, OrganizationRole.admin])

    result = await dependency(_principal(roles=[OrganizationRole.admin.value]))

    assert result.roles == [OrganizationRole.admin.value]


@pytest.mark.asyncio
async def test_require_roles_rejects_missing_role() -> None:
    dependency = require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(_principal(roles=[OrganizationRole.member.value]))

    assert exc_info.value.status_code == 403
