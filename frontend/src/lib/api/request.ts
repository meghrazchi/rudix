import {
  clearSessionStorage,
  emitAuthBoundaryEvent,
  readSessionFromStorage,
  writeSessionToStorage,
  type AuthBoundaryReason,
  type AuthenticatedSession,
} from "@/lib/auth-session";
import { clearAuthSensitiveQueryState } from "@/lib/api/query";

import {
  ApiClientError,
  isApiClientError,
  normalizeApiError,
  normalizeNetworkError,
} from "@/lib/api/errors";

const DEFAULT_API_BASE = "http://localhost:8000/api/v1";
const DEFAULT_RETRYABLE_STATUS_CODES = new Set([429, 503]);
const DEFAULT_RETRY_DELAY_MS = 250;
const DEFAULT_REFRESH_PATH = "/auth/token/refresh";
const DEFAULT_LOGOUT_PATH = "/auth/logout";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

export type AuthRetryPolicy = "safe" | "always" | "never";

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
  credentials?: RequestCredentials;
  authRetry?: AuthRetryPolicy;
  skipAuthRefresh?: boolean;
  responseType?: "json" | "blob" | "text";
};

export type SessionRequestContext = {
  token: string | null;
  organizationId: string | null;
  userId: string | null;
};

type RefreshTrigger = "preflight" | "proactive" | "401";

type RefreshResponse = {
  access_token?: string | null;
  token?: string | null;
  refresh_token?: string | null;
  refreshToken?: string | null;
};

let refreshInFlight: Promise<AuthenticatedSession | null> | null = null;
let proactiveRefreshTimer: ReturnType<typeof setTimeout> | null = null;
const pendingProtectedRequests = new Set<AbortController>();

function trimToNull(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeAuthProvider(value: string | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

function shouldAttachOrganizationHeader(
  organizationId: string | null,
): boolean {
  if (!organizationId) {
    return false;
  }

  const provider = normalizeAuthProvider(process.env.NEXT_PUBLIC_AUTH_PROVIDER);
  if (provider !== "app") {
    return true;
  }

  // App auth resolves organization from token memberships; avoid sending local slug placeholders.
  return UUID_PATTERN.test(organizationId);
}

function isSafeMethod(method: string): boolean {
  return method === "GET" || method === "HEAD";
}

function resolveApiBaseUrl(apiBaseUrl?: string): string {
  const resolved =
    apiBaseUrl ?? process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_BASE;
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
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return undefined;
}

function parseIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return parsed;
}

function getRefreshLeadTimeMs(): number {
  const seconds = parseIntegerEnv(
    process.env.NEXT_PUBLIC_AUTH_REFRESH_SKEW_SECONDS,
    60,
  );
  return Math.max(0, seconds * 1_000);
}

function resolveRefreshUrl(apiBaseUrl?: string): string {
  const configured = trimToNull(process.env.NEXT_PUBLIC_AUTH_REFRESH_URL);
  if (configured) {
    return toAbsoluteUrl(configured, apiBaseUrl);
  }

  return toAbsoluteUrl(DEFAULT_REFRESH_PATH, apiBaseUrl);
}

function resolveLogoutUrl(apiBaseUrl?: string): string | null {
  const configured = trimToNull(process.env.NEXT_PUBLIC_AUTH_LOGOUT_URL);
  if (configured) {
    return toAbsoluteUrl(configured, apiBaseUrl);
  }

  const provider = normalizeAuthProvider(process.env.NEXT_PUBLIC_AUTH_PROVIDER);
  if (provider === "app") {
    return toAbsoluteUrl(DEFAULT_LOGOUT_PATH, apiBaseUrl);
  }
  return null;
}

function hasConfiguredRefreshUrl(): boolean {
  return trimToNull(process.env.NEXT_PUBLIC_AUTH_REFRESH_URL) !== null;
}

function getCurrentPathForRedirect(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return `${window.location.pathname}${window.location.search}`;
}

function toAuthBoundaryReason(refreshError: unknown): AuthBoundaryReason {
  if (isApiClientError(refreshError)) {
    if (refreshError.status === 401) {
      return "session_expired";
    }
    if (refreshError.status === 403) {
      return "session_revoked";
    }
    if (refreshError.status === 400 || refreshError.status === 422) {
      return "session_invalid";
    }
  }
  return "session_refresh_failed";
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }

  const payload = parts[1];
  if (!payload) {
    return null;
  }

  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(
      normalized.length + ((4 - (normalized.length % 4)) % 4),
      "=",
    );

    let decoded = "";
    if (typeof atob === "function") {
      decoded = atob(padded);
    } else if (typeof Buffer !== "undefined") {
      decoded = Buffer.from(padded, "base64").toString("utf8");
    } else {
      return null;
    }

    const parsed = JSON.parse(decoded) as unknown;
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      return null;
    }

    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getJwtExpirationTimeMs(
  token: string | null | undefined,
): number | null {
  const normalizedToken = trimToNull(token);
  if (!normalizedToken) {
    return null;
  }

  const payload = decodeJwtPayload(normalizedToken);
  if (!payload) {
    return null;
  }

  const exp = payload.exp;
  if (typeof exp !== "number" || !Number.isFinite(exp) || exp <= 0) {
    return null;
  }

  return exp * 1_000;
}

