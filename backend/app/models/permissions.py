from enum import StrEnum


class PermissionType(StrEnum):
    # Documents
    documents_view = "documents:view"
    documents_upload = "documents:upload"
    documents_delete = "documents:delete"
    documents_manage = "documents:manage"

    # Collections
    collections_view = "collections:view"
    collections_create = "collections:create"
    collections_manage = "collections:manage"
    collections_delete = "collections:delete"

    # Chat
    chat_use = "chat:use"
    chat_use_collections = "chat:use_collections"
    chat_manage_sessions = "chat:manage_sessions"

    # Evaluations
    evaluations_view = "evaluations:view"
    evaluations_create = "evaluations:create"
    evaluations_run = "evaluations:run"
    evaluations_manage = "evaluations:manage"

    # Audit logs
    audit_logs_view = "audit_logs:view"
    audit_logs_export = "audit_logs:export"

    # Security center
    security_center_view = "security_center:view"
    security_center_configure = "security_center:configure"

    # Billing
    billing_view = "billing:view"
    billing_manage = "billing:manage"

    # API keys
    api_keys_list = "api_keys:list"
    api_keys_create = "api_keys:create"
    api_keys_revoke = "api_keys:revoke"

    # Webhooks
    webhooks_list = "webhooks:list"
    webhooks_create = "webhooks:create"
    webhooks_delete = "webhooks:delete"

    # Agents
    agents_use = "agents:use"
    agents_create = "agents:create"
    agents_manage = "agents:manage"

    # MCP
    mcp_use = "mcp:use"
    mcp_manage = "mcp:manage"

    # Roles (admin-only)
    roles_view = "roles:view"
    roles_manage = "roles:manage"

    # Team
    team_view = "team:view"
    team_manage = "team:manage"


PERMISSION_CATALOG: list[dict[str, str]] = [
    # Documents
    {"permission": PermissionType.documents_view, "category": "documents", "description": "View documents in the knowledge base"},
    {"permission": PermissionType.documents_upload, "category": "documents", "description": "Upload new documents"},
    {"permission": PermissionType.documents_delete, "category": "documents", "description": "Delete documents"},
    {"permission": PermissionType.documents_manage, "category": "documents", "description": "Manage document settings, chunking, and lifecycle"},
    # Collections
    {"permission": PermissionType.collections_view, "category": "collections", "description": "View knowledge base collections"},
    {"permission": PermissionType.collections_create, "category": "collections", "description": "Create new collections"},
    {"permission": PermissionType.collections_manage, "category": "collections", "description": "Update collection settings and membership"},
    {"permission": PermissionType.collections_delete, "category": "collections", "description": "Delete collections"},
    # Chat
    {"permission": PermissionType.chat_use, "category": "chat", "description": "Start and participate in chat sessions"},
    {"permission": PermissionType.chat_use_collections, "category": "chat", "description": "Scope chat to specific collections"},
    {"permission": PermissionType.chat_manage_sessions, "category": "chat", "description": "Rename, delete, and share chat sessions"},
    # Evaluations
    {"permission": PermissionType.evaluations_view, "category": "evaluations", "description": "View evaluation datasets and results"},
    {"permission": PermissionType.evaluations_create, "category": "evaluations", "description": "Create evaluation datasets"},
    {"permission": PermissionType.evaluations_run, "category": "evaluations", "description": "Run evaluations against datasets"},
    {"permission": PermissionType.evaluations_manage, "category": "evaluations", "description": "Manage quality gates and evaluation settings"},
    # Audit logs
    {"permission": PermissionType.audit_logs_view, "category": "audit_logs", "description": "View organization audit logs"},
    {"permission": PermissionType.audit_logs_export, "category": "audit_logs", "description": "Export audit logs"},
    # Security center
    {"permission": PermissionType.security_center_view, "category": "security_center", "description": "View security settings and reports"},
    {"permission": PermissionType.security_center_configure, "category": "security_center", "description": "Configure security policies and SSO/SCIM"},
    # Billing
    {"permission": PermissionType.billing_view, "category": "billing", "description": "View billing information and invoices"},
    {"permission": PermissionType.billing_manage, "category": "billing", "description": "Manage billing plan and payment methods"},
    # API keys
    {"permission": PermissionType.api_keys_list, "category": "api_keys", "description": "List API keys"},
    {"permission": PermissionType.api_keys_create, "category": "api_keys", "description": "Create API keys"},
    {"permission": PermissionType.api_keys_revoke, "category": "api_keys", "description": "Revoke API keys"},
    # Webhooks
    {"permission": PermissionType.webhooks_list, "category": "webhooks", "description": "List webhooks"},
    {"permission": PermissionType.webhooks_create, "category": "webhooks", "description": "Create webhooks"},
    {"permission": PermissionType.webhooks_delete, "category": "webhooks", "description": "Delete webhooks"},
    # Agents
    {"permission": PermissionType.agents_use, "category": "agents", "description": "Run agent tasks"},
    {"permission": PermissionType.agents_create, "category": "agents", "description": "Create and configure agents"},
    {"permission": PermissionType.agents_manage, "category": "agents", "description": "Manage agent settings and approvals"},
    # MCP
    {"permission": PermissionType.mcp_use, "category": "mcp", "description": "Use MCP server tools"},
    {"permission": PermissionType.mcp_manage, "category": "mcp", "description": "Configure MCP server policies"},
    # Roles
    {"permission": PermissionType.roles_view, "category": "roles", "description": "View role definitions and assignments"},
    {"permission": PermissionType.roles_manage, "category": "roles", "description": "Create, edit, and delete custom roles"},
    # Team
    {"permission": PermissionType.team_view, "category": "team", "description": "View team members"},
    {"permission": PermissionType.team_manage, "category": "team", "description": "Invite, remove, and change team member roles"},
]


