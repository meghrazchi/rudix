from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth.errors import AuthenticationError, AuthorizationError
from app.core.config import MCPTransport, settings
from app.core.logging import get_logger, log_agent_event
from app.db.session import check_database_health
from app.domains.agents.schemas import (
    ToolCall,
    ToolEffectPolicy,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services import (
    AgentToolExecutor,
    ToolRegistry,
    build_default_tool_specs,
    register_document_intelligence_handlers,
)
from app.mcp.auth import resolve_mcp_principal
from app.mcp.dependencies import (
    MCPSDKUnavailableError,
    build_streamable_http_app,
    get_http_headers_from_context,
    load_fastmcp_class,
)
from app.mcp.policy import ensure_mcp_tool_capability
from app.mcp.prompts import register_mcp_prompts
from app.mcp.rate_limit import (
    MCPRateLimiterUnavailableError,
    MCPRateLimitExceededError,
    enforce_mcp_rate_limit,
)
from app.mcp.resources import register_mcp_resources
from app.mcp.tool_catalog import MCPToolBinding, build_mcp_tool_bindings

_logger = get_logger("mcp.server")

_SUPPORTED_INTERNAL_MCP_TOOL_NAMES = {
    "search_documents",
    "get_document_detail",
    "list_document_chunks",
    "answer_from_context",
    "summarize_document",
    "compare_documents",
}


def _openai_config_ready() -> tuple[bool, str | None]:
    requires_openai = (
        settings.feature_enable_embeddings
        or settings.feature_enable_llm
        or settings.feature_enable_evaluations
    )
    if not requires_openai:
        return True, None
    if settings.openai_api_key is None:
        return False, "openai_api_key_missing"
    return True, None


def _check_qdrant_direct() -> bool:
    try:
        from app.clients.factory import create_qdrant_client

        client = create_qdrant_client(settings)
        try:
            client.get_collections()
            return True
        finally:
            client.close()
    except Exception:
        return False


async def _readiness_payload() -> tuple[int, dict[str, Any]]:
    openai_ok, openai_detail = _openai_config_ready()
    database_ok, qdrant_ok = await asyncio.gather(
        check_database_health(),
        asyncio.to_thread(_check_qdrant_direct),
    )

    sdk_ok = True
    try:
        load_fastmcp_class()
    except MCPSDKUnavailableError:
        sdk_ok = False

    dependencies = {
        "feature_flag": {
            "ok": bool(settings.feature_enable_mcp),
            "detail": None if settings.feature_enable_mcp else "feature_enable_mcp_false",
        },
        "mcp_sdk": {
            "ok": sdk_ok,
            "detail": None if sdk_ok else "mcp_sdk_unavailable",
        },
        "database": {
            "ok": bool(database_ok),
            "detail": None if database_ok else "database_unreachable",
        },
        "qdrant": {
            "ok": bool(qdrant_ok),
            "detail": None if qdrant_ok else "qdrant_unreachable",
        },
        "openai_config": {
            "ok": bool(openai_ok),
            "detail": openai_detail,
        },
    }
    failed_dependencies = [
        name for name, dependency in dependencies.items() if not bool(dependency["ok"])
    ]
    status_code = 200 if not failed_dependencies else 503
    status_value = "ok" if not failed_dependencies else "degraded"
    return status_code, {
        "status": status_value,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "dependencies": dependencies,
        "failed_dependencies": failed_dependencies,
    }


def _safe_tool_error_payload(
    *,
    tool_name: str,
    code: ToolErrorCode,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return ToolResult(
        call_id=str(uuid4()),
        tool_name=tool_name,
        success=False,
        output=None,
        latency_ms=None,
        error=ToolError(
            code=code,
            safe_message=message,
            retryable=False,
            request_id=request_id,
            details={},
        ),
    ).model_dump(mode="json")


@lru_cache(maxsize=1)
def _build_mcp_registry() -> ToolRegistry:
    selected_specs = tuple(
        spec
        for spec in build_default_tool_specs(
            max_calls_per_run=settings.agent_tool_max_calls_per_run,
            max_input_bytes=settings.agent_tool_max_input_bytes,
            max_output_bytes=settings.agent_tool_max_output_bytes,
            timeout_ms=settings.agent_tool_timeout_ms,
        )
        if spec.name in _SUPPORTED_INTERNAL_MCP_TOOL_NAMES
        and ToolSurface.mcp in spec.surfaces
        and spec.effect_policy is ToolEffectPolicy.read_only
    )
    registry = ToolRegistry(specs=selected_specs)
    register_document_intelligence_handlers(registry=registry)
    return registry


class MCPToolRuntime:
    def __init__(self) -> None:
        self._registry = _build_mcp_registry()
        self._bindings = build_mcp_tool_bindings(internal_specs=self._registry.list_specs())
        self._executor = AgentToolExecutor(registry=self._registry)

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def bindings(self) -> dict[str, MCPToolBinding]:
        return self._bindings

    def list_public_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(
            sorted(
                (binding.public_spec for binding in self._bindings.values()),
                key=lambda spec: spec.name,
            )
        )

    async def execute_tool(
        self, *, tool_name: str, arguments: dict[str, Any] | None
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        binding = self._bindings.get(tool_name)
        if binding is None:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.tool_unavailable,
                message="Tool is not registered for this MCP server.",
                request_id=request_id,
            )
        spec = self._registry.get_spec(binding.internal_name)
        if spec is None:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.tool_unavailable,
                message="Mapped internal tool is unavailable for this MCP server.",
                request_id=request_id,
            )

        if not settings.feature_enable_mcp:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.tool_unavailable,
                message="MCP is disabled for this deployment.",
                request_id=request_id,
            )

        try:
            principal = await resolve_mcp_principal(get_http_headers_from_context())
        except AuthenticationError:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.authorization_failed,
                message="Authentication failed for MCP request.",
                request_id=request_id,
            )
        except AuthorizationError:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.authorization_failed,
                message="MCP principal is not authorized for this operation.",
                request_id=request_id,
            )

        if principal.organization_id is None:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.authorization_failed,
                message="No active organization context for principal.",
                request_id=request_id,
            )

        try:
            ensure_mcp_tool_capability(principal=principal, tool_spec=binding.public_spec)
        except AuthorizationError:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.authorization_failed,
                message="MCP principal capability is not authorized for this tool.",
                request_id=request_id,
            )

        try:
            await enforce_mcp_rate_limit(principal=principal, tool_name=tool_name)
        except MCPRateLimitExceededError:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.rate_limit_exceeded,
                message="MCP rate limit exceeded. Retry later.",
                request_id=request_id,
            )
        except MCPRateLimiterUnavailableError:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.rate_limiter_unavailable,
                message="MCP rate limiter unavailable for this deployment.",
                request_id=request_id,
            )

        try:
            normalized_arguments = binding.normalize_arguments(arguments)
        except Exception:
            return _safe_tool_error_payload(
                tool_name=tool_name,
                code=ToolErrorCode.validation_failed,
                message="Tool arguments failed validation for this MCP tool.",
                request_id=request_id,
            )

        call = ToolCall(
            run_id=str(uuid4()),
            tool_name=binding.internal_name,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            surface=ToolSurface.mcp,
            arguments=normalized_arguments,
        )

        result = await self._executor.execute(
            session=None,
            call=call,
            principal=principal,
            request_id=request_id,
        )
        log_agent_event(
            event="mcp.tool_call.completed",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            run_id=call.run_id,
            tool_name=binding.internal_name,
            mcp_tool_name=tool_name,
            success=result.success,
            request_id=request_id,
        )
        payload = result.model_dump(mode="json")
        payload["tool_name"] = tool_name
        if result.success and isinstance(payload.get("output"), dict):
            payload["output"] = binding.normalize_output(payload["output"])
        return payload


