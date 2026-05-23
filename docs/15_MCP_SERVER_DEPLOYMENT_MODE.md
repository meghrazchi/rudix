# 15. Standalone MCP Server Deployment Mode

## Objective

Expose Rudix capabilities to MCP clients through a standalone server package without coupling MCP transport to the REST chat API runtime.

## Design Summary

MCP is implemented as a separate module:

- `backend/app/mcp/dependencies.py`
- `backend/app/mcp/auth.py`
- `backend/app/mcp/server.py`
- `backend/app/mcp/main.py`

MCP uses the same shared internal tool contracts as the agent/API runtime:

- `ToolSpec`
- `ToolCall`
- `ToolResult`
- `ToolRegistry`
- `AgentToolExecutor`

This avoids duplicated business logic while keeping transport boundaries separate.

## Transport Modes

Supported modes:

- `streamable_http` for network deployment
- `stdio` for local development/testing

`stdio` is blocked in `staging` and `production`.

## Disabled-by-Default Behavior

MCP is feature-gated:

- `FEATURE_ENABLE_MCP=false` by default

If disabled, MCP startup exits safely and readiness reports the feature gate as not enabled.

## Tool Surface Policy

Default MCP exposure is read-only only:

- `search_documents`
- `get_document_detail`
- `list_document_chunks`
- `answer_from_context`
- `summarize_document`
- `compare_documents`

Side-effect tools remain API-only unless explicitly allowed later.

## Authentication and Organization Isolation

HTTP mode:

- uses bearer token auth from existing auth providers
- requires organization context via authenticated principal
- enforces org-scoped execution through shared tool authorization

Development fallback:

- optional dev principal fallback when `MCP_REQUIRE_BEARER_AUTH=false`
- configured by:
  - `MCP_DEV_PRINCIPAL_USER_ID`
  - `MCP_DEV_PRINCIPAL_ORGANIZATION_ID`
  - `MCP_DEV_PRINCIPAL_ROLES`
- disabled for staging/production deployments

## Capability Mapping (Least Privilege)

MCP tools enforce both role authorization and capability authorization.

Role-to-capability mapping is configurable:

- `MCP_CAPABILITIES_OWNER`
- `MCP_CAPABILITIES_ADMIN`
- `MCP_CAPABILITIES_MEMBER`
- `MCP_CAPABILITIES_VIEWER`

Default behavior keeps MCP read-focused. Viewer role excludes `chat.answer` by default.

## MCP Rate Limits

MCP calls are rate-limited per organization, user, tool, and time window.

Relevant settings:

- `MCP_RATE_LIMIT_ENABLED`
- `MCP_RATE_LIMIT_WINDOW_SECONDS`
- `MCP_RATE_LIMIT_REQUESTS`

Redis failure behavior follows the shared rate-limit mode (`RATE_LIMIT_REDIS_FAILURE_MODE`).

## Safety and Redaction

MCP execution returns structured `ToolResult` payloads with safe errors:

- validation/auth/tool-availability failures are surfaced without secret leakage
- raw tokens, raw protected document text, and sensitive keys remain redacted by shared policy

## Runtime Endpoints (HTTP mode)

- `GET /health`
- `GET /ready`
- MCP protocol endpoint at `MCP_HTTP_PATH` (default `/mcp`)

Default local URL:

- `http://localhost:8010`

## Configuration

Key environment variables:

- `FEATURE_ENABLE_MCP`
- `MCP_SERVER_NAME`
- `MCP_TRANSPORT`
- `MCP_HTTP_HOST`
- `MCP_HTTP_PORT`
- `MCP_HTTP_PATH`
- `MCP_REQUIRE_BEARER_AUTH`
- `MCP_DEV_PRINCIPAL_USER_ID`
- `MCP_DEV_PRINCIPAL_ORGANIZATION_ID`
- `MCP_DEV_PRINCIPAL_ROLES`

## Local Commands

From `backend/`:

```bash
make run-mcp-http
make run-mcp-stdio
```

From repository root:

```bash
make up-mcp
make logs-mcp
make down-mcp
```

`up-mcp` uses the compose `mcp` profile, so MCP service startup is explicit.

## Deployment Notes

- Staging/production compose includes an optional `mcp` service profile.
- MCP service reuses backend image and starts with `python -m app.mcp.main`.
- Readiness/health endpoints are available on the MCP port for operators.

## Protected Resource Metadata Notes (Remote Deployments)

- Keep MCP endpoints behind authenticated ingress and TLS.
- Preserve `Authorization` header and optional `x-organization-id` forwarding.
- Do not emit raw document text, bearer tokens, or secrets in proxy/access logs.
- Restrict network exposure to trusted clients and internal subnets where possible.
