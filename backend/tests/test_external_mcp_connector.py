import os
from typing import Any
from uuid import uuid4

# Ensure strict settings can be loaded when app imports in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.models import AuthenticatedPrincipal
from app.core.config import MCPExternalServerSettings
from app.domains.agents.schemas import ToolCall, ToolErrorCode, ToolSurface
from app.domains.agents.services import AgentToolExecutor, ToolRegistry, build_default_tool_specs
from app.domains.agents.services.external_mcp import (
    ExternalMCPDiscoveredTool,
    ExternalMCPDiscoverySnapshot,
    ExternalMCPProtocolError,
    ExternalMCPToolManager,
)


async def test_external_mcp_manager_registers_allowlisted_tool() -> None:
    captured_headers: dict[str, str] = {}

    class _FakeClient:
        async def discover(self) -> ExternalMCPDiscoverySnapshot:
            return ExternalMCPDiscoverySnapshot(
                server_id="acme_tools",
                tools=(
                    ExternalMCPDiscoveredTool(
                        name="lookup_customer",
                        description="Fetch customer profile.",
                        input_schema={},
                    ),
                    ExternalMCPDiscoveredTool(
                        name="hidden_tool",
                        description="Should not be exposed.",
                        input_schema={},
                    ),
                ),
                resources=("acme://customers",),
            )

        async def call_tool(
            self,
            *,
            tool_name: str,
            arguments: dict[str, Any],
            context_headers: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            del arguments
            captured_headers.update(context_headers or {})
            return {
                "external_server_id": "acme_tools",
                "external_tool_name": tool_name,
                "result_keys": ["ok"],
            }

    server = MCPExternalServerSettings.model_validate(
        {
            "server_id": "acme_tools",
            "base_url": "https://mcp.example.com/mcp",
            "auth_type": "bearer",
            "auth_token": "token",
            "allow_tools": ["lookup_customer"],
            "read_only_tools": ["lookup_customer"],
            "required_roles": ["owner", "admin"],
        }
    )
    manager = ExternalMCPToolManager(
        external_servers=(server,),
        feature_enabled=True,
        client_factory=lambda _server: _FakeClient(),
    )
    registry = ToolRegistry(specs=build_default_tool_specs())

    summary = await manager.ensure_registered(registry=registry)

    assert summary.discovered_servers == 1
    assert summary.warnings == ()
    external_tool_name = "external_mcp.acme_tools.lookup_customer"
    assert external_tool_name in summary.registered_tools
    assert registry.get_spec(external_tool_name) is not None

    executor = AgentToolExecutor(registry=registry)
    call = ToolCall(
        run_id=str(uuid4()),
        tool_name=external_tool_name,
        organization_id=str(uuid4()),
        user_id=str(uuid4()),
        surface=ToolSurface.api,
        arguments={"customer_id": "cus_123"},
    )
    principal = AuthenticatedPrincipal(
        user_id=call.user_id,
        organization_id=call.organization_id,
        email="owner@example.com",
        roles=["owner"],
        auth_provider="app",
    )

    result = await executor.execute(session=None, call=call, principal=principal, request_id=None)

    assert result.success is True
    assert result.output is not None
    assert result.output["external_tool_name"] == "lookup_customer"
    assert captured_headers["x-rudix-organization-id"] == call.organization_id
    assert captured_headers["x-rudix-user-id"] == call.user_id
    assert captured_headers["x-rudix-run-id"] == call.run_id


async def test_external_mcp_manager_handles_discovery_schema_failure_safely() -> None:
    class _FakeFailingClient:
        async def discover(self) -> ExternalMCPDiscoverySnapshot:
            raise ExternalMCPProtocolError("tools/list shape changed")

    server = MCPExternalServerSettings.model_validate(
        {
            "server_id": "acme_tools",
            "base_url": "https://mcp.example.com/mcp",
            "auth_type": "bearer",
            "auth_token": "token",
            "allow_tools": ["lookup_customer"],
            "read_only_tools": ["lookup_customer"],
            "required_roles": ["owner", "admin"],
        }
    )
    manager = ExternalMCPToolManager(
        external_servers=(server,),
        feature_enabled=True,
        client_factory=lambda _server: _FakeFailingClient(),
    )
    registry = ToolRegistry(specs=build_default_tool_specs())

    summary = await manager.ensure_registered(registry=registry)

    assert summary.discovered_servers == 0
    assert summary.registered_tools == ()
    assert len(summary.warnings) == 1
    assert registry.get_spec("external_mcp.acme_tools.lookup_customer") is None


async def test_external_mcp_tool_preserves_org_authorization_boundary() -> None:
    class _FakeClient:
        async def discover(self) -> ExternalMCPDiscoverySnapshot:
            return ExternalMCPDiscoverySnapshot(
                server_id="acme_tools",
                tools=(
                    ExternalMCPDiscoveredTool(
                        name="lookup_customer",
                        description="Fetch customer profile.",
                        input_schema={},
                    ),
                ),
                resources=(),
            )

        async def call_tool(
            self,
            *,
            tool_name: str,
            arguments: dict[str, Any],
            context_headers: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            del tool_name, arguments, context_headers
            return {"ok": True}

    server = MCPExternalServerSettings.model_validate(
        {
            "server_id": "acme_tools",
            "base_url": "https://mcp.example.com/mcp",
            "auth_type": "bearer",
            "auth_token": "token",
            "allow_tools": ["lookup_customer"],
            "read_only_tools": ["lookup_customer"],
            "required_roles": ["owner", "admin"],
        }
    )
    manager = ExternalMCPToolManager(
        external_servers=(server,),
        feature_enabled=True,
        client_factory=lambda _server: _FakeClient(),
    )
    registry = ToolRegistry(specs=build_default_tool_specs())
    await manager.ensure_registered(registry=registry)

    external_tool_name = "external_mcp.acme_tools.lookup_customer"
    executor = AgentToolExecutor(registry=registry)
    call = ToolCall(
        run_id=str(uuid4()),
        tool_name=external_tool_name,
        organization_id=str(uuid4()),
        user_id=str(uuid4()),
        surface=ToolSurface.api,
        arguments={"customer_id": "cus_123"},
    )
    principal = AuthenticatedPrincipal(
        user_id=call.user_id,
        organization_id=str(uuid4()),
        email="owner@example.com",
        roles=["owner"],
        auth_provider="app",
    )

    result = await executor.execute(session=None, call=call, principal=principal, request_id=None)

    assert result.success is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.authorization_failed
