from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, cast

from fastapi import FastAPI


class MCPSDKUnavailableError(RuntimeError):
    """Raised when the MCP SDK is unavailable at runtime."""


def load_fastmcp_class() -> type[Any]:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - import-time guard
        raise MCPSDKUnavailableError(
            "MCP SDK is not installed. Install backend dependencies to enable MCP runtime."
        ) from exc
    return cast(type[Any], FastMCP)


def get_http_headers_from_context() -> dict[str, str]:
    """Safely return active MCP HTTP headers, or an empty mapping when unavailable."""
    try:
        module = importlib.import_module("mcp.server.fastmcp.dependencies")
    except Exception:
        return {}

    get_http_headers = getattr(module, "get_http_headers", None)
    if not callable(get_http_headers):
        return {}

    try:
        headers = get_http_headers(include_all=True)
    except TypeError:
        headers = get_http_headers()
    except Exception:
        return {}

    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key).lower()] = str(value)
    return normalized


def build_streamable_http_app(*, server: Any, path: str) -> Any:
    """
    Create an ASGI app from a FastMCP server across supported SDK variants.

    Newer SDK variants expose `http_app(path=...)`, while older ones expose
    `streamable_http_app(path=...)`.
    """
    def _mount_with_path(app: Any) -> Any:
        if path in {"", "/"}:
            return app
        wrapper = FastAPI()
        wrapper.mount(path, app)
        return wrapper

    factory: Callable[..., Any] | None = getattr(server, "http_app", None)
    if callable(factory):
        try:
            return factory(path=path)
        except TypeError:
            return _mount_with_path(factory())

    fallback_factory: Callable[..., Any] | None = getattr(server, "streamable_http_app", None)
    if callable(fallback_factory):
        try:
            return fallback_factory(path=path)
        except TypeError:
            return _mount_with_path(fallback_factory())

    raise MCPSDKUnavailableError(
        "Installed MCP SDK does not expose a Streamable HTTP app factory."
    )
