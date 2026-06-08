import { apiRequest } from "@/lib/api/request";

export const VALID_SCOPES = [
  "documents:read",
  "documents:write",
  "chat:write",
  "evaluations:run",
  "webhooks:manage",
  "connectors:manage",
] as const;

export type ApiKeyScope = (typeof VALID_SCOPES)[number];

export type ApiKey = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  key_prefix: string;
  scopes: string[];
  status: "active" | "revoked";
  expires_at: string | null;
  last_used_at: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ApiKeyCreated = ApiKey & {
  raw_key: string;
};

export type ApiKeyListResponse = {
  items: ApiKey[];
  total: number;
};

export type CreateApiKeyRequest = {
  name: string;
  description?: string | null;
  scopes: string[];
  expires_at?: string | null;
};

export type UpdateApiKeyRequest = {
  name?: string | null;
  description?: string | null;
};

function normalizeApiKey(value: unknown): ApiKey {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    name: typeof raw.name === "string" ? raw.name : "",
    description: typeof raw.description === "string" ? raw.description : null,
    key_prefix: typeof raw.key_prefix === "string" ? raw.key_prefix : "",
    scopes: Array.isArray(raw.scopes)
      ? (raw.scopes as unknown[]).filter(
          (s): s is string => typeof s === "string",
        )
      : [],
    status: raw.status === "revoked" ? "revoked" : "active",
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : null,
    last_used_at:
      typeof raw.last_used_at === "string" ? raw.last_used_at : null,
    created_by_id:
      typeof raw.created_by_id === "string" ? raw.created_by_id : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

function normalizeApiKeyCreated(value: unknown): ApiKeyCreated {
  const base = normalizeApiKey(value);
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    ...base,
    raw_key: typeof raw.raw_key === "string" ? raw.raw_key : "",
  };
}

export async function listApiKeys(): Promise<ApiKeyListResponse> {
  const payload = await apiRequest<unknown>("/admin/api-keys", {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items) ? raw.items.map(normalizeApiKey) : [];
  return {
    items,
    total: typeof raw.total === "number" ? raw.total : items.length,
  };
}

export async function getApiKey(keyId: string): Promise<ApiKey> {
  const payload = await apiRequest<unknown>(
    `/admin/api-keys/${encodeURIComponent(keyId)}`,
    { method: "GET", retry: false },
  );
  return normalizeApiKey(payload);
}

export async function createApiKey(
  request: CreateApiKeyRequest,
): Promise<ApiKeyCreated> {
  const payload = await apiRequest<unknown>("/admin/api-keys", {
    method: "POST",
    json: {
      name: request.name,
      description: request.description ?? null,
      scopes: request.scopes,
      expires_at: request.expires_at ?? null,
    },
    retry: false,
  });
  return normalizeApiKeyCreated(payload);
}

export async function updateApiKey(
  keyId: string,
  request: UpdateApiKeyRequest,
): Promise<ApiKey> {
  const payload = await apiRequest<unknown>(
    `/admin/api-keys/${encodeURIComponent(keyId)}`,
    { method: "PATCH", json: request, retry: false },
  );
  return normalizeApiKey(payload);
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await apiRequest<unknown>(`/admin/api-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
    retry: false,
  });
}

export async function rotateApiKey(keyId: string): Promise<ApiKeyCreated> {
  const payload = await apiRequest<unknown>(
    `/admin/api-keys/${encodeURIComponent(keyId)}/rotate`,
    { method: "POST", retry: false },
  );
  return normalizeApiKeyCreated(payload);
}
