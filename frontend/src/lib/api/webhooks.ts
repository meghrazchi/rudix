import { apiRequest } from "@/lib/api/request";

export const WEBHOOK_EVENT_TYPES = [
  "document.indexed",
  "document.failed",
  "document.deleted",
  "evaluation.completed",
  "evaluation.failed",
  "feedback.created",
  "connector.sync_failed",
  "quota.reached",
] as const;

export type WebhookEventType = (typeof WEBHOOK_EVENT_TYPES)[number];

export const WEBHOOK_EVENT_LABELS: Record<WebhookEventType, string> = {
  "document.indexed": "Document indexed",
  "document.failed": "Document processing failed",
  "document.deleted": "Document deleted",
  "evaluation.completed": "Evaluation completed",
  "evaluation.failed": "Evaluation failed",
  "feedback.created": "Feedback submitted",
  "connector.sync_failed": "Connector sync failed",
  "quota.reached": "Quota limit reached",
};

export type Webhook = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  url: string;
  secret_prefix: string;
  event_types: string[];
  status: "active" | "disabled";
  retry_policy: { max_attempts: number; backoff_seconds: number };
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type WebhookCreated = Webhook & {
  raw_secret: string;
};

export type WebhookDelivery = {
  id: string;
  webhook_id: string;
  organization_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  status: "pending" | "delivered" | "failed";
  http_status_code: number | null;
  response_body: string | null;
  attempt_count: number;
  next_retry_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type WebhookListResponse = { items: Webhook[]; total: number };
export type WebhookDeliveryListResponse = { items: WebhookDelivery[]; total: number };

export type CreateWebhookRequest = {
  name: string;
  description?: string | null;
  url: string;
  event_types: string[];
  retry_policy?: { max_attempts: number; backoff_seconds: number };
};

export type UpdateWebhookRequest = {
  name?: string | null;
  description?: string | null;
  url?: string | null;
  event_types?: string[] | null;
  status?: "active" | "disabled" | null;
  retry_policy?: { max_attempts: number; backoff_seconds: number } | null;
};

function normalizeRetryPolicy(raw: unknown): { max_attempts: number; backoff_seconds: number } {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    max_attempts: typeof obj.max_attempts === "number" ? obj.max_attempts : 5,
    backoff_seconds: typeof obj.backoff_seconds === "number" ? obj.backoff_seconds : 60,
  };
}

function normalizeWebhook(value: unknown): Webhook {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id: typeof raw.organization_id === "string" ? raw.organization_id : "",
    name: typeof raw.name === "string" ? raw.name : "",
    description: typeof raw.description === "string" ? raw.description : null,
    url: typeof raw.url === "string" ? raw.url : "",
    secret_prefix: typeof raw.secret_prefix === "string" ? raw.secret_prefix : "",
    event_types: Array.isArray(raw.event_types)
      ? (raw.event_types as unknown[]).filter((e): e is string => typeof e === "string")
      : [],
    status: raw.status === "disabled" ? "disabled" : "active",
    retry_policy: normalizeRetryPolicy(raw.retry_policy),
    created_by_id: typeof raw.created_by_id === "string" ? raw.created_by_id : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

function normalizeWebhookCreated(value: unknown): WebhookCreated {
  const base = normalizeWebhook(value);
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return { ...base, raw_secret: typeof raw.raw_secret === "string" ? raw.raw_secret : "" };
}

function normalizeDelivery(value: unknown): WebhookDelivery {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const statusRaw = raw.status;
  const status: WebhookDelivery["status"] =
    statusRaw === "delivered" ? "delivered" : statusRaw === "failed" ? "failed" : "pending";
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    webhook_id: typeof raw.webhook_id === "string" ? raw.webhook_id : "",
    organization_id: typeof raw.organization_id === "string" ? raw.organization_id : "",
    event_type: typeof raw.event_type === "string" ? raw.event_type : "",
    payload: raw.payload && typeof raw.payload === "object"
      ? (raw.payload as Record<string, unknown>)
      : {},
    status,
    http_status_code: typeof raw.http_status_code === "number" ? raw.http_status_code : null,
    response_body: typeof raw.response_body === "string" ? raw.response_body : null,
    attempt_count: typeof raw.attempt_count === "number" ? raw.attempt_count : 0,
    next_retry_at: typeof raw.next_retry_at === "string" ? raw.next_retry_at : null,
    error_message: typeof raw.error_message === "string" ? raw.error_message : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

export async function listWebhooks(): Promise<WebhookListResponse> {
  const payload = await apiRequest<unknown>("/admin/webhooks", { method: "GET", retry: false });
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const items = Array.isArray(raw.items) ? raw.items.map(normalizeWebhook) : [];
  return { items, total: typeof raw.total === "number" ? raw.total : items.length };
}

export async function getWebhook(webhookId: string): Promise<Webhook> {
  const payload = await apiRequest<unknown>(
    `/admin/webhooks/${encodeURIComponent(webhookId)}`,
    { method: "GET", retry: false },
  );
  return normalizeWebhook(payload);
}

export async function createWebhook(request: CreateWebhookRequest): Promise<WebhookCreated> {
  const payload = await apiRequest<unknown>("/admin/webhooks", {
    method: "POST",
    json: {
      name: request.name,
      description: request.description ?? null,
      url: request.url,
      event_types: request.event_types,
      retry_policy: request.retry_policy ?? { max_attempts: 5, backoff_seconds: 60 },
    },
    retry: false,
  });
  return normalizeWebhookCreated(payload);
}

export async function updateWebhook(
  webhookId: string,
  request: UpdateWebhookRequest,
): Promise<Webhook> {
  const payload = await apiRequest<unknown>(
    `/admin/webhooks/${encodeURIComponent(webhookId)}`,
    { method: "PATCH", json: request, retry: false },
  );
  return normalizeWebhook(payload);
}

export async function deleteWebhook(webhookId: string): Promise<void> {
  await apiRequest<unknown>(`/admin/webhooks/${encodeURIComponent(webhookId)}`, {
    method: "DELETE",
    retry: false,
  });
}

export async function rotateWebhookSecret(webhookId: string): Promise<WebhookCreated> {
  const payload = await apiRequest<unknown>(
    `/admin/webhooks/${encodeURIComponent(webhookId)}/rotate-secret`,
    { method: "POST", retry: false },
  );
  return normalizeWebhookCreated(payload);
}

export async function testWebhook(webhookId: string): Promise<WebhookDeliveryListResponse> {
  const payload = await apiRequest<unknown>(
    `/admin/webhooks/${encodeURIComponent(webhookId)}/test`,
    { method: "POST", retry: false },
  );
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const items = Array.isArray(raw.items) ? raw.items.map(normalizeDelivery) : [];
  return { items, total: typeof raw.total === "number" ? raw.total : items.length };
}

export async function listWebhookDeliveries(
  webhookId: string,
): Promise<WebhookDeliveryListResponse> {
  const payload = await apiRequest<unknown>(
    `/admin/webhooks/${encodeURIComponent(webhookId)}/deliveries`,
    { method: "GET", retry: false },
  );
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const items = Array.isArray(raw.items) ? raw.items.map(normalizeDelivery) : [];
  return { items, total: typeof raw.total === "number" ? raw.total : items.length };
}