# Canonical permission sets for each built-in role (ordered least → most privileged).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({
        PermissionType.documents_view,
        PermissionType.collections_view,
        PermissionType.chat_use,
        PermissionType.evaluations_view,
        PermissionType.agents_use,
        PermissionType.mcp_use,
    }),
    "reviewer": frozenset({
        PermissionType.documents_view,
        PermissionType.collections_view,
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
        PermissionType.evaluations_view,
        PermissionType.evaluations_create,
        PermissionType.evaluations_run,
        PermissionType.audit_logs_view,
        PermissionType.agents_use,
        PermissionType.mcp_use,
    }),
    "developer": frozenset({
        PermissionType.documents_view,
        PermissionType.documents_upload,
        PermissionType.collections_view,
        PermissionType.collections_create,
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
        PermissionType.evaluations_view,
        PermissionType.evaluations_create,
        PermissionType.evaluations_run,
        PermissionType.api_keys_list,
        PermissionType.api_keys_create,
        PermissionType.api_keys_revoke,
        PermissionType.webhooks_list,
        PermissionType.webhooks_create,
        PermissionType.webhooks_delete,
        PermissionType.agents_use,
        PermissionType.agents_create,
        PermissionType.mcp_use,
        PermissionType.audit_logs_view,
    }),
    "member": frozenset({
        PermissionType.documents_view,
        PermissionType.documents_upload,
        PermissionType.collections_view,
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
        PermissionType.evaluations_view,
        PermissionType.agents_use,
        PermissionType.mcp_use,
    }),
    "billing_admin": frozenset({
        PermissionType.billing_view,
        PermissionType.billing_manage,
        PermissionType.audit_logs_view,
        PermissionType.team_view,
    }),
    "security_admin": frozenset({
        PermissionType.security_center_view,
        PermissionType.security_center_configure,
        PermissionType.audit_logs_view,
        PermissionType.audit_logs_export,
        PermissionType.team_view,
    }),
    "admin": frozenset({
        PermissionType.documents_view,
        PermissionType.documents_upload,
        PermissionType.documents_delete,
        PermissionType.documents_manage,
        PermissionType.collections_view,
        PermissionType.collections_create,
        PermissionType.collections_manage,
        PermissionType.collections_delete,
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
        PermissionType.evaluations_view,
        PermissionType.evaluations_create,
        PermissionType.evaluations_run,
        PermissionType.evaluations_manage,
        PermissionType.audit_logs_view,
        PermissionType.audit_logs_export,
        PermissionType.security_center_view,
        PermissionType.security_center_configure,
        PermissionType.api_keys_list,
        PermissionType.api_keys_create,
        PermissionType.api_keys_revoke,
        PermissionType.webhooks_list,
        PermissionType.webhooks_create,
        PermissionType.webhooks_delete,
        PermissionType.agents_use,
        PermissionType.agents_create,
        PermissionType.agents_manage,
        PermissionType.mcp_use,
        PermissionType.mcp_manage,
        PermissionType.roles_view,
        PermissionType.roles_manage,
        PermissionType.team_view,
        PermissionType.team_manage,
    }),
    "owner": frozenset({
        PermissionType.documents_view,
        PermissionType.documents_upload,
        PermissionType.documents_delete,
        PermissionType.documents_manage,
        PermissionType.collections_view,
        PermissionType.collections_create,
        PermissionType.collections_manage,
        PermissionType.collections_delete,
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
        PermissionType.evaluations_view,
        PermissionType.evaluations_create,
        PermissionType.evaluations_run,
        PermissionType.evaluations_manage,
        PermissionType.audit_logs_view,
        PermissionType.audit_logs_export,
        PermissionType.security_center_view,
        PermissionType.security_center_configure,
        PermissionType.billing_view,
        PermissionType.billing_manage,
        PermissionType.api_keys_list,
        PermissionType.api_keys_create,
        PermissionType.api_keys_revoke,
        PermissionType.webhooks_list,
        PermissionType.webhooks_create,
        PermissionType.webhooks_delete,
        PermissionType.agents_use,
        PermissionType.agents_create,
        PermissionType.agents_manage,
        PermissionType.mcp_use,
        PermissionType.mcp_manage,
        PermissionType.roles_view,
        PermissionType.roles_manage,
        PermissionType.team_view,
        PermissionType.team_manage,
    }),
}