@lru_cache(maxsize=1)
def _build_mcp_tool_runtime() -> MCPToolRuntime:
    return MCPToolRuntime()


def _register_tools(server: Any, runtime: MCPToolRuntime) -> None:
    def _build_handler(bound_tool_name: str, description: str) -> Any:
        async def tool_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
            return await runtime.execute_tool(tool_name=bound_tool_name, arguments=arguments)

        tool_handler.__name__ = f"tool_{bound_tool_name.replace('.', '_')}"
        tool_handler.__doc__ = (
            f"{description}\n\nProvide tool parameters in the `arguments` object."
        )
        return tool_handler

    for spec in runtime.list_public_specs():
        tool_name = spec.name
        handler = _build_handler(tool_name, spec.description)
        try:
            server.tool(name=tool_name, description=spec.description)(handler)
        except TypeError:
            server.tool(handler, name=tool_name, description=spec.description)


@lru_cache(maxsize=1)
def build_mcp_server() -> Any:
    FastMCP = load_fastmcp_class()
    server = FastMCP(name=settings.mcp_server_name)
    _register_tools(server, _build_mcp_tool_runtime())
    register_mcp_resources(server)
    register_mcp_prompts(server)
    return server


def create_mcp_http_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.mcp_server_name} HTTP Gateway",
        version=settings.api_version,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "service": "mcp",
            "transport": settings.mcp_transport.value,
            "mcp_path": settings.mcp_http_path,
            "feature_enable_mcp": settings.feature_enable_mcp,
            "auth_required": settings.mcp_require_bearer_auth,
            "rate_limit_enabled": settings.mcp_rate_limit_enabled and settings.is_rate_limit_active,
        }

    @app.get("/ready")
    async def ready() -> JSONResponse:
        status_code, payload = await _readiness_payload()
        return JSONResponse(status_code=status_code, content=payload)

    mcp_server = build_mcp_server()
    mcp_http_app = build_streamable_http_app(server=mcp_server, path=settings.mcp_http_path)
    app.mount("/", mcp_http_app)
    return app


def run_stdio_server() -> None:
    if not settings.feature_enable_mcp:
        raise RuntimeError(
            "MCP runtime is disabled. Set FEATURE_ENABLE_MCP=true to start the MCP server."
        )
    if settings.mcp_transport != MCPTransport.stdio:
        _logger.warning(
            "mcp.run.stdio.override",
            configured_transport=settings.mcp_transport.value,
            requested_transport=MCPTransport.stdio.value,
        )
    server = build_mcp_server()
    server.run(transport="stdio")


def run_streamable_http_server() -> None:
    if not settings.feature_enable_mcp:
        raise RuntimeError(
            "MCP runtime is disabled. Set FEATURE_ENABLE_MCP=true to start the MCP server."
        )
    import uvicorn

    app = create_mcp_http_app()
    uvicorn.run(
        app,
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        log_level=settings.log_level.lower(),
    )
