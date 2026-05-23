from __future__ import annotations

from uuid import uuid4

from starlette.requests import Request

from app.auth.errors import AuthenticationError
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.core.config import Environment, MCPTransport, settings
from app.db.session import SessionLocal


def _build_request_from_headers(headers: dict[str, str]) -> Request:
    raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": settings.mcp_http_path,
        "raw_path": settings.mcp_http_path.encode("latin-1"),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("0.0.0.0", 0),
        "server": (settings.mcp_http_host, settings.mcp_http_port),
    }
    return Request(scope=scope)


def _principal_from_dev_settings() -> AuthenticatedPrincipal:
    if settings.mcp_dev_principal_user_id is None:
        raise AuthenticationError("MCP dev principal user id is not configured")
    if settings.mcp_dev_principal_organization_id is None:
        raise AuthenticationError("MCP dev principal organization id is not configured")
    if not settings.mcp_dev_principal_roles:
        raise AuthenticationError("MCP dev principal roles are not configured")

    return AuthenticatedPrincipal(
        user_id=settings.mcp_dev_principal_user_id,
        organization_id=settings.mcp_dev_principal_organization_id,
        email=None,
        roles=list(settings.mcp_dev_principal_roles),
        auth_provider="mcp_dev",
    )


async def resolve_mcp_principal(headers: dict[str, str] | None = None) -> AuthenticatedPrincipal:
    normalized_headers = {key.lower(): value for key, value in (headers or {}).items()}
    if settings.mcp_transport == MCPTransport.stdio:
        return _principal_from_dev_settings()

    if not settings.mcp_require_bearer_auth and "authorization" not in normalized_headers:
        if settings.environment in {Environment.production, Environment.staging}:
            raise AuthenticationError("Bearer token is required for MCP in non-development environments")
        return _principal_from_dev_settings()

    if "authorization" not in normalized_headers:
        raise AuthenticationError("Missing bearer token")

    request = _build_request_from_headers(normalized_headers)
    request.state.request_id = str(uuid4())
    async with SessionLocal() as session:
        provider = get_auth_provider()
        principal = await provider.authenticate(request, session)
    return principal
