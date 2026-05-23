from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import MCPExternalAuthType, MCPExternalServerSettings

from .types import (
    ExternalMCPClientError,
    ExternalMCPDiscoveredTool,
    ExternalMCPDiscoverySnapshot,
    ExternalMCPProtocolError,
    ExternalMCPRemoteError,
)

_MCP_SESSION_HEADER = "mcp-session-id"
_MAX_CONTENT_ITEMS = 8


class ExternalMCPHTTPClient:
    def __init__(self, *, server: MCPExternalServerSettings) -> None:
        self._server = server
        self._session_id: str | None = None
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    @property
    def server_id(self) -> str:
        return self._server.server_id

    async def discover(self) -> ExternalMCPDiscoverySnapshot:
        await self._ensure_initialized()
        tools_result = await self._rpc_call("tools/list", params={}, require_session=True)
        tools = self._parse_tools_result(tools_result)
        resources: tuple[str, ...] = ()
        warning: str | None = None
        try:
            resources_result = await self._rpc_call(
                "resources/list", params={}, require_session=True
            )
            resources = self._parse_resources_result(resources_result)
        except ExternalMCPRemoteError as exc:
            warning = str(exc)
        except ExternalMCPProtocolError as exc:
            warning = str(exc)
        return ExternalMCPDiscoverySnapshot(
            server_id=self._server.server_id,
            tools=tools,
            resources=resources,
            warning=warning,
        )

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        context_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_initialized()
        result = await self._rpc_call(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            require_session=True,
            context_headers=context_headers,
        )
        return self._compact_tool_result(tool_name=tool_name, result=result)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await self._rpc_call(
                "initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "rudix-external-mcp", "version": "0.1.0"},
                },
                require_session=False,
            )
            self._initialized = True

    def _timeout(self) -> httpx.Timeout:
        timeout_seconds = self._server.timeout_seconds
        return httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )

    def _auth_headers(self) -> dict[str, str]:
        if self._server.auth_type == MCPExternalAuthType.none:
            return {}
        if self._server.auth_type == MCPExternalAuthType.bearer:
            if self._server.auth_token is None:
                raise ExternalMCPClientError("auth_token is required for bearer auth")
            return {"authorization": f"Bearer {self._server.auth_token.get_secret_value()}"}
        if self._server.auth_type == MCPExternalAuthType.header:
            if self._server.auth_header_name is None or self._server.auth_header_value is None:
                raise ExternalMCPClientError(
                    "auth_header_name and auth_header_value are required for header auth"
                )
            return {
                self._server.auth_header_name: self._server.auth_header_value.get_secret_value()
            }
        raise ExternalMCPClientError("Unsupported external MCP auth_type")

    async def _rpc_call(
        self,
        method: str,
        *,
        params: dict[str, Any],
        require_session: bool,
        context_headers: dict[str, str] | None = None,
    ) -> Any:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **self._auth_headers(),
        }
        if self._session_id and require_session:
            headers[_MCP_SESSION_HEADER] = self._session_id
        if context_headers:
            headers.update(context_headers)

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.post(
                    str(self._server.base_url), json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise ExternalMCPClientError(
                f"Unable to reach external MCP server '{self._server.server_id}'."
            ) from exc

        session_id = response.headers.get(_MCP_SESSION_HEADER)
        if session_id:
            self._session_id = session_id

        if response.status_code >= 400:
            raise ExternalMCPClientError(
                f"External MCP server '{self._server.server_id}' returned HTTP {response.status_code}."
            )

        try:
            payload_json = response.json()
        except ValueError as exc:
            raise ExternalMCPProtocolError(
                f"External MCP server '{self._server.server_id}' returned non-JSON payload."
            ) from exc
        if not isinstance(payload_json, dict):
            raise ExternalMCPProtocolError(
                f"External MCP server '{self._server.server_id}' returned invalid JSON-RPC payload."
            )

        if "error" in payload_json:
            error_payload = payload_json.get("error")
            if isinstance(error_payload, dict):
                code = error_payload.get("code")
                message = error_payload.get("message")
                safe_message = (
                    str(message)
                    if isinstance(message, str) and message.strip()
                    else "External MCP server returned an RPC error."
                )
                raise ExternalMCPRemoteError(
                    f"{safe_message} (server={self._server.server_id}, code={code})"
                )
            raise ExternalMCPRemoteError(
                f"External MCP server '{self._server.server_id}' returned an RPC error."
            )

        if "result" not in payload_json:
            raise ExternalMCPProtocolError(
                f"External MCP server '{self._server.server_id}' returned payload without result."
            )
        return payload_json["result"]

    def _parse_tools_result(self, result: Any) -> tuple[ExternalMCPDiscoveredTool, ...]:
        if not isinstance(result, dict):
            raise ExternalMCPProtocolError(
                f"External MCP tools/list result is invalid for server '{self._server.server_id}'."
            )
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise ExternalMCPProtocolError(
                f"External MCP tools/list payload is missing tools[] for '{self._server.server_id}'."
            )

        tools: list[ExternalMCPDiscoveredTool] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            description = item.get("description")
            normalized_description = (
                description.strip()
                if isinstance(description, str) and description.strip()
                else "External MCP tool."
            )
            raw_input_schema = item.get("inputSchema")
            input_schema = raw_input_schema if isinstance(raw_input_schema, dict) else {}
            tools.append(
                ExternalMCPDiscoveredTool(
                    name=raw_name.strip(),
                    description=normalized_description,
                    input_schema=input_schema,
                )
            )
        if not tools:
            raise ExternalMCPProtocolError(
                f"External MCP tools/list returned no usable tools for '{self._server.server_id}'."
            )
        return tuple(sorted(tools, key=lambda entry: entry.name))

    def _parse_resources_result(self, result: Any) -> tuple[str, ...]:
        if not isinstance(result, dict):
            raise ExternalMCPProtocolError(
                f"External MCP resources/list result is invalid for server '{self._server.server_id}'."
            )
        raw_resources = result.get("resources")
        if not isinstance(raw_resources, list):
            raise ExternalMCPProtocolError(
                f"External MCP resources/list payload is missing resources[] for '{self._server.server_id}'."
            )

        resources: list[str] = []
        for resource in raw_resources:
            if not isinstance(resource, dict):
                continue
            raw_uri = resource.get("uri")
            if isinstance(raw_uri, str) and raw_uri.strip() and raw_uri not in resources:
                resources.append(raw_uri.strip())
        return tuple(resources)

    def _compact_tool_result(self, *, tool_name: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ExternalMCPProtocolError(
                f"External MCP tools/call result is invalid for '{self._server.server_id}:{tool_name}'."
            )

        if bool(result.get("isError")):
            raise ExternalMCPRemoteError(
                f"External MCP tool '{tool_name}' reported an error on server '{self._server.server_id}'."
            )

        compact_result: dict[str, Any] = {
            "external_server_id": self._server.server_id,
            "external_tool_name": tool_name,
            "result_keys": sorted(str(key) for key in result.keys()),
        }

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            compact_result["structured_payload"] = structured

        content_items = result.get("content")
        compact_items: list[dict[str, Any]] = []
        if isinstance(content_items, list):
            for item in content_items[:_MAX_CONTENT_ITEMS]:
                if not isinstance(item, dict):
                    continue
                compact_item: dict[str, Any] = {}
                raw_type = item.get("type")
                if isinstance(raw_type, str) and raw_type.strip():
                    compact_item["type"] = raw_type.strip()
                if isinstance(item.get("text"), str):
                    compact_item["has_text"] = True
                    compact_item["text_char_count"] = len(item["text"])
                if isinstance(item.get("mimeType"), str):
                    compact_item["mime_type"] = item["mimeType"]
                if compact_item:
                    compact_items.append(compact_item)
        if compact_items:
            compact_result["content_items"] = compact_items

        return compact_result
