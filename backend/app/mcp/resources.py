from __future__ import annotations

from app.mcp.resource_registry import register_mcp_resources
from app.mcp.resource_runtime import MCPResourceRuntime

__all__ = [
    "MCPResourceRuntime",
    "register_mcp_resources",
]
