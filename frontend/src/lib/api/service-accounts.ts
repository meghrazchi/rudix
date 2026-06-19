import { apiRequest } from "@/lib/api/request";

export const VALID_SCOPES = [
  "documents:read",
  "documents:write",
  "chat:write",
  "evaluations:run",
  "webhooks:manage",
  "connectors:manage",
] as const;

export type ServiceAccountScope = (typeof VALID_SCOPES)[number];

export const VALID_ENVIRONMENTS = [
  "production",
  "staging",
  "ci",
  "development",
] as const;

export type ServiceAccountEnvironment = (typeof VALID_ENVIRONMENTS)[number];

export type ServiceAccount = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  environment: ServiceAccountEnvironment;
  scopes: string[];
  is_active: boolean;
  last_used_at: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ServiceAccountListResponse = {
  items: ServiceAccount[];
  total: number;
};

export type CreateServiceAccountRequest = {
  name: string;
  description?: string | null;
  environment?: ServiceAccountEnvironment;
  scopes: string[];
};

export type UpdateServiceAccountRequest = {
  name?: string | null;
  description?: string | null;
  environment?: ServiceAccountEnvironment | null;
};

export type ServiceAccountToken = {
  id: string;
  service_account_id: string;
  name: string;
  token_prefix: string;
  status: "active" | "revoked";
  expires_at: string | null;
  last_used_at: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ServiceAccountTokenCreated = ServiceAccountToken & {
  raw_token: string;
};

export type ServiceAccountTokenListResponse = {
  items: ServiceAccountToken[];
  total: number;
};

export type CreateServiceAccountTokenRequest = {
  name: string;
  expires_at?: string | null;
};

function normalizeServiceAccount(value: unknown): ServiceAccount {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  const env = raw.environment as string;
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    name: typeof raw.name === "string" ? raw.name : "",
    description: typeof raw.description === "string" ? raw.description : null,
    environment: (VALID_ENVIRONMENTS as readonly string[]).includes(env)
      ? (env as ServiceAccountEnvironment)
      : "production",
    scopes: Array.isArray(raw.scopes)
      ? (raw.scopes as unknown[]).filter(
          (s): s is string => typeof s === "string",
        )
      : [],
    is_active: raw.is_active === true,
    last_used_at:
      typeof raw.last_used_at === "string" ? raw.last_used_at : null,
    created_by_id:
      typeof raw.created_by_id === "string" ? raw.created_by_id : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

function normalizeToken(value: unknown): ServiceAccountToken {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    service_account_id:
      typeof raw.service_account_id === "string" ? raw.service_account_id : "",
    name: typeof raw.name === "string" ? raw.name : "",
    token_prefix: typeof raw.token_prefix === "string" ? raw.token_prefix : "",
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

function normalizeTokenCreated(value: unknown): ServiceAccountTokenCreated {
  const base = normalizeToken(value);
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    ...base,
    raw_token: typeof raw.raw_token === "string" ? raw.raw_token : "",
  };
}

export async function listServiceAccounts(): Promise<ServiceAccountListResponse> {
  const payload = await apiRequest<unknown>("/admin/service-accounts", {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items.map(normalizeServiceAccount)
    : [];
  return {
    items,
    total: typeof raw.total === "number" ? raw.total : items.length,
  };
}

export async function getServiceAccount(
  accountId: string,
): Promise<ServiceAccount> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}`,
    { method: "GET", retry: false },
  );
  return normalizeServiceAccount(payload);
}

export async function createServiceAccount(
  request: CreateServiceAccountRequest,
): Promise<ServiceAccount> {
  const payload = await apiRequest<unknown>("/admin/service-accounts", {
    method: "POST",
    json: {
      name: request.name,
      description: request.description ?? null,
      environment: request.environment ?? "production",
      scopes: request.scopes,
    },
    retry: false,
  });
  return normalizeServiceAccount(payload);
}

export async function updateServiceAccount(
  accountId: string,
  request: UpdateServiceAccountRequest,
): Promise<ServiceAccount> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}`,
    { method: "PATCH", json: request, retry: false },
  );
  return normalizeServiceAccount(payload);
}

export async function deactivateServiceAccount(
  accountId: string,
): Promise<ServiceAccount> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/deactivate`,
    { method: "POST", retry: false },
  );
  return normalizeServiceAccount(payload);
}

export async function reactivateServiceAccount(
  accountId: string,
): Promise<ServiceAccount> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/reactivate`,
    { method: "POST", retry: false },
  );
  return normalizeServiceAccount(payload);
}

export async function listTokens(
  accountId: string,
): Promise<ServiceAccountTokenListResponse> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/tokens`,
    { method: "GET", retry: false },
  );
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items) ? raw.items.map(normalizeToken) : [];
  return {
    items,
    total: typeof raw.total === "number" ? raw.total : items.length,
  };
}

export async function createToken(
  accountId: string,
  request: CreateServiceAccountTokenRequest,
): Promise<ServiceAccountTokenCreated> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/tokens`,
    {
      method: "POST",
      json: {
        name: request.name,
        expires_at: request.expires_at ?? null,
      },
      retry: false,
    },
  );
  return normalizeTokenCreated(payload);
}

export async function revokeToken(
  accountId: string,
  tokenId: string,
): Promise<void> {
  await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/tokens/${encodeURIComponent(tokenId)}`,
    { method: "DELETE", retry: false },
  );
}

export async function rotateToken(
  accountId: string,
  tokenId: string,
): Promise<ServiceAccountTokenCreated> {
  const payload = await apiRequest<unknown>(
    `/admin/service-accounts/${encodeURIComponent(accountId)}/tokens/${encodeURIComponent(tokenId)}/rotate`,
    { method: "POST", retry: false },
  );
  return normalizeTokenCreated(payload);
}