function shouldRefreshBeforeRequest(token: string | null): boolean {
  const expiresAt = getJwtExpirationTimeMs(token);
  if (!expiresAt) {
    return false;
  }

  const refreshAt = expiresAt - getRefreshLeadTimeMs();
  return Date.now() >= refreshAt;
}

function canAttemptRefresh(session: AuthenticatedSession | null): boolean {
  if (!session) {
    return false;
  }

  if (trimToNull(session.refreshToken) || hasConfiguredRefreshUrl()) {
    return true;
  }

  const provider = normalizeAuthProvider(process.env.NEXT_PUBLIC_AUTH_PROVIDER);
  if (provider === "app") {
    return true;
  }

  return false;
}

function clearProactiveRefreshTimer(): void {
  if (proactiveRefreshTimer) {
    clearTimeout(proactiveRefreshTimer);
    proactiveRefreshTimer = null;
  }
}

function trackProtectedRequest(controller: AbortController): void {
  pendingProtectedRequests.add(controller);
}

function untrackProtectedRequest(controller: AbortController): void {
  pendingProtectedRequests.delete(controller);
}

export function cancelPendingProtectedRequests(): void {
  for (const controller of pendingProtectedRequests) {
    controller.abort("auth-boundary");
  }
  pendingProtectedRequests.clear();
}

export async function clearAuthSensitiveClientState(): Promise<void> {
  cancelPendingProtectedRequests();
  await clearAuthSensitiveQueryState();
}

function scheduleProactiveRefresh(session: AuthenticatedSession): void {
  clearProactiveRefreshTimer();

  if (!canAttemptRefresh(session)) {
    return;
  }

  const token = trimToNull(session.accessToken);
  if (!token) {
    return;
  }

  const expiresAt = getJwtExpirationTimeMs(token);
  if (!expiresAt) {
    return;
  }

  const refreshAt = expiresAt - getRefreshLeadTimeMs();
  const delayMs = Math.max(0, refreshAt - Date.now());
  const fingerprint = `${session.userId}:${token}`;

  proactiveRefreshTimer = setTimeout(() => {
    const current = readSessionFromStorage();
    const currentToken = trimToNull(current?.accessToken);
    const currentFingerprint =
      current && currentToken ? `${current.userId}:${currentToken}` : null;
    if (!current || currentFingerprint !== fingerprint) {
      return;
    }

    void refreshAccessToken({
      trigger: "proactive",
    }).catch(async (error) => {
      await clearFrontendAuthState({
        reason: toAuthBoundaryReason(error),
        preserveNextPath: true,
        redirectToLogin: true,
      });
    });
  }, delayMs);
}

function persistSessionWithRefreshState(session: AuthenticatedSession): void {
  writeSessionToStorage(session);
  scheduleProactiveRefresh(session);
}

