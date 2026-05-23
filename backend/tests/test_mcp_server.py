import os
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure strict settings can be loaded when app imports in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
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

from app.auth.errors import AuthenticationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.agents.schemas import ToolCall, ToolErrorCode, ToolResult
from app.mcp.server import MCPToolRuntime, create_mcp_http_app


async def test_mcp_runtime_returns_safe_error_when_feature_is_disabled(
    monkeypatch,
) -> None:
    runtime = MCPToolRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", False)

    payload = await runtime.execute_tool(tool_name="search_documents", arguments={"query": "policy"})

    assert payload["success"] is False
    assert payload["tool_name"] == "search_documents"
    assert payload["error"]["code"] == ToolErrorCode.tool_unavailable.value
    assert "disabled" in payload["error"]["safe_message"].lower()


async def test_mcp_runtime_returns_safe_auth_error(
    monkeypatch,
) -> None:
    runtime = MCPToolRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)

    async def _raise_auth_failure(_: dict[str, str]) -> AuthenticatedPrincipal:
        raise AuthenticationError("bad token")

    monkeypatch.setattr("app.mcp.server.get_http_headers_from_context", lambda: {"authorization": "Bearer secret"})
    monkeypatch.setattr("app.mcp.server.resolve_mcp_principal", _raise_auth_failure)

    payload = await runtime.execute_tool(tool_name="search_documents", arguments={"query": "policy"})

    assert payload["success"] is False
    assert payload["error"]["code"] == ToolErrorCode.authorization_failed.value
    assert "authentication failed" in payload["error"]["safe_message"].lower()
    assert "secret" not in str(payload)


async def test_mcp_runtime_executes_read_only_tool_with_org_scoped_principal(
    monkeypatch,
) -> None:
    runtime = MCPToolRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)

    async def _resolve_principal(_: dict[str, str]) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id="user-123",
            organization_id="org-123",
            email="user@example.com",
            roles=["viewer"],
            auth_provider="app",
        )

    async def _fake_execute(
        *,
        session: Any,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
        request_id: str | None,
    ) -> ToolResult:
        assert session is None
        assert call.tool_name == "search_documents"
        assert call.organization_id == "org-123"
        assert principal.organization_id == "org-123"
        assert request_id is not None
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            success=True,
            output={"items": [], "total": 0},
            error=None,
            latency_ms=7,
        )

    monkeypatch.setattr("app.mcp.server.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr("app.mcp.server.resolve_mcp_principal", _resolve_principal)
    monkeypatch.setattr(runtime._executor, "execute", _fake_execute)

    payload = await runtime.execute_tool(tool_name="search_documents", arguments={"query": "policy"})

    assert payload["success"] is True
    assert payload["tool_name"] == "search_documents"
    assert payload["output"] == {"items": [], "total": 0}
    assert payload["latency_ms"] == 7


def test_mcp_http_app_exposes_health_and_ready_routes(monkeypatch) -> None:
    async def _fake_readiness_payload() -> tuple[int, dict[str, Any]]:
        return 200, {
            "status": "ok",
            "failed_dependencies": [],
            "dependencies": {},
        }

    class _StubMCPServer:
        pass

    monkeypatch.setattr("app.mcp.server.build_mcp_server", lambda: _StubMCPServer())

    def _fake_streamable_http_app(*, server: Any, path: str) -> FastAPI:
        _ = server
        app = FastAPI()

        @app.get(path)
        async def _mcp_entrypoint() -> dict[str, str]:
            return {"ok": "true"}

        return app

    monkeypatch.setattr("app.mcp.server.build_streamable_http_app", _fake_streamable_http_app)
    monkeypatch.setattr("app.mcp.server._readiness_payload", _fake_readiness_payload)

    app = create_mcp_http_app()
    client = TestClient(app)

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["service"] == "mcp"

    ready_response = client.get("/ready")
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ok"

