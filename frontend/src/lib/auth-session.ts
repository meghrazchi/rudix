import {
  clearSession as clearStoredSession,
  getSession as getStoredSession,
  primeSession,
  SESSION_STORE_EVENT_NAME,
  setSession as setStoredSession,
} from "@/lib/auth/session-store";

export type AppRole =
  | "owner"
  | "admin"
  | "member"
  | "viewer"
  | "reviewer"
  | "developer"
  | "security_admin"
  | "billing_admin";

export type AuthenticatedSession = {
  userId: string;
  email: string | null;
  role: AppRole;
  organizationId: string | null;
  organizationName: string | null;
  accessToken?: string | null;
  refreshToken?: string | null;
};

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export type SessionState = {
  status: SessionStatus;
  session: AuthenticatedSession | null;
};

export type AuthBoundaryReason =
  | "signed_out"
  | "session_expired"
  | "session_revoked"
  | "session_invalid"
  | "session_refresh_failed";

export type AuthBoundaryEventDetail = {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  redirectTo: string;
  occurredAt: number;
};

export const SESSION_STORAGE_KEY = "rudix.session.v1";
export const AUTH_BOUNDARY_STORAGE_KEY = "rudix.auth.boundary.v1";
export const AUTH_BOUNDARY_EVENT_NAME = "rudix:auth-boundary";
export const SESSION_STORAGE_EVENT_NAME = SESSION_STORE_EVENT_NAME;

const VALID_ROLES: ReadonlySet<string> = new Set([
  "owner",
  "admin",
  "member",
  "viewer",
  "reviewer",
  "developer",
  "security_admin",
  "billing_admin",
]);

function isRole(value: unknown): value is AppRole {
  return typeof value === "string" && VALID_ROLES.has(value);
}

function isValidSession(value: unknown): value is AuthenticatedSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<AuthenticatedSession>;
  return (
    typeof candidate.userId === "string" &&
    candidate.userId.trim().length > 0 &&
    isRole(candidate.role) &&
    (candidate.email === null || typeof candidate.email === "string") &&
    (candidate.organizationId === null ||
      typeof candidate.organizationId === "string") &&
    (candidate.organizationName === null ||
      typeof candidate.organizationName === "string") &&
    (candidate.accessToken === undefined ||
      candidate.accessToken === null ||
      typeof candidate.accessToken === "string") &&
    (candidate.refreshToken === undefined ||
      candidate.refreshToken === null ||
      typeof candidate.refreshToken === "string")
  );
}

export function defaultSessionState(): SessionState {
  return {
    status: "loading",
    session: null,
  };
}

/** Legacy `localStorage` key, read once as a fallback until 0.8.0 (R07-09). */
export const LEGACY_SESSION_STORAGE_KEY = SESSION_STORAGE_KEY;
/** Dev-only `sessionStorage` key for the local sign-in fallback. */
export const DEV_SESSION_STORAGE_KEY = "rudix.session.dev.v1";

function isLegacySessionReadEnabled(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_LEGACY_SESSION_READ !== "false";
}

/**
 * The local sign-in fallback has no refresh cookie, so a reload could not
 * restore its session. It keeps a tab-scoped copy in `sessionStorage`. The
 * build refuses these variables in staging and production
 * (`config/build-env-validation.mjs`).
 */
export function isDevSessionPersistenceEnabled(): boolean {
  return (
    process.env.NEXT_PUBLIC_AUTH_LOCAL_FALLBACK?.trim() === "true" ||
    (process.env.NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN?.trim() ?? "") !== ""
  );
}

function parseStoredSession(raw: string | null): AuthenticatedSession | null {
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isValidSession(parsed)) {
      return null;
    }
    const { refreshToken: _refreshToken, ...session } = parsed;
    return session;
  } catch {
    return null;
  }
}

function readDevSession(): AuthenticatedSession | null {
  if (!isDevSessionPersistenceEnabled()) {
    return null;
  }
  try {
    return parseStoredSession(
      window.sessionStorage.getItem(DEV_SESSION_STORAGE_KEY),
    );
  } catch {
    return null;
  }
}

function readLegacySession(): AuthenticatedSession | null {
  if (!isLegacySessionReadEnabled()) {
    return null;
  }
  try {
    return parseStoredSession(
      window.localStorage.getItem(LEGACY_SESSION_STORAGE_KEY),
    );
  } catch {
    return null;
  }
}

/**
 * Returns the in-memory session. When memory is empty it restores, once, the
 * dev `sessionStorage` copy or a session written to `localStorage` by 0.6.x,
 * so users signed in before the deploy stay signed in.
 */
export function readSessionFromStorage(): AuthenticatedSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  const current = getStoredSession();
  if (current) {
    return current;
  }

  const restored = readDevSession() ?? readLegacySession();
  if (restored) {
    primeSession(restored);
  }
  return restored;
}

