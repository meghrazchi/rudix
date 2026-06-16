import { apiRequest } from "@/lib/api/request";

import type { ProviderSummary } from "@/lib/api/connector-providers";

export type ConnectorConnectionSummary = {
  id: string;
  provider_key: string;
  provider: ProviderSummary;
  display_name: string;
  external_account_id: string | null;
  collection_id: string | null;
  status: string;
  auth_config: Record<string, unknown>;
  last_sync_at: string | null;
  error_message: string | null;
  source_count: number;
  indexed_document_count: number;
  sync_job_count: number;
  created_at: string;
  updated_at: string;
};

export type ConnectorDiagnostics = {
  connection_id: string;
  provider_key: string;
  status: string;
  error_message: string | null;
  auth_type: string | null;
  credential_status: string | null;
  credential_version: number | null;
  credential_fingerprint: string | null;
  scopes: string[];
  expires_at: string | null;
  metadata: Record<string, unknown>;
};

export type SourcePermissionSnapshot = {
  id: string;
  provider_source_id: string;
  name: string;
  source_type: string;
  is_enabled: boolean;
  permissions: Record<string, unknown>;
};

export type ConnectorDiscoveryItem = {
  provider_source_id: string;
  name: string;
  source_type: string;
  source_url: string | null;
  parent_provider_source_id: string | null;
  metadata: Record<string, unknown>;
  permissions: Record<string, unknown>;
};

export type ConnectorDiscoveryResponse = {
  items: ConnectorDiscoveryItem[];
  total: number;
  next_cursor: Record<string, unknown> | null;
  has_more: boolean;
};

export type ConnectorConnectionDetail = ConnectorConnectionSummary & {
  diagnostics: ConnectorDiagnostics;
  source_permission_snapshots: SourcePermissionSnapshot[];
};

export type ScopeWarning = {
  code: string;
  message: string;
  scope: string | null;
};

export type PermissionReview = {
  id: string;
  connection_id: string;
  is_confirmed: boolean;
  is_broad_scope: boolean;
  scope_warnings: ScopeWarning[];
  permission_snapshot: Record<string, unknown>;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ConnectorConnectionsListResponse = {
  items: ConnectorConnectionSummary[];
  total: number;
};

export type BeginConnectorOAuthConnectPayload = {
  provider_key: string;
  redirect_uri: string;
  requested_scopes?: string[] | null;
  collection_id?: string | null;
  connection_id?: string | null;
  display_name?: string | null;
  external_account_id?: string | null;
  client_id?: string | null;
  config?: Record<string, unknown>;
};

export type BeginConnectorOAuthConnectResponse = {
  state: string;
  authorization_url: string;
  expires_at: string;
  scopes: string[];
};

export type CreateConnectorConnectionPayload = {
  provider_key: string;
  display_name: string;
  collection_id?: string | null;
  external_account_id?: string | null;
  config?: Record<string, unknown>;
};

export async function beginConnectorOAuthConnect(
  payload: BeginConnectorOAuthConnectPayload,
): Promise<BeginConnectorOAuthConnectResponse> {
  return apiRequest<BeginConnectorOAuthConnectResponse>(
    "/connectors/oauth/connect",
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function createConnectorConnection(
  payload: CreateConnectorConnectionPayload,
): Promise<ConnectorConnectionSummary> {
  return apiRequest<ConnectorConnectionSummary>("/connectors/connections", {
    method: "POST",
    json: payload,
  });
}

export async function listConnectorConnections(): Promise<ConnectorConnectionsListResponse> {
  return apiRequest<ConnectorConnectionsListResponse>(
    "/connectors/connections",
  );
}

export async function listAvailableConnectorConnections(): Promise<ConnectorConnectionsListResponse> {
  return apiRequest<ConnectorConnectionsListResponse>("/connectors/available");
}

export async function getConnectorConnection(
  connectionId: string,
): Promise<ConnectorConnectionDetail> {
  return apiRequest<ConnectorConnectionDetail>(
    `/connectors/connections/${encodeURIComponent(connectionId)}`,
  );
}

export async function refreshConnectorCredential(
  connectionId: string,
): Promise<unknown> {
  return apiRequest<unknown>(`/connectors/${connectionId}/refresh`, {
    method: "POST",
  });
}

export async function disconnectConnector(
  connectionId: string,
): Promise<unknown> {
  return apiRequest<unknown>(`/connectors/${connectionId}/disconnect`, {
    method: "POST",
  });
}

export async function deleteConnectorConnection(
  connectionId: string,
): Promise<void> {
  return apiRequest<void>(
    `/connectors/connections/${encodeURIComponent(connectionId)}`,
    { method: "DELETE" },
  );
}

export async function getPermissionReview(
  connectionId: string,
): Promise<PermissionReview> {
  return apiRequest<PermissionReview>(
    `/connectors/${encodeURIComponent(connectionId)}/permission-review`,
  );
}

export async function confirmPermissionReview(
  connectionId: string,
): Promise<PermissionReview> {
  return apiRequest<PermissionReview>(
    `/connectors/${encodeURIComponent(connectionId)}/permission-review/confirm`,
    { method: "POST" },
  );
}

export async function discoverConnectorSources(
  connectionId: string,
  providerKey: string,
  scope: "sites" | "drives" | "libraries" | "folders",
  params?: {
    cursor?: string | null;
    siteId?: string | null;
    driveId?: string | null;
    folderId?: string | null;
    pageSize?: number;
  },
): Promise<ConnectorDiscoveryResponse> {
  const search = new URLSearchParams();
  if (params?.cursor) {
    search.set("cursor", params.cursor);
  }
  if (params?.siteId) {
    search.set("site_id", params.siteId);
  }
  if (params?.driveId) {
    search.set("drive_id", params.driveId);
  }
  if (params?.folderId) {
    search.set("folder_id", params.folderId);
  }
  if (params?.pageSize) {
    search.set("page_size", String(params.pageSize));
  }

  const query = search.toString();
  const suffix = query.length > 0 ? `?${query}` : "";
  return apiRequest<ConnectorDiscoveryResponse>(
    `/connectors/connections/${encodeURIComponent(connectionId)}/providers/${encodeURIComponent(providerKey)}/discover/${scope}${suffix}`,
  );
}
