from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OrgMCPPolicyResponse(BaseModel):
    organization_id: str
    enabled: bool
    read_only: bool
    allowed_tools: list[str] | None
    capabilities_owner: list[str] | None
    capabilities_admin: list[str] | None
    capabilities_member: list[str] | None
    capabilities_viewer: list[str] | None
    rate_limit_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    # F176 trust and exposure controls
    allowed_resources: list[str] | None
    allowed_prompts: list[str] | None
    allowed_collections: list[str] | None
    allowed_roles: list[str] | None
    redact_document_text: bool
    max_chunk_chars: int | None
    max_request_bytes: int | None
    max_response_bytes: int | None
    updated_by_user_id: str | None
    updated_at: datetime


class UpdateMCPPolicyRequest(BaseModel):
    enabled: bool | None = None
    read_only: bool | None = None
    allowed_tools: list[str] | None = None
    capabilities_owner: list[str] | None = None
    capabilities_admin: list[str] | None = None
    capabilities_member: list[str] | None = None
    capabilities_viewer: list[str] | None = None
    rate_limit_enabled: bool | None = None
    rate_limit_requests: int | None = Field(default=None, ge=1, le=10000)
    rate_limit_window_seconds: int | None = Field(default=None, ge=1, le=3600)
    # F176 trust and exposure controls
    allowed_resources: list[str] | None = None
    allowed_prompts: list[str] | None = None
    allowed_collections: list[str] | None = None
    allowed_roles: list[str] | None = None
    redact_document_text: bool | None = None
    max_chunk_chars: int | None = Field(default=None, ge=100)
    max_request_bytes: int | None = Field(default=None, ge=256)
    max_response_bytes: int | None = Field(default=None, ge=256)


class MCPDependencyStatus(BaseModel):
    ok: bool
    detail: str | None


class MCPStatusResponse(BaseModel):
    feature_enabled: bool
    auth_required: bool
    transport: str
    server_name: str
    rate_limit_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    http_host: str
    http_port: int
    http_path: str
    dependencies: dict[str, MCPDependencyStatus]
    failed_dependencies: list[str]


class MCPToolInfo(BaseModel):
    name: str
    public_name: str
    description: str
    capability: str
    deprecated_alias: bool


class MCPToolListResponse(BaseModel):
    items: list[MCPToolInfo]
    total: int


class MCPAuditEvent(BaseModel):
    id: str
    action: str
    user_id: str | None
    resource_type: str | None
    resource_id: str | None
    metadata: dict
    created_at: datetime


class MCPAuditEventListResponse(BaseModel):
    items: list[MCPAuditEvent]
    total: int
