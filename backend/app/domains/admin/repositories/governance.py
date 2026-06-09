from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import OrganizationGovernancePolicy


class GovernancePolicyRepository:
    async def get_by_organization(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> OrganizationGovernancePolicy | None:
        result = await session.execute(
            select(OrganizationGovernancePolicy).where(
                OrganizationGovernancePolicy.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        updated_by_user_id: UUID | None,
        agentic_mode_enabled: bool,
        mcp_exposure_enabled: bool,
        allow_side_effect_tools: bool,
        allowed_tool_names: list[str],
        max_steps: int | None,
        max_tool_calls_per_run: int | None,
        max_tool_timeout_ms: int | None,
        max_tool_input_bytes: int | None,
        max_tool_output_bytes: int | None,
        max_tool_retry_attempts: int | None,
        max_total_tokens: int | None,
        max_total_cost_usd: Decimal | None,
        external_mcp_servers: list[dict],
        # F225 provider security fields
        local_only_mode: bool = False,
        cloud_fallback_allowed: bool = True,
        allowed_provider_profiles: list[str] | None = None,
        admin_only_model_selection: bool = True,
        retention_warning_acknowledged: bool = False,
    ) -> OrganizationGovernancePolicy:
        policy = await self.get_by_organization(session, organization_id=organization_id)
        allowed_profiles = list(allowed_provider_profiles or [])
        if policy is None:
            policy = OrganizationGovernancePolicy(
                organization_id=organization_id,
                updated_by_user_id=updated_by_user_id,
                agentic_mode_enabled=agentic_mode_enabled,
                mcp_exposure_enabled=mcp_exposure_enabled,
                allow_side_effect_tools=allow_side_effect_tools,
                allowed_tool_names_json=list(allowed_tool_names),
                max_steps=max_steps,
                max_tool_calls_per_run=max_tool_calls_per_run,
                max_tool_timeout_ms=max_tool_timeout_ms,
                max_tool_input_bytes=max_tool_input_bytes,
                max_tool_output_bytes=max_tool_output_bytes,
                max_tool_retry_attempts=max_tool_retry_attempts,
                max_total_tokens=max_total_tokens,
                max_total_cost_usd=max_total_cost_usd,
                external_mcp_servers_json=list(external_mcp_servers),
                local_only_mode=local_only_mode,
                cloud_fallback_allowed=cloud_fallback_allowed,
                allowed_provider_profiles_json=allowed_profiles,
                admin_only_model_selection=admin_only_model_selection,
                retention_warning_acknowledged=retention_warning_acknowledged,
            )
            session.add(policy)
            await session.flush()
            await session.refresh(policy)
            return policy

        policy.updated_by_user_id = updated_by_user_id
        policy.agentic_mode_enabled = agentic_mode_enabled
        policy.mcp_exposure_enabled = mcp_exposure_enabled
        policy.allow_side_effect_tools = allow_side_effect_tools
        policy.allowed_tool_names_json = list(allowed_tool_names)
        policy.max_steps = max_steps
        policy.max_tool_calls_per_run = max_tool_calls_per_run
        policy.max_tool_timeout_ms = max_tool_timeout_ms
        policy.max_tool_input_bytes = max_tool_input_bytes
        policy.max_tool_output_bytes = max_tool_output_bytes
        policy.max_tool_retry_attempts = max_tool_retry_attempts
        policy.max_total_tokens = max_total_tokens
        policy.max_total_cost_usd = max_total_cost_usd
        policy.external_mcp_servers_json = list(external_mcp_servers)
        policy.local_only_mode = local_only_mode
        policy.cloud_fallback_allowed = cloud_fallback_allowed
        policy.allowed_provider_profiles_json = allowed_profiles
        policy.admin_only_model_selection = admin_only_model_selection
        policy.retention_warning_acknowledged = retention_warning_acknowledged
        await session.flush()
        await session.refresh(policy)
        return policy
