from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.repositories.governance import GovernancePolicyRepository
from app.domains.admin.schemas.governance import (
    ExternalMCPServerPolicy,
    GovernanceBudgetConfig,
    GovernanceMCPStatus,
    GovernancePolicyResponse,
    GovernancePolicyState,
    GovernancePolicyUpdateRequest,
    GovernancePolicyUpdateResponse,
    GovernanceToolSummary,
    ProviderSecurityPolicy,
)
from app.domains.agents.schemas import ToolEffectPolicy, ToolSpec
from app.domains.agents.services.tool_registry import build_default_tool_specs


class GovernancePolicyService:
    def __init__(
        self,
        *,
        repository: GovernancePolicyRepository | None = None,
        tool_specs: tuple[ToolSpec, ...] | None = None,
    ) -> None:
        self._repository = repository or GovernancePolicyRepository()
        self._tool_specs = tool_specs or build_default_tool_specs(
            max_calls_per_run=settings.agent_tool_max_calls_per_run,
            max_input_bytes=settings.agent_tool_max_input_bytes,
            max_output_bytes=settings.agent_tool_max_output_bytes,
            timeout_ms=settings.agent_tool_timeout_ms,
        )
        self._tool_spec_by_name = {spec.name: spec for spec in self._tool_specs}

    def list_tool_catalog(self) -> list[GovernanceToolSummary]:
        return [
            GovernanceToolSummary(
                name=spec.name,
                capability=spec.capability,
                effect_policy=spec.effect_policy.value,
                surfaces=[surface.value for surface in spec.surfaces],
                required_roles=list(spec.required_roles),
                approval_required=spec.approval_required,
            )
            for spec in sorted(self._tool_specs, key=lambda item: item.name)
        ]

    async def get_policy(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> GovernancePolicyResponse:
        stored = await self._repository.get_by_organization(
            session, organization_id=organization_id
        )
        policy_state = self._resolve_state(stored)
        warnings = self._resolve_warnings(policy_state=policy_state)
        mcp_status = self._resolve_mcp_status()

        return GovernancePolicyResponse(
            organization_id=str(organization_id),
            policy=policy_state,
            mcp_status=mcp_status,
            tool_catalog=self.list_tool_catalog(),
            warnings=warnings,
            policy_updated_at=stored.updated_at if stored is not None else None,
            policy_updated_by_user_id=str(stored.updated_by_user_id)
            if stored is not None and stored.updated_by_user_id is not None
            else None,
        )

    async def update_policy(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        updated_by_user_id: UUID | None,
        payload: GovernancePolicyUpdateRequest,
    ) -> GovernancePolicyUpdateResponse:
        stored = await self._repository.get_by_organization(
            session, organization_id=organization_id
        )
        current_state = self._resolve_state(stored)
        next_state = self._apply_update(current_state=current_state, payload=payload)
        changed_fields = self._changed_fields(
            previous=current_state,
            current=next_state,
        )
        ps = next_state.provider_security
        stored = await self._repository.upsert(
            session,
            organization_id=organization_id,
            updated_by_user_id=updated_by_user_id,
            agentic_mode_enabled=next_state.agentic_mode_enabled,
            mcp_exposure_enabled=next_state.mcp_exposure_enabled,
            allow_side_effect_tools=next_state.allow_side_effect_tools,
            allowed_tool_names=list(next_state.allowed_tool_names),
            max_steps=next_state.budgets.max_steps,
            max_tool_calls_per_run=next_state.budgets.max_tool_calls_per_run,
            max_tool_timeout_ms=next_state.budgets.max_tool_timeout_ms,
            max_tool_input_bytes=next_state.budgets.max_tool_input_bytes,
            max_tool_output_bytes=next_state.budgets.max_tool_output_bytes,
            max_tool_retry_attempts=next_state.budgets.max_tool_retry_attempts,
            max_total_tokens=next_state.budgets.max_total_tokens,
            max_total_cost_usd=next_state.budgets.max_total_cost_usd,
            external_mcp_servers=[
                server.model_dump(mode="json") for server in next_state.external_mcp_servers
            ],
            local_only_mode=ps.local_only_mode,
            cloud_fallback_allowed=ps.cloud_fallback_allowed,
            allowed_provider_profiles=list(ps.allowed_provider_profiles),
            admin_only_model_selection=ps.admin_only_model_selection,
            retention_warning_acknowledged=ps.retention_warning_acknowledged,
        )

        warnings = self._resolve_warnings(policy_state=next_state)
        return GovernancePolicyUpdateResponse(
            organization_id=str(organization_id),
            policy=next_state,
            warnings=warnings,
            updated_at=stored.updated_at if stored is not None else datetime.now(tz=UTC),
            updated_by_user_id=str(stored.updated_by_user_id)
            if stored is not None and stored.updated_by_user_id is not None
            else None,
            audit_recorded=bool(changed_fields),
            changed_fields=changed_fields,
        )

    def _default_budget(self) -> GovernanceBudgetConfig:
        return GovernanceBudgetConfig(
            max_steps=settings.agent_max_steps,
            max_tool_calls_per_run=settings.agent_tool_max_calls_per_run,
            max_tool_timeout_ms=settings.agent_tool_timeout_ms,
            max_tool_input_bytes=settings.agent_tool_max_input_bytes,
            max_tool_output_bytes=settings.agent_tool_max_output_bytes,
            max_tool_retry_attempts=settings.agent_tool_max_retry_attempts,
            max_total_tokens=None,
            max_total_cost_usd=None,
        )

    def _default_allowed_tool_names(self) -> list[str]:
        return sorted(
            spec.name
            for spec in self._tool_specs
            if spec.effect_policy is ToolEffectPolicy.read_only
        )

    def _resolve_state(self, stored: Any | None) -> GovernancePolicyState:
        if stored is None:
            return GovernancePolicyState(
                agentic_mode_enabled=bool(settings.feature_enable_agents),
                mcp_exposure_enabled=False,
                allow_side_effect_tools=False,
                allowed_tool_names=self._default_allowed_tool_names(),
                budgets=self._default_budget(),
                external_mcp_servers=[],
            )

        allowed_tool_names = self._sanitize_allowed_tools(stored.allowed_tool_names_json)
        if not allowed_tool_names:
            allowed_tool_names = self._default_allowed_tool_names()

        external_servers = [
            ExternalMCPServerPolicy.model_validate(server)
            for server in (stored.external_mcp_servers_json or [])
        ]
        return GovernancePolicyState(
            agentic_mode_enabled=stored.agentic_mode_enabled,
            mcp_exposure_enabled=stored.mcp_exposure_enabled,
            allow_side_effect_tools=stored.allow_side_effect_tools,
            allowed_tool_names=allowed_tool_names,
            budgets=GovernanceBudgetConfig(
                max_steps=stored.max_steps or settings.agent_max_steps,
                max_tool_calls_per_run=stored.max_tool_calls_per_run
                or settings.agent_tool_max_calls_per_run,
                max_tool_timeout_ms=stored.max_tool_timeout_ms or settings.agent_tool_timeout_ms,
                max_tool_input_bytes=stored.max_tool_input_bytes
                or settings.agent_tool_max_input_bytes,
                max_tool_output_bytes=stored.max_tool_output_bytes
                or settings.agent_tool_max_output_bytes,
                max_tool_retry_attempts=stored.max_tool_retry_attempts
                if stored.max_tool_retry_attempts is not None
                else settings.agent_tool_max_retry_attempts,
                max_total_tokens=stored.max_total_tokens,
                max_total_cost_usd=Decimal(str(stored.max_total_cost_usd))
                if stored.max_total_cost_usd is not None
                else None,
            ),
            external_mcp_servers=external_servers,
            provider_security=ProviderSecurityPolicy(
                local_only_mode=stored.local_only_mode,
                cloud_fallback_allowed=stored.cloud_fallback_allowed,
                allowed_provider_profiles=list(stored.allowed_provider_profiles_json or []),
                admin_only_model_selection=stored.admin_only_model_selection,
                retention_warning_acknowledged=stored.retention_warning_acknowledged,
            ),
        )

    def _sanitize_allowed_tools(self, candidates: list[str] | None) -> list[str]:
        if not candidates:
            return []
        allowed_tools: list[str] = []
        for name in candidates:
            normalized = name.strip()
            if not normalized:
                continue
            if normalized in self._tool_spec_by_name and normalized not in allowed_tools:
                allowed_tools.append(normalized)
        return allowed_tools

    def _resolve_mcp_status(self) -> GovernanceMCPStatus:
        return GovernanceMCPStatus(
            feature_enable_mcp=settings.feature_enable_mcp,
            mcp_transport=settings.mcp_transport.value,
            mcp_http_path=settings.mcp_http_path,
            mcp_http_host=settings.mcp_http_host,
            mcp_http_port=settings.mcp_http_port,
            mcp_auth_required=settings.mcp_require_bearer_auth,
            mcp_rate_limit_enabled=settings.mcp_rate_limit_enabled
            and settings.is_rate_limit_active,
            feature_enable_external_mcp_connectors=settings.feature_enable_external_mcp_connectors,
            configured_global_external_servers=len(settings.mcp_external_servers),
        )

    def _apply_update(
        self,
        *,
        current_state: GovernancePolicyState,
        payload: GovernancePolicyUpdateRequest,
    ) -> GovernancePolicyState:
        next_allowed = list(current_state.allowed_tool_names)
        if payload.allowed_tool_names is not None:
            unknown_names = [
                name for name in payload.allowed_tool_names if name not in self._tool_spec_by_name
            ]
            if unknown_names:
                joined = ", ".join(sorted(unknown_names))
                raise ValueError(f"Unsupported tool names: {joined}")
            next_allowed = self._sanitize_allowed_tools(payload.allowed_tool_names)

        next_allow_side_effects = (
            current_state.allow_side_effect_tools
            if payload.allow_side_effect_tools is None
            else payload.allow_side_effect_tools
        )
        selected_side_effect_tools = [
            name
            for name in next_allowed
            if self._tool_spec_by_name[name].effect_policy is ToolEffectPolicy.side_effect
        ]
        if selected_side_effect_tools and not next_allow_side_effects:
            raise ValueError("Side-effect tools require allow_side_effect_tools=true.")

        side_effect_mode_changed = (
            not current_state.allow_side_effect_tools and next_allow_side_effects
        ) or (
            set(selected_side_effect_tools)
            != {
                name
                for name in current_state.allowed_tool_names
                if self._tool_spec_by_name[name].effect_policy is ToolEffectPolicy.side_effect
            }
        )
        if side_effect_mode_changed and selected_side_effect_tools:
            if not payload.side_effect_warning_acknowledged:
                raise ValueError(
                    "side_effect_warning_acknowledged must be true when enabling or changing side-effect tools."
                )

        next_budgets = payload.budgets or current_state.budgets
        next_external_servers = (
            payload.external_mcp_servers
            if payload.external_mcp_servers is not None
            else current_state.external_mcp_servers
        )

        # F225: provider security update
        current_ps = current_state.provider_security
        if payload.provider_security is not None:
            ps_in = payload.provider_security
            # Re-enabling cloud fallback from local-only requires acknowledgment
            was_local_only = current_ps.local_only_mode
            turning_off_local_only = was_local_only and not ps_in.local_only_mode
            enabling_cloud_fallback = (
                not current_ps.cloud_fallback_allowed and ps_in.cloud_fallback_allowed
            )
            if (turning_off_local_only or enabling_cloud_fallback) and not payload.cloud_fallback_warning_acknowledged:
                raise ValueError(
                    "cloud_fallback_warning_acknowledged must be true when enabling cloud "
                    "provider access from a local-only deployment."
                )
            next_ps = ProviderSecurityPolicy(
                local_only_mode=ps_in.local_only_mode,
                cloud_fallback_allowed=ps_in.cloud_fallback_allowed,
                allowed_provider_profiles=list(ps_in.allowed_provider_profiles),
                admin_only_model_selection=ps_in.admin_only_model_selection,
                retention_warning_acknowledged=ps_in.retention_warning_acknowledged,
            )
        else:
            next_ps = current_ps

        return GovernancePolicyState(
            agentic_mode_enabled=current_state.agentic_mode_enabled
            if payload.agentic_mode_enabled is None
            else payload.agentic_mode_enabled,
            mcp_exposure_enabled=current_state.mcp_exposure_enabled
            if payload.mcp_exposure_enabled is None
            else payload.mcp_exposure_enabled,
            allow_side_effect_tools=next_allow_side_effects,
            allowed_tool_names=next_allowed,
            budgets=next_budgets,
            external_mcp_servers=next_external_servers,
            provider_security=next_ps,
        )

    def _resolve_warnings(self, *, policy_state: GovernancePolicyState) -> list[str]:
        warnings: list[str] = []
        side_effect_tools = [
            name
            for name in policy_state.allowed_tool_names
            if self._tool_spec_by_name[name].effect_policy is ToolEffectPolicy.side_effect
        ]
        if side_effect_tools:
            warnings.append(
                "Side-effect tools are enabled. Ensure approval policies are enforced for destructive operations."
            )
        if policy_state.mcp_exposure_enabled and not settings.feature_enable_mcp:
            warnings.append(
                "MCP exposure is enabled in policy, but FEATURE_ENABLE_MCP is disabled for this deployment."
            )
        if (
            policy_state.external_mcp_servers
            and not settings.feature_enable_external_mcp_connectors
        ):
            warnings.append(
                "External MCP servers are configured in policy, but global external MCP connectors are disabled."
            )
        if not policy_state.allowed_tool_names:
            warnings.append("No tools are allowlisted. Agent runs will not be able to call tools.")

        ps = policy_state.provider_security
        if ps.local_only_mode and ps.cloud_fallback_allowed:
            warnings.append(
                "local_only_mode is enabled but cloud_fallback_allowed is also true. "
                "Set cloud_fallback_allowed=false to guarantee no cloud provider is ever contacted."
            )
        if ps.local_only_mode and not ps.retention_warning_acknowledged:
            warnings.append(
                "Local-only mode is active. Ensure logs and traces do not forward data to "
                "cloud services. Acknowledge with retention_warning_acknowledged=true."
            )
        return warnings

    def _changed_fields(
        self,
        *,
        previous: GovernancePolicyState,
        current: GovernancePolicyState,
    ) -> list[str]:
        previous_payload = previous.model_dump(mode="json")
        current_payload = current.model_dump(mode="json")
        changed: list[str] = []
        for key, value in current_payload.items():
            if previous_payload.get(key) != value:
                changed.append(key)
        return changed