/**
 * Removes the 0.6.x `localStorage` session after the first successful
 * refresh or authenticated response; memory holds the session from then on.
 */
export function discardLegacySessionStorage(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, blocked site data).
  }
}

export function writeSessionToStorage(session: AuthenticatedSession): void {
  if (typeof window === "undefined") {
    return;
  }
  if (isDevSessionPersistenceEnabled()) {
    try {
      const { refreshToken: _refreshToken, ...sanitizedSession } = session;
      window.sessionStorage.setItem(
        DEV_SESSION_STORAGE_KEY,
        JSON.stringify(sanitizedSession),
      );
    } catch {
      // Storage can be unavailable (private mode, blocked site data).
    }
  }
  setStoredSession(session);
}

export function clearSessionStorage(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY);
    window.sessionStorage.removeItem(DEV_SESSION_STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, blocked site data).
  }
  clearStoredSession();
}

function normalizeNextPath(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }

  const trimmed = path.trim();
  if (!trimmed.startsWith("/")) {
    return null;
  }
  if (trimmed.startsWith("/login")) {
    return null;
  }
  return trimmed;
}

export function buildLoginRedirectUrl(params: {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  nextPath?: string | null;
}): string {
  const query = new URLSearchParams();
  query.set("reason", params.reason);

  if (params.preserveNextPath) {
    const normalizedNext = normalizeNextPath(params.nextPath);
    if (normalizedNext) {
      query.set("next", normalizedNext);
    }
  }

  return `/login?${query.toString()}`;
}

export function getAuthBoundaryMessageKey(
  reason: string | null | undefined,
): "signedOut" | "sessionExpired" | "sessionRevoked" | "sessionInvalid" | null {
  if (reason === "signed_out") return "signedOut";
  if (reason === "session_expired") return "sessionExpired";
  if (reason === "session_revoked") return "sessionRevoked";
  if (reason === "session_invalid" || reason === "session_refresh_failed")
    return "sessionInvalid";
  return null;
}

export function emitAuthBoundaryEvent(params: {
  reason: AuthBoundaryReason;
  preserveNextPath: boolean;
  nextPath?: string | null;
}): AuthBoundaryEventDetail {
  const redirectTo = buildLoginRedirectUrl({
    reason: params.reason,
    preserveNextPath: params.preserveNextPath,
    nextPath: params.nextPath,
  });

  const detail: AuthBoundaryEventDetail = {
    reason: params.reason,
    preserveNextPath: params.preserveNextPath,
    redirectTo,
    occurredAt: Date.now(),
  };

  if (typeof window === "undefined") {
    return detail;
  }

  try {
    window.dispatchEvent(
      new CustomEvent<AuthBoundaryEventDetail>(AUTH_BOUNDARY_EVENT_NAME, {
        detail,
      }),
    );
    window.localStorage.setItem(
      AUTH_BOUNDARY_STORAGE_KEY,
      JSON.stringify({
        ...detail,
        nonce: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      }),
    );
  } catch {
    // Ignore browser storage/event failures.
  }

  return detail;
}

export function subscribeAuthBoundaryEvents(
  onBoundaryEvent: (event: AuthBoundaryEventDetail) => void,
): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  function onWindowEvent(event: Event): void {
    const custom = event as CustomEvent<AuthBoundaryEventDetail>;
    if (!custom.detail) {
      return;
    }
    onBoundaryEvent(custom.detail);
  }

  function onStorageEvent(event: StorageEvent): void {
    if (event.key !== AUTH_BOUNDARY_STORAGE_KEY || !event.newValue) {
      return;
    }

    try {
      const parsed = JSON.parse(
        event.newValue,
      ) as Partial<AuthBoundaryEventDetail>;
      if (
        typeof parsed.reason !== "string" ||
        typeof parsed.preserveNextPath !== "boolean" ||
        typeof parsed.redirectTo !== "string" ||
        typeof parsed.occurredAt !== "number"
      ) {
        return;
      }

      onBoundaryEvent({
        reason: parsed.reason as AuthBoundaryReason,
        preserveNextPath: parsed.preserveNextPath,
        redirectTo: parsed.redirectTo,
        occurredAt: parsed.occurredAt,
      });
    } catch {
      // Ignore malformed events.
    }
  }

  window.addEventListener(
    AUTH_BOUNDARY_EVENT_NAME,
    onWindowEvent as EventListener,
  );
  window.addEventListener("storage", onStorageEvent);

  return () => {
    window.removeEventListener(
      AUTH_BOUNDARY_EVENT_NAME,
      onWindowEvent as EventListener,
    );
    window.removeEventListener("storage", onStorageEvent);
  };
}
