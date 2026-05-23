from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.core.config import Environment, MCPTransport, settings
from app.core.logging import configure_logging, get_logger
from app.mcp.server import run_stdio_server, run_streamable_http_server

_logger = get_logger("mcp.main")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp.main",
        description="Run Rudix MCP server in streamable HTTP or stdio mode.",
    )
    parser.add_argument(
        "--transport",
        choices=[transport.value for transport in MCPTransport],
        default=None,
        help="Override configured MCP transport for this process.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_transport(raw_transport: str | None) -> MCPTransport:
    if raw_transport is None:
        return settings.mcp_transport
    return MCPTransport(raw_transport)


def _validate_transport_override(transport: MCPTransport) -> bool:
    if transport == MCPTransport.stdio and settings.environment in {
        Environment.production,
        Environment.staging,
    }:
        _logger.error(
            "mcp.startup.invalid_transport",
            environment=settings.environment.value,
            transport=transport.value,
            detail="stdio transport is only allowed in development or test environments",
        )
        return False
    if transport == MCPTransport.stdio:
        if settings.mcp_dev_principal_user_id is None:
            _logger.error(
                "mcp.startup.missing_dev_principal_user",
                detail="mcp_dev_principal_user_id is required for stdio mode",
            )
            return False
        if settings.mcp_dev_principal_organization_id is None:
            _logger.error(
                "mcp.startup.missing_dev_principal_org",
                detail="mcp_dev_principal_organization_id is required for stdio mode",
            )
            return False
        if not settings.mcp_dev_principal_roles:
            _logger.error(
                "mcp.startup.missing_dev_principal_roles",
                detail="mcp_dev_principal_roles is required for stdio mode",
            )
            return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging(
        settings.log_level,
        environment=settings.environment.value,
        log_format=settings.log_format.value,
    )
    args = _parse_args(argv)
    transport = _resolve_transport(args.transport)

    if not settings.feature_enable_mcp:
        _logger.error(
            "mcp.startup.disabled",
            detail="MCP runtime is disabled. Set FEATURE_ENABLE_MCP=true to enable.",
        )
        return 2

    if not _validate_transport_override(transport):
        return 2

    _logger.info(
        "mcp.startup",
        transport=transport.value,
        server_name=settings.mcp_server_name,
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        path=settings.mcp_http_path,
        auth_required=settings.mcp_require_bearer_auth,
    )

    if transport == MCPTransport.stdio:
        run_stdio_server()
        return 0

    run_streamable_http_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

