from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ExternalMCPClientError(RuntimeError):
    """Base error for external MCP client failures."""


class ExternalMCPProtocolError(ExternalMCPClientError):
    """Raised for malformed or unsupported external MCP protocol payloads."""


class ExternalMCPRemoteError(ExternalMCPClientError):
    """Raised when an external MCP server responds with an RPC error."""


@dataclass(frozen=True)
class ExternalMCPDiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ExternalMCPDiscoverySnapshot:
    server_id: str
    tools: tuple[ExternalMCPDiscoveredTool, ...]
    resources: tuple[str, ...]
    warning: str | None = None
