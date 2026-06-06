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

export type ConnectorConnectionDetail = ConnectorConnectionSummary & {
  diagnostics: ConnectorDiagnostics;
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
