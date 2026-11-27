from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import OrgScope, get_or_load
from app.core.cache_invalidation import mark_dirty
from app.core.config import settings
from app.models.agent_policy import AgentToolPolicyOverride

NAMESPACE_CHAT_TOOL_POLICY = "chat_tool_policy"
_TOOL_NAMES_ADAPTER: TypeAdapter[list[str]] = TypeAdapter(list[str])


class AgentToolPolicyRepository:
    async def list_by_organization(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[AgentToolPolicyOverride]:
        result = await session.execute(
            select(AgentToolPolicyOverride)
            .where(AgentToolPolicyOverride.organization_id == organization_id)
            .order_by(AgentToolPolicyOverride.tool_name)
        )
        return list(result.scalars().all())

    async def disabled_tool_names_cached(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> frozenset[str]:
        """Names of the organisation's disabled tools, cached per organisation (R05-05).

        Only the names are cached (namespace ``chat_tool_policy``, TTL
        ``CACHE_TTL_POLICIES_SECONDS``); any override write bumps the organisation's cache
        version on commit.
        """

        async def load() -> list[str]:
            overrides = await self.list_by_organization(session, organization_id=organization_id)
            return sorted(o.tool_name for o in overrides if not o.enabled)

        names = await get_or_load(
            scope=OrgScope(organization_id),
            namespace=NAMESPACE_CHAT_TOOL_POLICY,
            key_id="disabled",
            ttl=settings.cache_ttl_policies_seconds,
            adapter=_TOOL_NAMES_ADAPTER,
            loader=load,
        )
        return frozenset(names)

    async def get_by_tool(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        tool_name: str,
    ) -> AgentToolPolicyOverride | None:
        result = await session.execute(
            select(AgentToolPolicyOverride).where(
                AgentToolPolicyOverride.organization_id == organization_id,
                AgentToolPolicyOverride.tool_name == tool_name,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        tool_name: str,
        updated_by_user_id: UUID | None,
        enabled: bool,
        approval_required: bool | None,
        required_roles: list[str] | None,
        max_calls_per_run: int | None,
        max_input_bytes: int | None,
        max_output_bytes: int | None,
        timeout_ms: int | None,
        max_retry_attempts: int | None,
    ) -> AgentToolPolicyOverride:
        existing = await self.get_by_tool(
            session, organization_id=organization_id, tool_name=tool_name
        )
        if existing is None:
            override = AgentToolPolicyOverride(
                organization_id=organization_id,
                tool_name=tool_name,
                updated_by_user_id=updated_by_user_id,
                enabled=enabled,
                approval_required=approval_required,
                required_roles_json=required_roles,
                max_calls_per_run=max_calls_per_run,
                max_input_bytes=max_input_bytes,
                max_output_bytes=max_output_bytes,
                timeout_ms=timeout_ms,
                max_retry_attempts=max_retry_attempts,
            )
            session.add(override)
            await session.flush()
            await session.refresh(override)
            return override

        existing.updated_by_user_id = updated_by_user_id
        existing.enabled = enabled
        existing.approval_required = approval_required
        existing.required_roles_json = required_roles
        existing.max_calls_per_run = max_calls_per_run
        existing.max_input_bytes = max_input_bytes
        existing.max_output_bytes = max_output_bytes
        existing.timeout_ms = timeout_ms
        existing.max_retry_attempts = max_retry_attempts
        await session.flush()
        await session.refresh(existing)
        return existing

    async def delete_by_tool(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        tool_name: str,
    ) -> bool:
        result = await session.execute(
            delete(AgentToolPolicyOverride).where(
                AgentToolPolicyOverride.organization_id == organization_id,
                AgentToolPolicyOverride.tool_name == tool_name,
            )
        )
        # Core DELETE: no ORM flush event, so record the cache invalidation (R05-05).
        mark_dirty(session, org_ids=[organization_id])
        return int(getattr(result, "rowcount", 0) or 0) > 0
