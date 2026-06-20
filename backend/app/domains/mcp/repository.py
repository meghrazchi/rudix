from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_policy import OrgMCPPolicy


class _Unset:
    """Sentinel for distinguishing None (explicit null) from missing."""


_UNSET = _Unset()


class MCPPolicyRepository:
    async def get(self, session: AsyncSession, *, organization_id: UUID) -> OrgMCPPolicy | None:
        result = await session.execute(
            select(OrgMCPPolicy).where(OrgMCPPolicy.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_or_default(self, session: AsyncSession, *, organization_id: UUID) -> OrgMCPPolicy:
        policy = await self.get(session, organization_id=organization_id)
        if policy is not None:
            return policy
        return OrgMCPPolicy(
            id=uuid4(),
            organization_id=organization_id,
            enabled=False,
            read_only=True,
            allowed_tools=None,
            capabilities_owner=None,
            capabilities_admin=None,
            capabilities_member=None,
            capabilities_viewer=None,
            rate_limit_enabled=True,
            rate_limit_requests=30,
            rate_limit_window_seconds=60,
            allowed_resources=None,
            allowed_prompts=None,
            allowed_collections=None,
            allowed_roles=None,
            redact_document_text=True,
            max_chunk_chars=None,
            max_request_bytes=None,
            max_response_bytes=None,
        )

    async def upsert(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        updated_by_user_id: UUID | None = None,
        enabled: bool | None = None,
        read_only: bool | None = None,
        allowed_tools: object = _UNSET,
        capabilities_owner: object = _UNSET,
        capabilities_admin: object = _UNSET,
        capabilities_member: object = _UNSET,
        capabilities_viewer: object = _UNSET,
        rate_limit_enabled: bool | None = None,
        rate_limit_requests: int | None = None,
        rate_limit_window_seconds: int | None = None,
        # F176 trust controls
        allowed_resources: object = _UNSET,
        allowed_prompts: object = _UNSET,
        allowed_collections: object = _UNSET,
        allowed_roles: object = _UNSET,
        redact_document_text: bool | None = None,
        max_chunk_chars: object = _UNSET,
        max_request_bytes: object = _UNSET,
        max_response_bytes: object = _UNSET,
    ) -> OrgMCPPolicy:
        policy = await self.get(session, organization_id=organization_id)
        if policy is None:
            policy = OrgMCPPolicy(
                id=uuid4(),
                organization_id=organization_id,
            )
            session.add(policy)

        if updated_by_user_id is not None:
            policy.updated_by_user_id = updated_by_user_id
        if enabled is not None:
            policy.enabled = enabled
        if read_only is not None:
            policy.read_only = read_only
        if not isinstance(allowed_tools, _Unset):
            policy.allowed_tools = allowed_tools  # type: ignore[assignment]
        if not isinstance(capabilities_owner, _Unset):
            policy.capabilities_owner = capabilities_owner  # type: ignore[assignment]
        if not isinstance(capabilities_admin, _Unset):
            policy.capabilities_admin = capabilities_admin  # type: ignore[assignment]
        if not isinstance(capabilities_member, _Unset):
            policy.capabilities_member = capabilities_member  # type: ignore[assignment]
        if not isinstance(capabilities_viewer, _Unset):
            policy.capabilities_viewer = capabilities_viewer  # type: ignore[assignment]
        if rate_limit_enabled is not None:
            policy.rate_limit_enabled = rate_limit_enabled
        if rate_limit_requests is not None:
            policy.rate_limit_requests = rate_limit_requests
        if rate_limit_window_seconds is not None:
            policy.rate_limit_window_seconds = rate_limit_window_seconds

        # F176 trust controls — all use _UNSET sentinel to allow explicit null
        if not isinstance(allowed_resources, _Unset):
            policy.allowed_resources = allowed_resources  # type: ignore[assignment]
        if not isinstance(allowed_prompts, _Unset):
            policy.allowed_prompts = allowed_prompts  # type: ignore[assignment]
        if not isinstance(allowed_collections, _Unset):
            policy.allowed_collections = allowed_collections  # type: ignore[assignment]
        if not isinstance(allowed_roles, _Unset):
            policy.allowed_roles = allowed_roles  # type: ignore[assignment]
        if redact_document_text is not None:
            policy.redact_document_text = redact_document_text
        if not isinstance(max_chunk_chars, _Unset):
            policy.max_chunk_chars = max_chunk_chars  # type: ignore[assignment]
        if not isinstance(max_request_bytes, _Unset):
            policy.max_request_bytes = max_request_bytes  # type: ignore[assignment]
        if not isinstance(max_response_bytes, _Unset):
            policy.max_response_bytes = max_response_bytes  # type: ignore[assignment]

        await session.flush()
        return policy
