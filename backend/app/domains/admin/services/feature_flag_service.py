from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.repositories.feature_flags import FeatureFlagRepository
from app.domains.admin.schemas.feature_flags import (
    ALL_FLAG_NAMES,
    FeatureFlagDeleteResponse,
    FeatureFlagDetail,
    FeatureFlagName,
    FeatureFlagsResponse,
    FeatureFlagSetResponse,
    PublicFeatureFlagsResponse,
)
from app.models.feature_flags import OrgFeatureFlagOverride

# Maps canonical flag name → settings attribute name.
_SETTINGS_ATTR: dict[str, str] = {
    "agents": "feature_enable_agents",
    "mcp": "feature_enable_mcp",
    "connectors": "feature_enable_connectors",
    "evaluations": "feature_enable_evaluations",
    "chunking_profiles": "feature_enable_chunking_profiles",
    "adaptive_chunking": "feature_enable_adaptive_chunking",
    "advanced_pdf_extraction": "feature_enable_advanced_pdf_extraction",
    "language_aware_rag": "feature_enable_language_aware_rag",
    "pipeline_explorer": "feature_enable_pipeline_explorer",
    "local_llm_profiles": "feature_enable_local_llm_profiles",
    "experimental_profiles": "feature_enable_experimental_profiles",
    "provider_fallback": "feature_enable_provider_fallback",
    "external_mcp_connectors": "feature_enable_external_mcp_connectors",
}


def _env_default(flag_name: str) -> bool:
    """Returns the environment-level default for a flag (None treated as False)."""
    attr = _SETTINGS_ATTR.get(flag_name)
    if attr is None:
        return False
    value = getattr(settings, attr, False)
    return bool(value) if value is not None else False


def _resolve_flag(
    flag_name: str,
    override: OrgFeatureFlagOverride | None,
) -> FeatureFlagDetail:
    env_default = _env_default(flag_name)
    if override is not None:
        return FeatureFlagDetail(
            name=flag_name,
            enabled=override.enabled,
            env_default=env_default,
            has_org_override=True,
            override_enabled=override.enabled,
            override_reason=override.reason,
            overridden_by_user_id=(
                str(override.overridden_by_user_id)
                if override.overridden_by_user_id is not None
                else None
            ),
            overridden_at=override.overridden_at,
        )
    return FeatureFlagDetail(
        name=flag_name,
        enabled=env_default,
        env_default=env_default,
        has_org_override=False,
    )


class FeatureFlagService:
    def __init__(self, repository: FeatureFlagRepository | None = None) -> None:
        self._repository = repository or FeatureFlagRepository()

    async def list_flags(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> FeatureFlagsResponse:
        overrides = await self._repository.list_by_organization(
            session, organization_id=organization_id
        )
        override_map = {o.flag_name: o for o in overrides}
        flags = [_resolve_flag(name, override_map.get(name)) for name in ALL_FLAG_NAMES]
        return FeatureFlagsResponse(
            organization_id=str(organization_id),
            flags=flags,
        )

    async def get_public_flags(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> PublicFeatureFlagsResponse:
        overrides = await self._repository.list_by_organization(
            session, organization_id=organization_id
        )
        override_map = {o.flag_name: o for o in overrides}
        resolved = {
            name: _resolve_flag(name, override_map.get(name)).enabled
            for name in ALL_FLAG_NAMES
        }
        return PublicFeatureFlagsResponse(flags=resolved)

    async def set_flag(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
        enabled: bool,
        reason: str | None,
        overridden_by_user_id: UUID | None,
    ) -> FeatureFlagSetResponse:
        if flag_name not in _SETTINGS_ATTR:
            raise ValueError(f"Unknown feature flag: {flag_name!r}")
        override = await self._repository.upsert(
            session,
            organization_id=organization_id,
            flag_name=flag_name,
            enabled=enabled,
            reason=reason,
            overridden_by_user_id=overridden_by_user_id,
        )
        flag_detail = _resolve_flag(flag_name, override)
        return FeatureFlagSetResponse(
            organization_id=str(organization_id),
            flag=flag_detail,
        )

    async def clear_flag(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
    ) -> FeatureFlagDeleteResponse:
        if flag_name not in _SETTINGS_ATTR:
            raise ValueError(f"Unknown feature flag: {flag_name!r}")
        await self._repository.delete(
            session, organization_id=organization_id, flag_name=flag_name
        )
        env_default = _env_default(flag_name)
        return FeatureFlagDeleteResponse(
            organization_id=str(organization_id),
            flag_name=flag_name,
            reverted_to_env_default=True,
            env_default=env_default,
        )

    async def is_enabled(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
    ) -> bool:
        override = await self._repository.get(
            session, organization_id=organization_id, flag_name=flag_name
        )
        return _resolve_flag(flag_name, override).enabled


def resolve_flag_from_env(flag_name: FeatureFlagName) -> bool:
    """Stateless env-only resolution — no DB, used in guards that run before DB is available."""
    return _env_default(flag_name)
