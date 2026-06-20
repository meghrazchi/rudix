from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.repositories.governance import GovernancePolicyRepository
from app.domains.agents.repositories.agent_policy import AgentToolPolicyRepository
from app.domains.agents.schemas.agent_policy import (
    AgentPolicyResponse,
    EffectivePolicyResponse,
    OrgBudgetPolicySummary,
    OrgToolPolicyOverride,
    ToolPolicyOverrideState,
    ToolPolicyUpsertRequest,
    ToolPolicyUpsertResponse,
)
from app.domains.agents.schemas.agent_tools import ToolSpec
from app.domains.agents.services.tool_registry import build_default_tool_specs
from app.models.agent import AgentRun
from app.models.agent_policy import AgentToolPolicyOverride


class AgentPolicyService:
    def __init__(
        self,
        *,
        tool_policy_repository: AgentToolPolicyRepository | None = None,
        governance_repository: GovernancePolicyRepository | None = None,
        tool_specs: tuple[ToolSpec, ...] | None = None,
    ) -> None:
        self._tool_policy_repo = tool_policy_repository or AgentToolPolicyRepository()
        self._governance_repo = governance_repository or GovernancePolicyRepository()
        self._tool_specs = tool_specs or build_default_tool_specs(
            max_calls_per_run=settings.agent_tool_max_calls_per_run,
            max_input_bytes=settings.agent_tool_max_input_bytes,
            max_output_bytes=settings.agent_tool_max_output_bytes,
            timeout_ms=settings.agent_tool_timeout_ms,
        )
        self._spec_by_name = {spec.name: spec for spec in self._tool_specs}

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_policy(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> AgentPolicyResponse:
        overrides = await self._tool_policy_repo.list_by_organization(
            session, organization_id=organization_id
        )
        override_by_name = {o.tool_name: o for o in overrides}
        governance = await self._governance_repo.get_by_organization(
            session, organization_id=organization_id
        )

        org_budget = _budget_from_governance(governance)
        tool_overrides = [_to_org_tool_override(o) for o in overrides]
        resolved = [
            self._resolve_tool_state(spec, override_by_name.get(spec.name))
            for spec in sorted(self._tool_specs, key=lambda s: s.name)
        ]

        policy_updated_at: datetime | None = None
        if overrides:
            policy_updated_at = max(o.updated_at for o in overrides if o.updated_at)

        return AgentPolicyResponse(
            organization_id=str(organization_id),
            org_budget=org_budget,
            tool_overrides=tool_overrides,
            resolved_tools=resolved,
            policy_updated_at=policy_updated_at,
        )

    async def get_effective_policy_for_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        run: AgentRun,
    ) -> EffectivePolicyResponse:
        snapshot = run.policy_snapshot_json or {}
        overrides = await self._tool_policy_repo.list_by_organization(
            session, organization_id=organization_id
        )
        override_by_name = {o.tool_name: o for o in overrides}
        governance = await self._governance_repo.get_by_organization(
            session, organization_id=organization_id
        )

        resolved = [
            self._resolve_tool_state(spec, override_by_name.get(spec.name))
            for spec in sorted(self._tool_specs, key=lambda s: s.name)
        ]

        snapshot_at_str: str | None = (
            snapshot.get("recorded_at") if isinstance(snapshot, dict) else None
        )
        snapshot_at: datetime | None = None
        if snapshot_at_str:
            try:
                snapshot_at = datetime.fromisoformat(snapshot_at_str)
            except ValueError:
                pass

        return EffectivePolicyResponse(
            run_id=str(run.id),
            organization_id=str(organization_id),
            snapshot=snapshot if snapshot else None,
            resolved_tools=resolved,
            org_budget=_budget_from_governance(governance),
            snapshot_recorded_at=snapshot_at,
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def upsert_tool_override(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        tool_name: str,
        updated_by_user_id: UUID,
        request: ToolPolicyUpsertRequest,
    ) -> ToolPolicyUpsertResponse:
        if tool_name not in self._spec_by_name:
            raise ValueError(f"Unknown tool: {tool_name!r}")

        override = await self._tool_policy_repo.upsert(
            session,
            organization_id=organization_id,
            tool_name=tool_name,
            updated_by_user_id=updated_by_user_id,
            enabled=request.enabled,
            approval_required=request.approval_required,
            required_roles=request.required_roles,
            max_calls_per_run=request.max_calls_per_run,
            max_input_bytes=request.max_input_bytes,
            max_output_bytes=request.max_output_bytes,
            timeout_ms=request.timeout_ms,
            max_retry_attempts=request.max_retry_attempts,
        )
        return ToolPolicyUpsertResponse(
            organization_id=str(organization_id),
            override=_to_org_tool_override(override),
            audit_recorded=False,
        )

    async def delete_tool_override(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        tool_name: str,
    ) -> bool:
        return await self._tool_policy_repo.delete_by_tool(
            session, organization_id=organization_id, tool_name=tool_name
        )

    # ------------------------------------------------------------------
    # Policy enforcement
    # ------------------------------------------------------------------

    def check_tool_allowed(
        self,
        tool_name: str,
        override: AgentToolPolicyOverride | None,
        allowed_tool_names: list[str],
    ) -> bool:
        """Return False if the tool is disabled by org governance or per-tool override."""
        if allowed_tool_names and tool_name not in allowed_tool_names:
            return False
        if override is not None and not override.enabled:
            return False
        return True

    def is_run_over_budget(
        self,
        run: AgentRun,
        *,
        org_max_steps: int | None,
        org_max_tool_calls: int | None,
        org_max_total_cost_usd: Decimal | None,
    ) -> tuple[bool, str]:
        """Return (exceeded, reason) for mid-run budget enforcement."""
        budget: dict[str, Any] = run.budget_json or {}
        costs: dict[str, Any] = run.costs_json or {}

        steps_taken: int = costs.get("steps_taken", 0) or 0
        tool_calls_made: int = costs.get("tool_calls_made", 0) or 0
        total_cost_usd_raw = costs.get("total_cost_usd", 0)
        try:
            total_cost_usd: Decimal = Decimal(str(total_cost_usd_raw))
        except Exception:
            total_cost_usd = Decimal("0")

        run_max_steps: int | None = run.max_steps or budget.get("max_steps")
        effective_max_steps = _min_non_none(run_max_steps, org_max_steps)
        if effective_max_steps is not None and steps_taken >= effective_max_steps:
            return (
                True,
                f"Budget exceeded: steps_taken={steps_taken} >= max_steps={effective_max_steps}",
            )

        run_max_tool_calls: int | None = budget.get("max_tool_calls")
        effective_max_tool_calls = _min_non_none(run_max_tool_calls, org_max_tool_calls)
        if effective_max_tool_calls is not None and tool_calls_made >= effective_max_tool_calls:
            return (
                True,
                f"Budget exceeded: tool_calls_made={tool_calls_made} >= max_tool_calls={effective_max_tool_calls}",
            )

        run_max_cost_raw = budget.get("max_total_cost_usd")
        run_max_cost: Decimal | None = None
        if run_max_cost_raw is not None:
            try:
                run_max_cost = Decimal(str(run_max_cost_raw))
            except Exception:
                pass
        effective_max_cost = _decimal_min_non_none(run_max_cost, org_max_total_cost_usd)
        if effective_max_cost is not None and total_cost_usd >= effective_max_cost:
            return (
                True,
                f"Budget exceeded: total_cost_usd={total_cost_usd} >= max_total_cost_usd={effective_max_cost}",
            )

        return False, ""

    def build_policy_snapshot(
        self,
        *,
        org_budget: OrgBudgetPolicySummary,
        resolved_tools: list[ToolPolicyOverrideState],
    ) -> dict[str, Any]:
        return {
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "org_budget": org_budget.model_dump(),
            "resolved_tools": [t.model_dump() for t in resolved_tools],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_tool_state(
        self,
        spec: ToolSpec,
        override: AgentToolPolicyOverride | None,
    ) -> ToolPolicyOverrideState:
        is_overridden = override is not None
        return ToolPolicyOverrideState(
            tool_name=spec.name,
            enabled=override.enabled if is_overridden else True,
            approval_required=(
                override.approval_required
                if (is_overridden and override.approval_required is not None)
                else spec.approval_required
            ),
            required_roles=(
                override.required_roles_json
                if (is_overridden and override.required_roles_json)
                else list(spec.required_roles)
            ),
            max_calls_per_run=(
                override.max_calls_per_run
                if (is_overridden and override.max_calls_per_run is not None)
                else spec.budget.max_calls_per_run
            ),
            max_input_bytes=(
                override.max_input_bytes
                if (is_overridden and override.max_input_bytes is not None)
                else spec.budget.max_input_bytes
            ),
            max_output_bytes=(
                override.max_output_bytes
                if (is_overridden and override.max_output_bytes is not None)
                else spec.budget.max_output_bytes
            ),
            timeout_ms=(
                override.timeout_ms
                if (is_overridden and override.timeout_ms is not None)
                else spec.budget.timeout_ms
            ),
            max_retry_attempts=(
                override.max_retry_attempts
                if (is_overridden and override.max_retry_attempts is not None)
                else spec.budget.max_retry_attempts
            ),
            is_overridden=is_overridden,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _budget_from_governance(governance: Any) -> OrgBudgetPolicySummary:
    if governance is None:
        return OrgBudgetPolicySummary()
    return OrgBudgetPolicySummary(
        max_steps=governance.max_steps,
        max_tool_calls_per_run=governance.max_tool_calls_per_run,
        max_tool_timeout_ms=governance.max_tool_timeout_ms,
        max_tool_input_bytes=governance.max_tool_input_bytes,
        max_tool_output_bytes=governance.max_tool_output_bytes,
        max_tool_retry_attempts=governance.max_tool_retry_attempts,
        max_total_tokens=governance.max_total_tokens,
        max_total_cost_usd=float(governance.max_total_cost_usd)
        if governance.max_total_cost_usd is not None
        else None,
    )


def _to_org_tool_override(override: AgentToolPolicyOverride) -> OrgToolPolicyOverride:
    return OrgToolPolicyOverride(
        tool_name=override.tool_name,
        enabled=override.enabled,
        approval_required=override.approval_required,
        required_roles=override.required_roles_json,
        max_calls_per_run=override.max_calls_per_run,
        max_input_bytes=override.max_input_bytes,
        max_output_bytes=override.max_output_bytes,
        timeout_ms=override.timeout_ms,
        max_retry_attempts=override.max_retry_attempts,
        updated_at=override.updated_at,
        updated_by_user_id=str(override.updated_by_user_id)
        if override.updated_by_user_id
        else None,
    )


def _min_non_none(a: int | None, b: int | None) -> int | None:
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _decimal_min_non_none(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)
