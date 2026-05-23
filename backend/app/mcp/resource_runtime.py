from __future__ import annotations

from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_agent_event
from app.domains.agents.schemas import (
    ToolCall,
    ToolEffectPolicy,
    ToolErrorCode,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services import DocumentIntelligenceToolService, build_default_tool_specs
from app.mcp.auth import resolve_mcp_principal
from app.mcp.dependencies import get_http_headers_from_context
from app.mcp.policy import ensure_mcp_tool_capability
from app.mcp.rate_limit import (
    MCPRateLimiterUnavailableError,
    MCPRateLimitExceededError,
    enforce_mcp_rate_limit,
)
from app.mcp.resource_constants import _READONLY_RESOURCE_TOOL_NAMES
from app.mcp.resource_reader import MCPResourceReader
from app.mcp.resource_utils import safe_resource_error_payload


def _build_resource_tool_specs() -> dict[str, ToolSpec]:
    specs = build_default_tool_specs(
        max_calls_per_run=settings.agent_tool_max_calls_per_run,
        max_input_bytes=settings.agent_tool_max_input_bytes,
        max_output_bytes=settings.agent_tool_max_output_bytes,
        timeout_ms=settings.agent_tool_timeout_ms,
    )
    selected: dict[str, ToolSpec] = {}
    for spec in specs:
        if (
            spec.name in _READONLY_RESOURCE_TOOL_NAMES
            and spec.effect_policy is ToolEffectPolicy.read_only
            and ToolSurface.mcp in spec.surfaces
        ):
            selected[spec.name] = spec
    return selected


class MCPResourceRuntime:
    def __init__(
        self,
        *,
        service: DocumentIntelligenceToolService | None = None,
    ) -> None:
        self._service = service or DocumentIntelligenceToolService()
        self._tool_specs = _build_resource_tool_specs()
        self._reader = MCPResourceReader(execute_resource_tool=self._execute_resource_tool)

    async def _resolve_authorized_principal(
        self,
        *,
        resource: str,
        tool_name: str,
        request_id: str,
    ) -> AuthenticatedPrincipal | dict[str, Any]:
        if not settings.feature_enable_mcp:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.tool_unavailable,
                message="MCP is disabled for this deployment.",
                request_id=request_id,
            )

        tool_spec = self._tool_specs.get(tool_name)
        if tool_spec is None:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.tool_unavailable,
                message="Resource tool is not registered for this MCP server.",
                request_id=request_id,
            )

        try:
            principal = await resolve_mcp_principal(get_http_headers_from_context())
        except AuthenticationError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="Authentication failed for MCP resource request.",
                request_id=request_id,
            )
        except AuthorizationError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="MCP principal is not authorized for this operation.",
                request_id=request_id,
            )

        if principal.organization_id is None:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="No active organization context for principal.",
                request_id=request_id,
            )

        try:
            ensure_mcp_tool_capability(principal=principal, tool_spec=tool_spec)
        except AuthorizationError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="MCP principal capability is not authorized for this resource.",
                request_id=request_id,
            )

        try:
            await enforce_mcp_rate_limit(
                principal=principal,
                tool_name=f"resource:{resource}",
            )
        except MCPRateLimitExceededError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.rate_limit_exceeded,
                message="MCP rate limit exceeded. Retry later.",
                request_id=request_id,
            )
        except MCPRateLimiterUnavailableError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.rate_limiter_unavailable,
                message="MCP rate limiter unavailable for this deployment.",
                request_id=request_id,
            )

        return principal

    async def _execute_resource_tool(
        self,
        resource: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        principal_or_error = await self._resolve_authorized_principal(
            resource=resource,
            tool_name=tool_name,
            request_id=request_id,
        )
        if isinstance(principal_or_error, dict):
            return principal_or_error

        principal = principal_or_error
        organization_id = principal.organization_id
        if organization_id is None:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="No active organization context for principal.",
                request_id=request_id,
            )

        call = ToolCall(
            run_id=str(uuid4()),
            tool_name=tool_name,
            organization_id=organization_id,
            user_id=principal.user_id,
            surface=ToolSurface.mcp,
            arguments=arguments,
        )

        try:
            if tool_name == "search_documents":
                data = await self._service.search_documents(call, principal)
            elif tool_name == "get_document_detail":
                data = await self._service.get_document_detail(call, principal)
            elif tool_name == "list_document_chunks":
                data = await self._service.list_document_chunks(call, principal)
            elif tool_name == "answer_from_context":
                data = await self._service.answer_from_context(call, principal)
            else:
                return safe_resource_error_payload(
                    resource=resource,
                    code=ToolErrorCode.tool_unavailable,
                    message="Resource tool is not implemented.",
                    request_id=request_id,
                )
        except ValueError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.validation_failed,
                message="Resource request validation failed.",
                request_id=request_id,
            )
        except AuthorizationError:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.authorization_failed,
                message="Resource access is not allowed for this principal.",
                request_id=request_id,
            )
        except Exception:
            return safe_resource_error_payload(
                resource=resource,
                code=ToolErrorCode.internal_error,
                message="Resource execution failed unexpectedly.",
                request_id=request_id,
            )

        log_agent_event(
            event="mcp.resource.read.completed",
            organization_id=organization_id,
            user_id=principal.user_id,
            run_id=call.run_id,
            tool_name=tool_name,
            success=True,
            request_id=request_id,
        )
        return {"ok": True, "resource": resource, "data": data}

    async def read_documents(
        self,
        *,
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 10,
        offset: int = 0,
        query: str | None = None,
    ) -> dict[str, Any]:
        return await self._reader.read_documents(
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            query=query,
        )

    async def read_document_detail(self, *, document_id: str) -> dict[str, Any]:
        return await self._reader.read_document_detail(document_id=document_id)

    async def read_document_status(self, *, document_id: str) -> dict[str, Any]:
        return await self._reader.read_document_status(document_id=document_id)

    async def read_document_chunks(
        self,
        *,
        document_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self._reader.read_document_chunks(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    async def read_search_context(
        self,
        *,
        query: str,
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self._reader.read_search_context(
            query=query,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def read_citations(
        self,
        *,
        query: str,
        document_id: str | None = None,
        top_k: int = 4,
        rerank: bool = True,
    ) -> dict[str, Any]:
        return await self._reader.read_citations(
            query=query,
            document_id=document_id,
            top_k=top_k,
            rerank=rerank,
        )


@lru_cache(maxsize=1)
def build_mcp_resource_runtime() -> MCPResourceRuntime:
    return MCPResourceRuntime()
