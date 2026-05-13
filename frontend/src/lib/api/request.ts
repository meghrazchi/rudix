import { readSessionFromStorage } from "@/lib/auth-session";

import {
  ApiClientError,
  isApiClientError,
  normalizeApiError,
  normalizeNetworkError,
} from "@/lib/api/errors";

const DEFAULT_API_BASE = "http://localhost:8000/api/v1";
const DEFAULT_RETRYABLE_STATUS_CODES = new Set([429, 503]);
const DEFAULT_RETRY_DELAY_MS = 250;

type PrimitiveQueryValue = string | number | boolean | null | undefined;
export type ApiQueryValue = PrimitiveQueryValue | PrimitiveQueryValue[];
export type ApiQuery = Record<string, ApiQueryValue>;

export type RetryPolicy =
  | false
  | {
      maxRetries?: number;
      baseDelayMs?: number;
      retryableStatusCodes?: number[];
    };

export type ApiRequestOptions = {
  apiBaseUrl?: string;
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  headers?: HeadersInit;
  query?: ApiQuery;
  json?: unknown;
  body?: BodyInit;
  token?: string;
  organizationId?: string;
  attachAuth?: boolean;
  attachOrganizationId?: boolean;
  requestId?: string;
  retry?: RetryPolicy;
  signal?: AbortSignal;
  cache?: RequestCache;
};

export type SessionRequestContext = {
  token: string | null;
  organizationId: string | null;
  userId: string | null;
};

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function isSafeMethod(method: string): boolean {
  return method === "GET" || method === "HEAD";
}

function resolveApiBaseUrl(apiBaseUrl?: string): string {
  const resolved = apiBaseUrl ?? process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_BASE;
  return resolved.replace(/\/$/, "");
}

function toAbsoluteUrl(path: string, apiBaseUrl?: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${resolveApiBaseUrl(apiBaseUrl)}${normalizedPath}`;
}

function appendQueryParams(url: string, query?: ApiQuery): string {
  if (!query) {
    return url;
  }

  const result = new URL(url);

  for (const [key, rawValue] of Object.entries(query)) {
    if (rawValue === undefined || rawValue === null) {
      continue;
    }

    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      if (value === undefined || value === null) {
        continue;
      }
      result.searchParams.append(key, String(value));
    }
  }

  return result.toString();
}

function generateRequestId(): string | undefined {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return undefined;
}

export function getSessionRequestContext(): SessionRequestContext {
  const session = readSessionFromStorage();

  return {
    token: trimToNull(session?.accessToken ?? null),
    organizationId: trimToNull(session?.organizationId ?? null),
    userId: trimToNull(session?.userId ?? null),
  };
}

function buildHeaders(options: ApiRequestOptions): Headers {
  const headers = new Headers(options.headers);
  const method = (options.method ?? "GET").toUpperCase();

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const sessionContext = getSessionRequestContext();
  const shouldAttachAuth = options.attachAuth ?? true;
  const shouldAttachOrganizationId = options.attachOrganizationId ?? true;

  const token = trimToNull(options.token) ?? (shouldAttachAuth ? sessionContext.token : null);
  const organizationId =
    trimToNull(options.organizationId) ?? (shouldAttachOrganizationId ? sessionContext.organizationId : null);

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (organizationId) {
    headers.set("X-Organization-ID", organizationId);
  }

  const requestId = trimToNull(options.requestId) ?? generateRequestId();
  if (requestId && !headers.has("X-Request-ID")) {
    headers.set("X-Request-ID", requestId);
  }

  if (options.json !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (method === "GET" || method === "HEAD") {
    headers.delete("Content-Type");
  }

  return headers;
}

function resolveRetryPolicy(method: string, retry: RetryPolicy | undefined): {
  maxRetries: number;
  baseDelayMs: number;
  retryableStatusCodes: Set<number>;
} {
  if (retry === false) {
    return {
      maxRetries: 0,
      baseDelayMs: 0,
      retryableStatusCodes: new Set(),
    };
  }

  const maxRetries =
    retry?.maxRetries ??
    (isSafeMethod(method)
      ? Number.parseInt(process.env.NEXT_PUBLIC_API_SAFE_RETRIES ?? "1", 10)
      : 0);

  const baseDelayMs = retry?.baseDelayMs ?? DEFAULT_RETRY_DELAY_MS;

  const retryableStatusCodes = new Set(
    retry?.retryableStatusCodes ?? Array.from(DEFAULT_RETRYABLE_STATUS_CODES),
  );

  return {
    maxRetries: Number.isFinite(maxRetries) && maxRetries > 0 ? maxRetries : 0,
    baseDelayMs,
    retryableStatusCodes,
  };
}

function delay(ms: number): Promise<void> {
  if (ms <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function retryDelay(baseDelayMs: number, attempt: number): number {
  return Math.min(baseDelayMs * 2 ** Math.max(0, attempt - 1), 2_000);
}

function resolveResponseRequestId(response: Response): string | null {
  return response.headers.get("x-request-id") ?? response.headers.get("X-Request-ID");
}

async function parseJsonOrText(response: Response): Promise<unknown> {
  const rawBody = await response.text();
  if (!rawBody) {
    return null;
  }

  try {
    return JSON.parse(rawBody) as unknown;
  } catch {
    return rawBody;
  }
}

function shouldRetryError(
  error: unknown,
  context: {
    retryableStatusCodes: Set<number>;
    method: string;
    attempt: number;
    maxRetries: number;
  },
): boolean {
  const { retryableStatusCodes, method, attempt, maxRetries } = context;
  if (!isSafeMethod(method) || attempt > maxRetries) {
    return false;
  }

  if (error instanceof ApiClientError) {
    return error.retryable && retryableStatusCodes.has(error.status);
  }

  return true;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const policy = resolveRetryPolicy(method, options.retry);

  const headers = buildHeaders({ ...options, method: method as ApiRequestOptions["method"] });
  const url = appendQueryParams(toAbsoluteUrl(path, options.apiBaseUrl), options.query);

  let attempt = 0;

  while (true) {
    attempt += 1;

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: options.json !== undefined ? JSON.stringify(options.json) : options.body,
        signal: options.signal,
        cache: options.cache,
      });

      const parsedBody = await parseJsonOrText(response);

      if (!response.ok) {
        const requestId = resolveResponseRequestId(response);
        const error = normalizeApiError({
          status: response.status,
          payload: parsedBody,
          requestId,
        });

        if (
          shouldRetryError(error, {
            retryableStatusCodes: policy.retryableStatusCodes,
            method,
            attempt,
            maxRetries: policy.maxRetries,
          })
        ) {
          await delay(retryDelay(policy.baseDelayMs, attempt));
          continue;
        }

        throw error;
      }

      if (parsedBody === null) {
        return {} as T;
      }

      return parsedBody as T;
    } catch (error) {
      if (isApiClientError(error)) {
        throw error;
      }

      const normalizedError = normalizeNetworkError(error);
      if (
        shouldRetryError(normalizedError, {
          retryableStatusCodes: policy.retryableStatusCodes,
          method,
          attempt,
          maxRetries: policy.maxRetries,
        })
      ) {
        await delay(retryDelay(policy.baseDelayMs, attempt));
        continue;
      }

      throw normalizedError;
    }
  }
}

export async function apiRequestVoid(path: string, options: ApiRequestOptions = {}): Promise<void> {
  await apiRequest<unknown>(path, options);
}
