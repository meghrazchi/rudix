import os
from typing import Any

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

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.mcp.prompts import MCPPromptRuntime, register_mcp_prompts


def _principal(
    *, roles: list[str], organization_id: str | None = "org-123"
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-123",
        organization_id=organization_id,
        email="user@example.com",
        roles=roles,
        auth_provider="app",
    )


async def _noop_rate_limit(*, principal: AuthenticatedPrincipal, tool_name: str) -> None:
    _ = (principal, tool_name)


async def _resolve_viewer(_: dict[str, str]) -> AuthenticatedPrincipal:
    return _principal(roles=["viewer"])


async def _resolve_viewer_no_org(_: dict[str, str]) -> AuthenticatedPrincipal:
    return _principal(roles=["viewer"], organization_id=None)


def test_register_mcp_prompts_templates() -> None:
    registered_prompt_names: list[str] = []

    class _StubServer:
        def prompt(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            if "name" in kwargs:
                registered_prompt_names.append(str(kwargs["name"]))
            elif args:
                registered_prompt_names.append(str(args[0]))
            else:
                raise AssertionError("prompt registration missing name")

            def _decorator(handler: Any) -> Any:
                return handler

            return _decorator

    register_mcp_prompts(_StubServer(), runtime=MCPPromptRuntime())

    assert "grounded_qa" in registered_prompt_names
    assert "summarize_workflow" in registered_prompt_names
    assert "compare_workflow" in registered_prompt_names
    assert "obligations_action_items" in registered_prompt_names
    assert "evidence_lookup" in registered_prompt_names


async def test_mcp_prompt_runtime_success(monkeypatch) -> None:
    runtime = MCPPromptRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.prompts.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr("app.mcp.prompts.resolve_mcp_principal", _resolve_viewer)
    monkeypatch.setattr("app.mcp.prompts.enforce_mcp_rate_limit", _noop_rate_limit)

    prompt = await runtime.build_prompt(
        prompt_name="grounded_qa",
        arguments={"query": "What changed?", "document_ids": ["doc-1"]},
    )

    assert "What changed?" in prompt
    assert "doc-1" in prompt
    assert "`ask_documents`" in prompt


async def test_mcp_prompt_runtime_validation_failure(monkeypatch) -> None:
    runtime = MCPPromptRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.prompts.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr("app.mcp.prompts.resolve_mcp_principal", _resolve_viewer)
    monkeypatch.setattr("app.mcp.prompts.enforce_mcp_rate_limit", _noop_rate_limit)

    try:
        await runtime.build_prompt(
            prompt_name="grounded_qa",
            arguments={"document_ids": ["doc-1"]},
        )
    except ValueError as exc:
        assert "validation" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected validation failure for missing query argument")


async def test_mcp_prompt_runtime_capability_denied(monkeypatch) -> None:
    runtime = MCPPromptRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr(settings, "mcp_capabilities_viewer", ["documents.read"])
    monkeypatch.setattr("app.mcp.prompts.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr("app.mcp.prompts.resolve_mcp_principal", _resolve_viewer)
    monkeypatch.setattr("app.mcp.prompts.enforce_mcp_rate_limit", _noop_rate_limit)

    try:
        await runtime.build_prompt(
            prompt_name="obligations_action_items",
            arguments={"document_ids": ["doc-1"]},
        )
    except AuthorizationError as exc:
        assert "capability" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected authorization failure for denied capability")


async def test_mcp_prompt_runtime_safe_auth_error(monkeypatch) -> None:
    runtime = MCPPromptRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.prompts.get_http_headers_from_context", lambda: {})

    async def _raise_auth(_: dict[str, str]) -> AuthenticatedPrincipal:
        raise AuthenticationError("token=super-secret")

    monkeypatch.setattr("app.mcp.prompts.resolve_mcp_principal", _raise_auth)

    try:
        await runtime.build_prompt(
            prompt_name="grounded_qa",
            arguments={"query": "hello"},
        )
    except AuthenticationError as exc:
        message = str(exc)
        assert "authentication failed" in message.lower()
        assert "super-secret" not in message
    else:  # pragma: no cover
        raise AssertionError("Expected authentication error")


async def test_mcp_prompt_runtime_requires_organization_context(monkeypatch) -> None:
    runtime = MCPPromptRuntime()
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.prompts.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr("app.mcp.prompts.resolve_mcp_principal", _resolve_viewer_no_org)
    monkeypatch.setattr("app.mcp.prompts.enforce_mcp_rate_limit", _noop_rate_limit)

    try:
        await runtime.build_prompt(
            prompt_name="grounded_qa",
            arguments={"query": "hello"},
        )
    except AuthorizationError as exc:
        assert "organization context" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected organization context authorization error")
