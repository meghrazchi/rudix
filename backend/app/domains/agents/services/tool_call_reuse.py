"""Exactly-once side-effect tool calls across worker retries (R06-13).

Before a side-effect tool runs, ``AgentToolExecutor`` looks up a ``succeeded`` call of the
same run with the same idempotency key (``idx_agent_tool_calls_run_idem``). When one
exists, its stored (already redacted) output is returned instead of running the tool
again. The lookup happens after the role, organisation, and payload-budget checks, so a
principal who lost access is refused before any stored result is returned; the output
budget is checked again by ``build_tool_success_result``.

Inline runs use a fresh run id per request, so their keys never match an earlier call.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_agent_event
from app.core.metrics_workers import record_agent_tool_call_reused
from app.domains.agents.repositories import AgentRunWorkerRepository
from app.domains.agents.schemas import (
    ToolCall,
    ToolEffectPolicy,
    ToolResult,
    ToolSpec,
    build_tool_success_result,
)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


async def reusable_result(
    repository: AgentRunWorkerRepository,
    *,
    session: AsyncSession | None,
    spec: ToolSpec,
    call: ToolCall,
) -> ToolResult | None:
    """The stored result of this side-effect call, or ``None`` to execute it."""
    if session is None or spec.effect_policy is not ToolEffectPolicy.side_effect:
        return None
    if not call.idempotency_key:
        return None
    run_uuid = _uuid(call.run_id)
    org_uuid = _uuid(call.organization_id)
    if run_uuid is None or org_uuid is None:
        return None
    previous = await repository.find_succeeded_tool_call(
        session,
        agent_run_id=run_uuid,
        organization_id=org_uuid,
        idempotency_key=call.idempotency_key,
    )
    if previous is None:
        return None
    result = build_tool_success_result(
        spec, call, output=dict(previous.output_json or {}), latency_ms=0
    )
    record_agent_tool_call_reused(call.tool_name)
    log_agent_event(
        event="agent.tool_call.reused",
        organization_id=call.organization_id,
        user_id=call.user_id,
        run_id=call.run_id,
        tool_name=call.tool_name,
        call_id=call.call_id,
        previous_call_id=previous.call_id,
    )
    return result
