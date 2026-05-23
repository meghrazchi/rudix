from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.auth.models import AuthenticatedPrincipal
from app.core.config import MCPExternalServerSettings, settings
from app.core.logging import get_logger, log_agent_event
from app.domains.agents.schemas import (
    ToolBudget,
    ToolCall,
    ToolEffectPolicy,
    ToolRedactionPolicy,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services.tool_registry import ToolHandler, ToolRegistry
from app.models.enums import OrganizationRole

from .http_client import ExternalMCPHTTPClient
from .types import ExternalMCPClientError, ExternalMCPDiscoveredTool, ExternalMCPDiscoverySnapshot

_logger = get_logger("services.agent.external_mcp")


class _ExternalMCPClientLike(Protocol):
    async def discover(self) -> ExternalMCPDiscoverySnapshot: ...

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        context_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExternalMCPRegistrationSummary:
    enabled: bool
    configured_servers: int
    discovered_servers: int
    registered_tools: tuple[str, ...]
    discovered_resources: dict[str, tuple[str, ...]]
    warnings: tuple[str, ...]


class ExternalMCPToolManager:
    def __init__(
        self,
        *,
        external_servers: tuple[MCPExternalServerSettings, ...] | None = None,
        feature_enabled: bool | None = None,
        client_factory: Callable[[MCPExternalServerSettings], _ExternalMCPClientLike] | None = None,
    ) -> None:
        configured_servers = external_servers
        if configured_servers is None:
            configured_servers = tuple(settings.mcp_external_servers)
        self._servers = tuple(server for server in configured_servers if server.enabled)
        self._feature_enabled = (
            settings.feature_enable_external_mcp_connectors
            if feature_enabled is None
            else feature_enabled
        )
        self._client_factory = client_factory or self._default_client_factory
        self._clients: dict[str, _ExternalMCPClientLike] = {}
        self._registered = False
        self._lock = asyncio.Lock()
        self._last_summary = ExternalMCPRegistrationSummary(
            enabled=self._feature_enabled,
            configured_servers=len(self._servers),
            discovered_servers=0,
            registered_tools=(),
            discovered_resources={},
            warnings=(),
        )

    @staticmethod
    def _default_client_factory(server: MCPExternalServerSettings) -> _ExternalMCPClientLike:
        return ExternalMCPHTTPClient(server=server)

    @property
    def enabled(self) -> bool:
        return self._feature_enabled and bool(self._servers)

    @property
    def summary(self) -> ExternalMCPRegistrationSummary:
        return self._last_summary

    async def ensure_registered(self, *, registry: ToolRegistry) -> ExternalMCPRegistrationSummary:
        if not self.enabled:
            return self._last_summary
        if self._registered:
            return self._last_summary
        async with self._lock:
            if self._registered:
                return self._last_summary

            warnings: list[str] = []
            discovered_resources: dict[str, tuple[str, ...]] = {}
            registered_tools: list[str] = []
            discovered_servers = 0

            for server in self._servers:
                client = self._clients.get(server.server_id)
                if client is None:
                    client = self._client_factory(server)
                    self._clients[server.server_id] = client

                try:
                    snapshot = await client.discover()
                except ExternalMCPClientError as exc:
                    warning = f"external server '{server.server_id}' discovery failed: {exc}"
                    warnings.append(warning)
                    _logger.warning(
                        "agent.external_mcp.discovery_failed",
                        server_id=server.server_id,
                        warning=str(exc),
                    )
                    continue

                discovered_servers += 1
                discovered_resources[server.server_id] = snapshot.resources
                if snapshot.warning:
                    warnings.append(
                        f"external server '{server.server_id}' resources warning: {snapshot.warning}"
                    )
                for discovered_tool in snapshot.tools:
                    if discovered_tool.name not in server.allow_tools:
                        continue
                    internal_name = self._build_internal_tool_name(
                        server=server,
                        external_tool_name=discovered_tool.name,
                        registry=registry,
                    )
                    spec = self._build_tool_spec(
                        server=server,
                        discovered_tool=discovered_tool,
                        internal_name=internal_name,
                    )
                    handler = self._build_tool_handler(
                        client=client,
                        server=server,
                        external_tool_name=discovered_tool.name,
                    )
                    registry.register_tool(spec=spec, handler=handler)
                    registered_tools.append(internal_name)

            self._registered = True
            self._last_summary = ExternalMCPRegistrationSummary(
                enabled=self.enabled,
                configured_servers=len(self._servers),
                discovered_servers=discovered_servers,
                registered_tools=tuple(sorted(registered_tools)),
                discovered_resources=discovered_resources,
                warnings=tuple(warnings),
            )
            _logger.info(
                "agent.external_mcp.registration_completed",
                configured_servers=len(self._servers),
                discovered_servers=discovered_servers,
                registered_tool_count=len(registered_tools),
                warning_count=len(warnings),
            )
            return self._last_summary

    def _build_internal_tool_name(
        self,
        *,
        server: MCPExternalServerSettings,
        external_tool_name: str,
        registry: ToolRegistry,
    ) -> str:
        server_slug = self._slug(server.server_id)
        tool_slug = self._slug(external_tool_name)
        base_name = f"external_mcp.{server_slug}.{tool_slug}"
        candidate = base_name
        suffix = 2
        while registry.get_spec(candidate) is not None:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _slug(value: str) -> str:
        lowered = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "tool"

    def _build_tool_spec(
        self,
        *,
        server: MCPExternalServerSettings,
        discovered_tool: ExternalMCPDiscoveredTool,
        internal_name: str,
    ) -> ToolSpec:
        is_read_only = discovered_tool.name in server.read_only_tools
        effect_policy = ToolEffectPolicy.read_only if is_read_only else ToolEffectPolicy.side_effect
        approval_required = (
            False
            if effect_policy is ToolEffectPolicy.read_only
            else server.approval_required_for_side_effect
        )
        budget = ToolBudget(
            max_calls_per_run=server.budget_max_calls_per_run
            or settings.agent_tool_max_calls_per_run,
            max_input_bytes=server.budget_max_input_bytes or settings.agent_tool_max_input_bytes,
            max_output_bytes=server.budget_max_output_bytes or settings.agent_tool_max_output_bytes,
            timeout_ms=server.budget_timeout_ms or settings.agent_tool_timeout_ms,
            max_retry_attempts=server.budget_max_retry_attempts
            if server.budget_max_retry_attempts is not None
            else settings.agent_tool_max_retry_attempts,
        )
        surfaces = [ToolSurface.api]
        if server.expose_on_mcp_surface:
            surfaces.append(ToolSurface.mcp)
        return ToolSpec(
            name=internal_name,
            description=(
                f"External MCP tool '{discovered_tool.name}' from server '{server.server_id}'."
            ),
            capability=f"{server.capability_prefix}.{self._slug(server.server_id)}.{self._slug(discovered_tool.name)}",
            effect_policy=effect_policy,
            required_roles=server.required_roles or [OrganizationRole.owner.value],
            organization_scoped=True,
            approval_required=approval_required,
            surfaces=surfaces,
            budget=budget,
            redaction=ToolRedactionPolicy(
                input_keys=["authorization", "token", "password", "prompt", "question"],
                output_keys=["authorization", "token", "password", "secret", "api_key"],
            ),
        )

    def _build_tool_handler(
        self,
        *,
        client: _ExternalMCPClientLike,
        server: MCPExternalServerSettings,
        external_tool_name: str,
    ) -> ToolHandler:
        async def _handler(
            call: ToolCall,
            principal: AuthenticatedPrincipal,
        ) -> dict[str, Any]:
            request_context_headers = {
                "x-rudix-organization-id": call.organization_id,
                "x-rudix-user-id": call.user_id,
                "x-rudix-run-id": call.run_id,
            }
            log_agent_event(
                event="agent.external_mcp.tool_call.started",
                organization_id=call.organization_id,
                user_id=call.user_id,
                run_id=call.run_id,
                tool_name=call.tool_name,
                external_server_id=server.server_id,
                external_tool_name=external_tool_name,
            )
            try:
                output = await client.call_tool(
                    tool_name=external_tool_name,
                    arguments=call.arguments,
                    context_headers=request_context_headers,
                )
            except ExternalMCPClientError as exc:
                log_agent_event(
                    event="agent.external_mcp.tool_call.failed",
                    organization_id=call.organization_id,
                    user_id=call.user_id,
                    run_id=call.run_id,
                    tool_name=call.tool_name,
                    external_server_id=server.server_id,
                    external_tool_name=external_tool_name,
                    error=exc.__class__.__name__,
                )
                raise ValueError(
                    f"External MCP tool call failed for server '{server.server_id}'."
                ) from exc

            del principal
            log_agent_event(
                event="agent.external_mcp.tool_call.completed",
                organization_id=call.organization_id,
                user_id=call.user_id,
                run_id=call.run_id,
                tool_name=call.tool_name,
                external_server_id=server.server_id,
                external_tool_name=external_tool_name,
            )
            return output

        return _handler