function resolveResponseRequestId(response: Response): string | null {
  return (
    response.headers.get("x-request-id") ?? response.headers.get("X-Request-ID")
  );
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

function resolveRetryPolicy(
  method: string,
  retry: RetryPolicy | undefined,
): {
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

function buildHeaders(options: ApiRequestOptions): Headers {
  const headers = new Headers(options.headers);
  const method = (options.method ?? "GET").toUpperCase();

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const sessionContext = getSessionRequestContext();
  const shouldAttachAuth = options.attachAuth ?? true;
  const shouldAttachOrganizationId = options.attachOrganizationId ?? true;

  const token =
    trimToNull(options.token) ??
    (shouldAttachAuth ? sessionContext.token : null);
  const organizationId =
    trimToNull(options.organizationId) ??
    (shouldAttachOrganizationId ? sessionContext.organizationId : null);

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (organizationId && shouldAttachOrganizationHeader(organizationId)) {
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

function shouldReplayAfterRefresh(
  method: string,
  policy: AuthRetryPolicy,
): boolean {
  if (policy === "never") {
    return false;
  }
  if (policy === "always") {
    return true;
  }
  return isSafeMethod(method);
}

function buildRefreshFailureError(): ApiClientError {
  return new ApiClientError({
    status: 401,
    code: "session_refresh_required_retry",
    message: "Session was refreshed. Retry the previous action.",
    details: null,
    requestId: null,
    userMessage: "Your session was refreshed.",
    actionMessage: "Retry the action.",
    retryable: true,
  });
}

function createRequestController(params: {
  externalSignal?: AbortSignal;
  trackProtected: boolean;
}): {
  signal: AbortSignal;
  cleanup: () => void;
} {
  const controller = new AbortController();
  const { externalSignal, trackProtected } = params;

  if (trackProtected) {
    trackProtectedRequest(controller);
  }

  if (externalSignal?.aborted) {
    controller.abort(externalSignal.reason);
  }

  const onAbort = () => {
    controller.abort(externalSignal?.reason);
  };

  externalSignal?.addEventListener("abort", onAbort);

  return {
    signal: controller.signal,
    cleanup: () => {
      externalSignal?.removeEventListener("abort", onAbort);
      if (trackProtected) {
        untrackProtectedRequest(controller);
      }
    },
  };
}

function parseRefreshedSession(
  payload: unknown,
  currentSession: AuthenticatedSession,
): AuthenticatedSession {
  const response = (
    typeof payload === "object" && payload !== null ? payload : {}
  ) as RefreshResponse;
  const accessToken =
    trimToNull(response.access_token) ?? trimToNull(response.token);
  const refreshToken =
    trimToNull(response.refresh_token) ??
    trimToNull(response.refreshToken) ??
    trimToNull(currentSession.refreshToken);

  if (!accessToken) {
    throw normalizeApiError({
      status: 401,
      payload: {
        detail: {
          code: "session_invalid",
          message: "Refresh response did not include an access token.",
        },
      },
    });
  }

  return {
    ...currentSession,
    accessToken,
    refreshToken,
  };
}

async function executeRefreshRequest(params: {
  currentSession: AuthenticatedSession;
  apiBaseUrl?: string;
}): Promise<AuthenticatedSession> {
  const refreshToken = trimToNull(params.currentSession.refreshToken);
  const response = await fetch(resolveRefreshUrl(params.apiBaseUrl), {
    method: "POST",
    headers: new Headers({
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    credentials: "include",
    cache: "no-store",
  });

  const parsedBody = await parseJsonOrText(response);
  if (!response.ok) {
    throw normalizeApiError({
      status: response.status,
      payload: parsedBody,
      requestId: resolveResponseRequestId(response),
    });
  }

  const refreshedSession = parseRefreshedSession(
    parsedBody,
    params.currentSession,
  );
  persistSessionWithRefreshState(refreshedSession);
  return refreshedSession;
}

export async function refreshAccessToken(params?: {
  apiBaseUrl?: string;
  trigger?: RefreshTrigger;
}): Promise<AuthenticatedSession | null> {
  const trigger = params?.trigger ?? "preflight";
  const currentSession = readSessionFromStorage();
  if (!currentSession || !canAttemptRefresh(currentSession)) {
    return null;
  }

  const shouldSkipBecauseNotNearExpiry =
    trigger === "preflight" &&
    !shouldRefreshBeforeRequest(trimToNull(currentSession.accessToken));
  if (shouldSkipBecauseNotNearExpiry) {
    return currentSession;
  }

  if (!refreshInFlight) {
    refreshInFlight = executeRefreshRequest({
      currentSession,
      apiBaseUrl: params?.apiBaseUrl,
    }).finally(() => {
      refreshInFlight = null;
    });
  }

  return refreshInFlight;
}

export function getSessionRequestContext(): SessionRequestContext {
  const session = readSessionFromStorage();

  return {
    token: trimToNull(session?.accessToken ?? null),
    organizationId: trimToNull(session?.organizationId ?? null),
    userId: trimToNull(session?.userId ?? null),
  };
}

export function syncSessionRefreshState(
  session: AuthenticatedSession | null,
): void {
  if (!session) {
    clearProactiveRefreshTimer();
    return;
  }

  scheduleProactiveRefresh(session);
}

export async function clearFrontendAuthState(params: {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  redirectToLogin: boolean;
}): Promise<void> {
  clearProactiveRefreshTimer();
  clearSessionStorage();
  await clearAuthSensitiveClientState();

  const boundaryEvent = emitAuthBoundaryEvent({
    reason: params.reason,
    preserveNextPath: params.preserveNextPath,
    nextPath: getCurrentPathForRedirect(),
  });

  if (
    params.redirectToLogin &&
    typeof window !== "undefined" &&
    process.env.NODE_ENV !== "test" &&
    !window.location.pathname.startsWith("/login")
  ) {
    window.location.replace(boundaryEvent.redirectTo);
  }
}

export async function performLogout(params?: {
  apiBaseUrl?: string;
  redirectToLogin?: boolean;
}): Promise<void> {
  const currentSession = readSessionFromStorage();
  const logoutUrl = resolveLogoutUrl(params?.apiBaseUrl);
  if (logoutUrl) {
    try {
      const headers = new Headers({ Accept: "application/json" });
      const token = trimToNull(currentSession?.accessToken);
      const refreshToken = trimToNull(currentSession?.refreshToken);
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      if (refreshToken) {
        headers.set("Content-Type", "application/json");
      }

      await fetch(logoutUrl, {
        method: "POST",
        headers,
        body: refreshToken
          ? JSON.stringify({ refresh_token: refreshToken })
          : undefined,
        credentials: "include",
        cache: "no-store",
      });
    } catch {
      // Logout endpoint failure should not block local sign-out.
    }
  }

  await clearFrontendAuthState({
    reason: "signed_out",
    preserveNextPath: false,
    redirectToLogin: params?.redirectToLogin ?? false,
  });
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const policy = resolveRetryPolicy(method, options.retry);
  const url = appendQueryParams(
    toAbsoluteUrl(path, options.apiBaseUrl),
    options.query,
  );
  const shouldAttachAuth = options.attachAuth ?? true;
  const authRetryPolicy = options.authRetry ?? "safe";

  const controller = createRequestController({
    externalSignal: options.signal,
    trackProtected: shouldAttachAuth,
  });

  let attempt = 0;
  let authReplayAttempted = false;

  try {
    while (true) {
      attempt += 1;

      if (shouldAttachAuth && !options.skipAuthRefresh) {
        try {
          await refreshAccessToken({
            apiBaseUrl: options.apiBaseUrl,
            trigger: "preflight",
          });
        } catch (error) {
          await clearFrontendAuthState({
            reason: toAuthBoundaryReason(error),
            preserveNextPath: true,
            redirectToLogin: true,
          });
          throw error;
        }
      }

      const headers = buildHeaders({
        ...options,
        method: method as ApiRequestOptions["method"],
      });

      try {
        const response = await fetch(url, {
          method,
          headers,
          body:
            options.json !== undefined
              ? JSON.stringify(options.json)
              : options.body,
          signal: controller.signal,
          cache: options.cache,
          credentials: options.credentials,
        });

        if (!response.ok) {
          const parsedBody = await parseJsonOrText(response);
          const requestId = resolveResponseRequestId(response);
          const error = normalizeApiError({
            status: response.status,
            payload: parsedBody,
            requestId,
          });

          if (
            error.status === 401 &&
            shouldAttachAuth &&
            !options.skipAuthRefresh &&
            !authReplayAttempted &&
            canAttemptRefresh(readSessionFromStorage())
          ) {
            authReplayAttempted = true;
            try {
              await refreshAccessToken({
                apiBaseUrl: options.apiBaseUrl,
                trigger: "401",
              });
            } catch (refreshError) {
              await clearFrontendAuthState({
                reason: toAuthBoundaryReason(refreshError),
                preserveNextPath: true,
                redirectToLogin: true,
              });
              throw refreshError;
            }

            if (shouldReplayAfterRefresh(method, authRetryPolicy)) {
              continue;
            }

            throw buildRefreshFailureError();
          }

          if (
            error.status === 401 &&
            shouldAttachAuth &&
            !options.skipAuthRefresh
          ) {
            await clearFrontendAuthState({
              reason: "session_expired",
              preserveNextPath: true,
              redirectToLogin: true,
            });
          }

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

        if (options.responseType === "blob") {
          return (await response.blob()) as T;
        }

        if (options.responseType === "text") {
          return (await response.text()) as T;
        }

        const parsedBody = await parseJsonOrText(response);
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
  } finally {
    controller.cleanup();
  }
}

export async function apiRequestVoid(
  path: string,
  options: ApiRequestOptions = {},
): Promise<void> {
  await apiRequest<unknown>(path, options);
}
